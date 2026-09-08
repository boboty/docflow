"""Explicit-confirmation-only Catalog mutation.

There is no auto-learning and no implicit write path: this module is only
ever invoked when a user has explicitly confirmed a change (see
skills/docflow/SKILL.md). An apply is all-or-nothing - every operation in
the batch is validated against the resulting *candidate* catalog state
before anything is written to disk, and the write itself is atomic
per-file (write-temp-then-rename). No delete, no merge, no history: only
upsert_organization / upsert_contact / upsert_address / upsert_product /
set_template, matching Reference Catalog v0 section 13 exactly.
"""
from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

import yaml

from docflow.catalog.loader import load_catalog, load_raw_sections, parse_catalog_dict

_KNOWN_OPERATIONS = {
    "upsert_organization",
    "upsert_contact",
    "upsert_address",
    "upsert_product",
    "set_template",
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


def _apply_set_template(op: dict, index: int, templates_raw: dict) -> None:
    key = _require_str(op, "key", index)
    document_type = _require_str(op, "document_type", index)
    path = _require_str(op, "path", index)
    templates_raw[key] = {"document_type": document_type, "path": path}


def _apply_one(op: Any, index: int, organizations_raw: dict, products_raw: dict, templates_raw: dict) -> None:
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
    elif operation == "set_template":
        _apply_set_template(op, index, templates_raw)


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
    templates_raw = copy.deepcopy(templates_raw)

    for index, op in enumerate(operations):
        _apply_one(op, index, organizations_raw, products_raw, templates_raw)

    # Validate the candidate state with the exact same rules a fresh load
    # would apply, BEFORE writing anything.
    parse_catalog_dict(organizations_raw, products_raw, templates_raw)

    _write_yaml_atomic(root / "organizations.yaml", "organizations", organizations_raw)
    _write_yaml_atomic(root / "products.yaml", "products", products_raw)
    _write_yaml_atomic(root / "templates.yaml", "templates", templates_raw)

    # Re-validate from disk - defensive, but explicit per spec.
    load_catalog(root)
