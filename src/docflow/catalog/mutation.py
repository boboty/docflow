"""Explicit-confirmation-only Catalog mutation.

There is no auto-learning and no implicit write path: this module is only
ever invoked when a user has explicitly confirmed a change (see
skills/docflow/SKILL.md).

Two distinct mutation paths, matching a clean ownership boundary:

  - `apply_operations()` / `catalog apply`: stable YAML facts only
    (organizations, contacts, addresses, products). All-or-nothing - every
    operation in the batch is validated against the resulting *candidate*
    catalog state before anything is written to disk, and the write itself
    is atomic per-file (write-temp-then-rename).
  - `import_template()` / `catalog import-template`: the ONLY way to
    register a template. There is deliberately no `set_template` operation
    in `apply_operations` - a template is a binary asset plus a Catalog
    entry, not a plain fact, and letting `catalog apply` accept an
    arbitrary external path would let an agent bypass the whole
    managed-copy lifecycle (Managed Template Lifecycle section 11). This
    module intentionally imports `docflow.templates`/`docflow.renderers`
    (the Engine's own template registry and xlsx preflight) specifically
    so a proposed template is validated with the exact same rules
    `docflow generate` would apply to it - not a re-implementation of that
    validation.
  - `import_seal()` / `catalog import-seal`: validates and atomically
    manages one PNG plus its organization `seal.path` entry.
"""
from __future__ import annotations

import copy
import io
import json
import re
import shutil
from pathlib import Path
from typing import Any

import yaml

from docflow.catalog.loader import load_catalog, load_raw_sections, parse_catalog_dict
from docflow.catalog.root import managed_seal_root, managed_template_root
from docflow.domain.document import DocumentType
from docflow.renderers.xlsx import preflight
from docflow.templates.definition import TemplateDefinitionError
from docflow.templates.registry import TemplateRegistry

_KNOWN_OPERATIONS = {
    "upsert_organization",
    "upsert_contact",
    "upsert_address",
    "upsert_product",
}

MANAGED_TEMPLATE_TYPES = {
    "procurement_contract": DocumentType.PROCUREMENT_CONTRACT_V1,
    "delivery_note": DocumentType.DELIVERY_NOTE_V1,
}


class CatalogMutationError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


class ChangeFileError(Exception):
    """Whole-file structural error in the change.json input (not one
    operation's fault - nothing in it is trustworthy enough to apply
    anything)."""


def load_operations(path: Path) -> list[dict[str, Any]]:
    try:
        with path.open("r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError) as exc:
        raise ChangeFileError(f"cannot read change file {path}: {exc}") from exc
    if not isinstance(data, list) or not data:
        raise ChangeFileError(f"change file {path} must contain a non-empty JSON array of operations")
    return data


def _require_str(op: dict, key: str, index: int) -> str:
    value = op.get(key)
    if not isinstance(value, str) or not value:
        raise CatalogMutationError("INVALID_OPERATION", f"operations[{index}]: '{key}' must be a non-empty string")
    return value


def _apply_upsert_organization(op: dict, index: int, organizations_raw: dict) -> None:
    org_id = _require_str(op, "id", index)
    existing = organizations_raw.get(org_id, {})
    updated = dict(existing)

    if "name" in op:
        updated["name"] = op["name"]
    elif "name" not in existing:
        raise CatalogMutationError("INVALID_OPERATION", f"operations[{index}]: new organization {org_id!r} requires 'name'")
    if "roles" in op:
        updated["roles"] = op["roles"]
    if "aliases" in op:
        updated["aliases"] = op["aliases"]
    updated.setdefault("contacts", existing.get("contacts", []))
    updated.setdefault("addresses", existing.get("addresses", []))
    organizations_raw[org_id] = updated


def _apply_upsert_sub_entry(op: dict, index: int, organizations_raw: dict, entry_key: str, collection_key: str) -> None:
    org_id = _require_str(op, "organization", index)
    if org_id not in organizations_raw:
        raise CatalogMutationError(
            "ORGANIZATION_NOT_FOUND",
            f"operations[{index}]: organization {org_id!r} does not exist - upsert_organization first",
        )
    entry = op.get(entry_key)
    if not isinstance(entry, dict) or not entry.get("id"):
        raise CatalogMutationError("INVALID_OPERATION", f"operations[{index}]: '{entry_key}' must be an object with an 'id'")

    org = dict(organizations_raw[org_id])
    collection = list(org.get(collection_key, []))

    if entry.get("default"):
        other_defaults = [e for e in collection if e.get("id") != entry["id"] and e.get("default")]
        if other_defaults:
            raise CatalogMutationError(
                "DUPLICATE_DEFAULT",
                f"operations[{index}]: organization {org_id!r} already has a default {entry_key} "
                f"({other_defaults[0].get('id')!r}) - demote it explicitly in the same apply first",
            )

    collection = [e for e in collection if e.get("id") != entry["id"]] + [entry]
    org[collection_key] = collection
    organizations_raw[org_id] = org


def _apply_upsert_product(op: dict, index: int, products_raw: dict) -> None:
    product_id = _require_str(op, "id", index)
    product = op.get("product")
    if not isinstance(product, dict) or not product.get("name"):
        raise CatalogMutationError("INVALID_OPERATION", f"operations[{index}]: 'product' must be an object with a 'name'")
    products_raw[product_id] = product


def _apply_one(op: Any, index: int, organizations_raw: dict, products_raw: dict) -> None:
    if not isinstance(op, dict):
        raise CatalogMutationError("INVALID_OPERATION", f"operations[{index}] must be an object")
    operation = op.get("operation")
    if operation not in _KNOWN_OPERATIONS:
        raise CatalogMutationError("UNKNOWN_OPERATION", f"operations[{index}]: unknown operation {operation!r}")

    if operation == "upsert_organization":
        _apply_upsert_organization(op, index, organizations_raw)
    elif operation == "upsert_contact":
        _apply_upsert_sub_entry(op, index, organizations_raw, "contact", "contacts")
    elif operation == "upsert_address":
        _apply_upsert_sub_entry(op, index, organizations_raw, "address", "addresses")
    elif operation == "upsert_product":
        _apply_upsert_product(op, index, products_raw)


def _write_yaml_atomic(path: Path, top_key: str, section: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_name(path.name + ".tmp")
    with tmp_path.open("w", encoding="utf-8") as f:
        yaml.safe_dump({top_key: section}, f, allow_unicode=True, sort_keys=False)
    tmp_path.replace(path)


def apply_operations(root: Path, operations: list[dict[str, Any]]) -> None:
    organizations_raw, products_raw, templates_raw = load_raw_sections(root)
    organizations_raw = copy.deepcopy(organizations_raw)
    products_raw = copy.deepcopy(products_raw)

    for index, op in enumerate(operations):
        _apply_one(op, index, organizations_raw, products_raw)

    # Validate the candidate state with the exact same rules a fresh load
    # would apply, BEFORE writing anything. templates_raw is untouched by
    # this function (see module docstring - templates go through
    # import_template instead) but is still passed through so the
    # validation covers the whole real catalog, not a fragment of it.
    parse_catalog_dict(organizations_raw, products_raw, templates_raw)

    _write_yaml_atomic(root / "organizations.yaml", "organizations", organizations_raw)
    _write_yaml_atomic(root / "products.yaml", "products", products_raw)

    # Re-validate from disk - defensive, but explicit per spec.
    load_catalog(root)


def import_template(catalog_root: Path, key: str, document_type: str, source: Path, replace: bool) -> None:
    """The only sanctioned way to register a template (see module
    docstring). Order matters for failure safety (Managed Template
    Lifecycle section 7): every validation that can fail happens before
    any filesystem mutation. The managed binary is committed before the
    catalog YAML, with the prior binary and YAML bytes retained until the
    final reload succeeds so any later failure can restore both resources.
    """
    canonical_doc_type = MANAGED_TEMPLATE_TYPES.get(key)
    if canonical_doc_type is None:
        raise CatalogMutationError(
            "UNSUPPORTED_TEMPLATE_KEY",
            f"{key!r} is not a supported template key "
            f"(expected one of: {list(MANAGED_TEMPLATE_TYPES)})",
        )

    try:
        doc_type = DocumentType(document_type)
    except ValueError as exc:
        raise CatalogMutationError(
            "UNSUPPORTED_DOCUMENT_TYPE",
            f"{document_type!r} is not a supported document type "
            f"(expected one of: {[d.value for d in DocumentType]})",
        ) from exc

    if doc_type is not canonical_doc_type:
        raise CatalogMutationError(
            "TEMPLATE_IDENTITY_MISMATCH",
            f"template key {key!r} requires document type {canonical_doc_type.value!r}, "
            f"not {document_type!r}",
        )

    registry = TemplateRegistry()
    try:
        definition = registry.get(doc_type)
    except (FileNotFoundError, TemplateDefinitionError) as exc:
        raise CatalogMutationError("TEMPLATE_MAPPING_INVALID", str(exc)) from exc

    # Reuses the exact preflight docflow generate would run: file exists,
    # is a valid xlsx, has the mapped sheet, every header/text placeholder
    # and item column is valid, no mapped cell is a non-anchor merged
    # cell. Raises TemplatePreflightError (not caught here - it already
    # carries a clear code/message) on any problem; nothing has been
    # written yet at this point.
    preflight(definition, source)

    organizations_raw, products_raw, templates_raw = load_raw_sections(catalog_root)

    if key in templates_raw and not replace:
        raise CatalogMutationError(
            "TEMPLATE_ALREADY_EXISTS",
            f"template {key!r} is already registered - pass --replace to overwrite it",
        )

    # `key` has already been resolved through MANAGED_TEMPLATE_TYPES. It
    # is the canonical identity, not user input to slugify or sanitize.
    filename = f"{key}.xlsx"
    managed_dir = managed_template_root(catalog_root)
    managed_dir.mkdir(parents=True, exist_ok=True)
    final_path = managed_dir / filename
    tmp_path = managed_dir / f".{filename}.tmp"
    backup_path = managed_dir / f".{filename}.bak"
    # Relative to catalog_root (managed_template_root is always its fixed
    # sibling "templates" dir) - so a moved/copied workspace keeps working
    # without rewriting the Catalog. See resolve.resolve_template_path.
    relative_path = f"../templates/{filename}"

    candidate_templates_raw = dict(templates_raw)
    candidate_templates_raw[key] = {"document_type": canonical_doc_type.value, "path": relative_path}

    # Validate the candidate catalog state BEFORE committing anything.
    parse_catalog_dict(organizations_raw, products_raw, candidate_templates_raw)

    catalog_path = catalog_root / "templates.yaml"
    catalog_existed = catalog_path.exists()
    catalog_bytes = catalog_path.read_bytes() if catalog_existed else None
    managed_existed = final_path.exists()
    backup_ready = False
    final_replaced = False

    try:
        shutil.copyfile(source, tmp_path)
        if managed_existed:
            shutil.copyfile(final_path, backup_path)
            backup_ready = True
        tmp_path.replace(final_path)
        final_replaced = True
        _write_yaml_atomic(catalog_path, "templates", candidate_templates_raw)
        load_catalog(catalog_root)
    except Exception as exc:
        # Restore both observable resources to their exact pre-call state.
        # This deliberately does not call the injectable YAML writer: that
        # is the component whose failure may have triggered compensation.
        if final_replaced and managed_existed and backup_ready:
            backup_path.replace(final_path)
        elif final_replaced and not managed_existed and final_path.exists():
            final_path.unlink()

        yaml_tmp_path = catalog_path.with_name(catalog_path.name + ".tmp")
        if catalog_existed:
            rollback_path = catalog_path.with_name(catalog_path.name + ".rollback.tmp")
            try:
                rollback_path.write_bytes(catalog_bytes or b"")
                rollback_path.replace(catalog_path)
            finally:
                if rollback_path.exists():
                    rollback_path.unlink()
        elif catalog_path.exists():
            catalog_path.unlink()
        if yaml_tmp_path.exists():
            yaml_tmp_path.unlink()
        raise CatalogMutationError("TEMPLATE_IMPORT_FAILED", f"template import could not be committed: {exc}") from exc
    finally:
        if tmp_path.exists():
            tmp_path.unlink()
        if backup_path.exists():
            backup_path.unlink()


def _normalize_seal_png(source: Path) -> bytes:
    """Crop a seal PNG to its non-transparent (alpha-channel) bounding box
    and center it in a transparent square canvas.

    A source PNG frequently carries incidental transparent padding around
    the actual stamped seal (e.g. exported on a fixed canvas size). A
    template mapping's `printed_diameter_mm` describes the seal's visible
    outer diameter, not the PNG canvas - if that padding survives into the
    managed asset, the renderer's printed-size math (which sizes the whole
    image to `printed_diameter_mm`) ends up shrinking the *visible* seal
    well below the declared diameter. Cropping to the alpha bounding box
    here, once, at import time, makes the managed asset's canvas edge-to-edge
    with the visible seal, so that math is correct for every document
    generated from it afterwards. Only non-transparent pixels are touched -
    none are modified, just relocated onto a fresh transparent canvas.
    """
    from PIL import Image

    with Image.open(source) as opened:
        rgba = opened.convert("RGBA")
        bbox = rgba.getchannel("A").getbbox()
        cropped = rgba.crop(bbox) if bbox is not None else rgba
        side = max(cropped.width, cropped.height)
        canvas = Image.new("RGBA", (side, side), (0, 0, 0, 0))
        offset = ((side - cropped.width) // 2, (side - cropped.height) // 2)
        canvas.paste(cropped, offset, cropped)
        buffer = io.BytesIO()
        canvas.save(buffer, format="PNG")
        return buffer.getvalue()


def import_seal(catalog_root: Path, organization: str, source: Path, replace: bool) -> None:
    """Validate and atomically import one organization's managed PNG seal.

    The managed copy is not a byte-for-byte copy of `source`: it is
    normalized (see `_normalize_seal_png`) so its canvas has no leftover
    transparent padding around the visible seal. `source` itself is never
    modified.
    """
    organizations_raw, products_raw, templates_raw = load_raw_sections(catalog_root)
    if organization not in organizations_raw:
        raise CatalogMutationError("ORGANIZATION_NOT_FOUND", f"organization {organization!r} does not exist")
    if re.fullmatch(r"[A-Za-z0-9._-]+", organization) is None:
        raise CatalogMutationError(
            "INVALID_ORGANIZATION_ID",
            f"organization id {organization!r} cannot be used as a managed seal filename",
        )

    if not source.is_file():
        raise CatalogMutationError("SEAL_SOURCE_MISSING", f"seal source not found: {source}")
    try:
        from PIL import Image
        with Image.open(source) as image:
            image.verify()
            if image.format != "PNG":
                raise ValueError(f"expected PNG, got {image.format or 'unknown'}")
    except (OSError, ValueError) as exc:
        raise CatalogMutationError("SEAL_SOURCE_INVALID", f"cannot read {source} as a PNG image: {exc}") from exc

    managed_dir = managed_seal_root(catalog_root)
    final_path = managed_dir / f"{organization}.png"
    existing_seal = organizations_raw[organization].get("seal")
    if (existing_seal is not None or final_path.exists()) and not replace:
        raise CatalogMutationError(
            "SEAL_ALREADY_EXISTS", f"seal for {organization!r} already exists - pass --replace to overwrite it"
        )

    relative_path = f"../assets/seals/{organization}.png"
    candidate_organizations = copy.deepcopy(organizations_raw)
    candidate_org = dict(candidate_organizations[organization])
    candidate_org["seal"] = {"path": relative_path}
    candidate_organizations[organization] = candidate_org
    parse_catalog_dict(candidate_organizations, products_raw, templates_raw)

    catalog_path = catalog_root / "organizations.yaml"
    catalog_existed = catalog_path.exists()
    catalog_bytes = catalog_path.read_bytes() if catalog_existed else None
    managed_existed = final_path.exists()
    managed_dir.mkdir(parents=True, exist_ok=True)
    tmp_path = managed_dir / f".{organization}.png.tmp"
    backup_path = managed_dir / f".{organization}.png.bak"
    backup_ready = False
    final_replaced = False
    try:
        tmp_path.write_bytes(_normalize_seal_png(source))
        if managed_existed:
            shutil.copyfile(final_path, backup_path)
            backup_ready = True
        tmp_path.replace(final_path)
        final_replaced = True
        _write_yaml_atomic(catalog_path, "organizations", candidate_organizations)
        load_catalog(catalog_root)
    except Exception as exc:
        if final_replaced and managed_existed and backup_ready:
            backup_path.replace(final_path)
        elif final_replaced and not managed_existed and final_path.exists():
            final_path.unlink()
        yaml_tmp_path = catalog_path.with_name(catalog_path.name + ".tmp")
        if catalog_existed:
            rollback_path = catalog_path.with_name(catalog_path.name + ".rollback.tmp")
            try:
                rollback_path.write_bytes(catalog_bytes or b"")
                rollback_path.replace(catalog_path)
            finally:
                if rollback_path.exists():
                    rollback_path.unlink()
        elif catalog_path.exists():
            catalog_path.unlink()
        if yaml_tmp_path.exists():
            yaml_tmp_path.unlink()
        raise CatalogMutationError("SEAL_IMPORT_FAILED", f"seal import could not be committed: {exc}") from exc
    finally:
        if tmp_path.exists():
            tmp_path.unlink()
        if backup_path.exists():
            backup_path.unlink()
