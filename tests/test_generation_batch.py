import copy
import json
from pathlib import Path

import openpyxl
import pytest

from docflow.application.generation import FAILED, PASS, generate_batch


def _write_batch(tmp_path: Path, records: list[dict], name: str = "batch.json") -> Path:
    path = tmp_path / name
    path.write_text(json.dumps(records, ensure_ascii=False), encoding="utf-8")
    return path


def test_same_fact_pack_generates_both_documents(
    sample_batch_dict, contract_template_path, delivery_template_path, tmp_path
):
    batch_path = _write_batch(tmp_path, [sample_batch_dict])
    output_dir = tmp_path / "output"

    summary = generate_batch(batch_path, contract_template_path, delivery_template_path, output_dir)

    assert summary.total_records == 1
    assert summary.passed_documents == 2
    assert summary.failed_documents == 0

    ref = sample_batch_dict["business_reference"]
    assert (output_dir / ref / "procurement-contract.xlsx").exists()
    assert (output_dir / ref / "delivery-note.xlsx").exists()


def test_one_failing_record_does_not_abort_batch(
    sample_batch_dict, contract_template_path, delivery_template_path, tmp_path
):
    broken = copy.deepcopy(sample_batch_dict)
    broken["business_reference"] = "BR-BROKEN"
    del broken["buyer"]  # missing required field -> should FAIL, not raise

    good = copy.deepcopy(sample_batch_dict)
    good["business_reference"] = "BR-GOOD"

    batch_path = _write_batch(tmp_path, [broken, good])
    output_dir = tmp_path / "output"

    summary = generate_batch(batch_path, contract_template_path, delivery_template_path, output_dir)

    assert summary.total_records == 2
    assert summary.passed_documents == 2  # only the good record's 2 documents
    assert summary.failed_documents == 2  # the broken record's 2 documents

    good_entries = [e for e in summary.entries if e.business_reference == "BR-GOOD"]
    broken_entries = [e for e in summary.entries if e.business_reference == "BR-BROKEN"]
    assert all(e.validation_status == PASS for e in good_entries)
    assert all(e.validation_status == FAILED for e in broken_entries)
    assert all(e.issues for e in broken_entries)
    assert (output_dir / "BR-GOOD" / "procurement-contract.xlsx").exists()
    assert not (output_dir / "BR-BROKEN").exists()


def test_manifest_is_written_and_structurally_correct(
    sample_batch_dict, contract_template_path, delivery_template_path, tmp_path
):
    batch_path = _write_batch(tmp_path, [sample_batch_dict])
    output_dir = tmp_path / "output"

    generate_batch(batch_path, contract_template_path, delivery_template_path, output_dir)

    manifest_path = output_dir / "manifest.json"
    assert manifest_path.exists()
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

    assert len(manifest) == 2
    required_fields = {
        "business_reference", "document_type", "template_id", "template_version",
        "output_file", "validation_status", "issues", "source_snapshot_hash",
    }
    for entry in manifest:
        assert required_fields <= entry.keys()
        assert entry["validation_status"] == "PASS"
        assert (output_dir / entry["output_file"]).exists()


def test_same_input_produces_stable_business_content(
    sample_batch_dict, contract_template_path, delivery_template_path, tmp_path
):
    batch_path = _write_batch(tmp_path, [sample_batch_dict])

    summary_a = generate_batch(batch_path, contract_template_path, delivery_template_path, tmp_path / "out-a")
    summary_b = generate_batch(batch_path, contract_template_path, delivery_template_path, tmp_path / "out-b")

    manifest_a = json.loads((tmp_path / "out-a" / "manifest.json").read_text(encoding="utf-8"))
    manifest_b = json.loads((tmp_path / "out-b" / "manifest.json").read_text(encoding="utf-8"))
    assert manifest_a == manifest_b

    wb_a = openpyxl.load_workbook(tmp_path / "out-a" / summary_a.entries[0].output_file)
    wb_b = openpyxl.load_workbook(tmp_path / "out-b" / summary_b.entries[0].output_file)
    ws_a = wb_a[wb_a.sheetnames[0]]
    ws_b = wb_b[wb_b.sheetnames[0]]
    assert ws_a["A3"].value == ws_b["A3"].value
    assert ws_a["I9"].value == ws_b["I9"].value
