"""Batch generation orchestration.

Wires together: template preflight -> batch input -> validation ->
derivation -> rendering -> manifest.

Two distinct failure scopes (Phase 0 Repair section 5):
  - Template-level (file missing/invalid, sheet missing, mapping invalid):
    the whole batch cannot possibly succeed, so it fails fast via
    TemplatePreflightError / BatchFileError *before* the record loop runs.
  - Record-level (missing fields, bad amounts, over capacity): a single
    record's failure never aborts the batch; it is recorded as FAILED with
    structured issues and processing continues.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from docflow.adapters.batch_input import (
    BatchRecordError,
    fact_pack_from_record,
    load_batch_records,
)
from docflow.domain.document import DocumentProjection, DocumentType, build_projection
from docflow.domain.validation import (
    ValidationResult,
    validate_aggregate_consistency,
    validate_cross_document,
    validate_derived_consistency,
    validate_fact_pack,
    validate_source_consistency,
)
from docflow.renderers.xlsx import TemplatePreflightError, TemplateRenderError, preflight, render
from docflow.templates.definition import TemplateDefinitionError
from docflow.templates.registry import TemplateRegistry

PASS = "PASS"
FAILED = "FAILED"

_OUTPUT_FILENAMES = {
    DocumentType.PROCUREMENT_CONTRACT_V1: "procurement-contract.xlsx",
    DocumentType.DELIVERY_NOTE_V1: "delivery-note.xlsx",
}


@dataclass(frozen=True, slots=True)
class ManifestEntry:
    business_reference: str
    document_type: str
    template_id: str
    template_version: str
    output_file: str | None
    validation_status: str
    issues: tuple[str, ...]
    source_snapshot_hash: str


@dataclass(frozen=True, slots=True)
class BatchSummary:
    total_records: int
    passed_documents: int
    failed_documents: int
    entries: tuple[ManifestEntry, ...]


def _snapshot_hash(raw: Any) -> str:
    canonical = json.dumps(raw, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _template_version(template_id: str) -> str:
    return template_id.rsplit(".", 1)[-1]


def _issue_strings(result: ValidationResult) -> list[str]:
    return [f"{issue.code}: {issue.message}" for issue in result.issues]


def _preflight_templates(registry: TemplateRegistry, template_paths: dict[DocumentType, Path]) -> None:
    """Whole-batch gate: raises if any template/mapping is unusable."""
    for document_type, path in template_paths.items():
        try:
            definition = registry.get(document_type)
        except (FileNotFoundError, TemplateDefinitionError) as exc:
            raise TemplatePreflightError("TEMPLATE_MAPPING_INVALID", str(exc)) from exc
        preflight(definition, path)


def generate_batch(
    batch_file: Path,
    contract_template_path: Path,
    delivery_template_path: Path,
    output_dir: Path,
    registry: TemplateRegistry | None = None,
) -> BatchSummary:
    registry = registry or TemplateRegistry()
    template_paths = {
        DocumentType.PROCUREMENT_CONTRACT_V1: contract_template_path,
        DocumentType.DELIVERY_NOTE_V1: delivery_template_path,
    }

    # Template-level preflight: must happen before any record is touched.
    # Errors here (BatchFileError, TemplatePreflightError) are intentionally
    # NOT caught - they propagate to the caller as a whole-batch failure,
    # never disguised as a per-record FAILED entry.
    _preflight_templates(registry, template_paths)
    raw_records = load_batch_records(batch_file)

    entries: list[ManifestEntry] = []

    for index, raw in enumerate(raw_records):
        business_reference = str(raw.get("business_reference") or f"record-{index}") \
            if isinstance(raw, dict) else f"record-{index}"
        snapshot_hash = _snapshot_hash(raw)

        try:
            fact_pack = fact_pack_from_record(raw)
        except BatchRecordError as exc:
            entries.extend(
                _failed_entries(business_reference, [f"{exc.code}: {exc}"], snapshot_hash)
            )
            continue

        record_issues = _issue_strings(validate_fact_pack(fact_pack))
        record_issues += _issue_strings(validate_source_consistency(fact_pack))
        record_issues += _issue_strings(validate_aggregate_consistency(fact_pack))
        if record_issues:
            entries.extend(
                _failed_entries(fact_pack.business_reference, record_issues, snapshot_hash)
            )
            continue

        contract_projection = build_projection(fact_pack, DocumentType.PROCUREMENT_CONTRACT_V1)
        delivery_projection = build_projection(fact_pack, DocumentType.DELIVERY_NOTE_V1)

        contract_issues = _issue_strings(validate_derived_consistency(contract_projection))
        delivery_issues = _issue_strings(validate_derived_consistency(delivery_projection))

        cross_issues = _issue_strings(validate_cross_document(contract_projection, delivery_projection))
        contract_issues += cross_issues
        delivery_issues += cross_issues

        entries.append(
            _render_or_fail(
                registry, template_paths, output_dir,
                DocumentType.PROCUREMENT_CONTRACT_V1, contract_projection,
                contract_issues, snapshot_hash,
            )
        )
        entries.append(
            _render_or_fail(
                registry, template_paths, output_dir,
                DocumentType.DELIVERY_NOTE_V1, delivery_projection,
                delivery_issues, snapshot_hash,
            )
        )

    _write_manifest(output_dir, entries)

    passed = sum(1 for e in entries if e.validation_status == PASS)
    return BatchSummary(
        total_records=len(raw_records),
        passed_documents=passed,
        failed_documents=len(entries) - passed,
        entries=tuple(entries),
    )


def _failed_entries(business_reference: str, issues: list[str], snapshot_hash: str) -> list[ManifestEntry]:
    return [
        ManifestEntry(
            business_reference=business_reference,
            document_type=doc_type.value,
            template_id=doc_type.value,
            template_version=_template_version(doc_type.value),
            output_file=None,
            validation_status=FAILED,
            issues=tuple(issues),
            source_snapshot_hash=snapshot_hash,
        )
        for doc_type in (DocumentType.PROCUREMENT_CONTRACT_V1, DocumentType.DELIVERY_NOTE_V1)
    ]


def _render_or_fail(
    registry: TemplateRegistry,
    template_paths: dict[DocumentType, Path],
    output_dir: Path,
    document_type: DocumentType,
    projection: DocumentProjection,
    issues: list[str],
    snapshot_hash: str,
) -> ManifestEntry:
    definition = registry.get(document_type)

    if issues:
        return ManifestEntry(
            business_reference=projection.business_reference,
            document_type=document_type.value,
            template_id=definition.id,
            template_version=_template_version(definition.id),
            output_file=None,
            validation_status=FAILED,
            issues=tuple(issues),
            source_snapshot_hash=snapshot_hash,
        )

    relative_output = Path(projection.business_reference) / _OUTPUT_FILENAMES[document_type]
    output_path = output_dir / relative_output

    try:
        render(definition, template_paths[document_type], projection, output_path)
    except TemplateRenderError as exc:
        return ManifestEntry(
            business_reference=projection.business_reference,
            document_type=document_type.value,
            template_id=definition.id,
            template_version=_template_version(definition.id),
            output_file=None,
            validation_status=FAILED,
            issues=(f"{exc.code}: {exc}",),
            source_snapshot_hash=snapshot_hash,
        )

    return ManifestEntry(
        business_reference=projection.business_reference,
        document_type=document_type.value,
        template_id=definition.id,
        template_version=_template_version(definition.id),
        output_file=str(relative_output),
        validation_status=PASS,
        issues=(),
        source_snapshot_hash=snapshot_hash,
    )


def _write_manifest(output_dir: Path, entries: list[ManifestEntry]) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = output_dir / "manifest.json"
    payload = [dict(asdict(e), issues=list(e.issues)) for e in entries]
    with manifest_path.open("w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
