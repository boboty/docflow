"""Load and validate a YAML-backed Catalog.

File layout under a catalog root:

    <root>/organizations.yaml   {"organizations": {<id>: {...}, ...}}
    <root>/products.yaml        {"products": {<id>: {...}, ...}}
    <root>/templates.yaml       {"templates": {<key>: {...}, ...}}

A missing file (or a missing top-level key inside it) is treated as an
empty section - a catalog that doesn't exist yet at all is a valid, empty
catalog (this is what lets `catalog apply` bootstrap one from nothing).
A file that exists but fails to parse, or fails structural/semantic
validation (duplicate default contact/address, duplicate ids, missing
required fields), raises CatalogError - never a bare exception type.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import yaml

from docflow.catalog.models import Address, Catalog, Contact, Organization, Product, Seal, TemplateEntry

_WHITESPACE_RE = re.compile(r"\s+")


class CatalogError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


def normalize(value: str) -> str:
    """Deterministic-only normalization: trim, casefold, collapse spaces.

    Deliberately no edit distance, no pinyin guessing, no fuzzy/embedding
    matching - see Reference Catalog v0 section 8.
    """
    return _WHITESPACE_RE.sub(" ", value.strip()).casefold()


def _load_yaml_section(path: Path, top_key: str) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        with path.open("r", encoding="utf-8") as f:
            raw = yaml.safe_load(f)
    except yaml.YAMLError as exc:
        raise CatalogError("INVALID_CATALOG", f"invalid YAML in {path}: {exc}") from exc

    if raw is None:
        return {}
    if not isinstance(raw, dict):
        raise CatalogError("INVALID_CATALOG", f"{path} must contain a YAML mapping")

    section = raw.get(top_key, {})
    if section is None:
        return {}
    if not isinstance(section, dict):
        raise CatalogError("INVALID_CATALOG", f"{path}: '{top_key}' must be a mapping")
    return section


def _require_str(raw: dict, key: str, where: str) -> str:
    value = raw.get(key)
    if not isinstance(value, str) or not value:
        raise CatalogError("INVALID_CATALOG", f"{where}: '{key}' must be a non-empty string")
    return value


def _optional_str(raw: dict, key: str, where: str) -> str | None:
    value = raw.get(key)
    if value is None:
        return None
    if not isinstance(value, str):
        raise CatalogError("INVALID_CATALOG", f"{where}: '{key}' must be a string")
    return value


def _str_list(raw: dict, key: str, where: str) -> tuple[str, ...]:
    value = raw.get(key) or []
    if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
        raise CatalogError("INVALID_CATALOG", f"{where}: '{key}' must be a list of strings")
    return tuple(value)


def _check_unique_ids(ids: list[str], where: str) -> None:
    seen = set()
    for id_ in ids:
        if id_ in seen:
            raise CatalogError("INVALID_CATALOG", f"{where}: duplicate id {id_!r}")
        seen.add(id_)


def _parse_contact(raw: Any, where: str) -> Contact:
    if not isinstance(raw, dict):
        raise CatalogError("INVALID_CATALOG", f"{where}: contact must be a mapping")
    cid = _require_str(raw, "id", where)
    return Contact(
        id=cid,
        name=_require_str(raw, "name", f"{where}.contacts[{cid!r}]"),
        label=_optional_str(raw, "label", f"{where}.contacts[{cid!r}]"),
        phone=_optional_str(raw, "phone", f"{where}.contacts[{cid!r}]"),
        default=bool(raw.get("default", False)),
    )


def _parse_address(raw: Any, where: str) -> Address:
    if not isinstance(raw, dict):
        raise CatalogError("INVALID_CATALOG", f"{where}: address must be a mapping")
    aid = _require_str(raw, "id", where)
    return Address(
        id=aid,
        address=_require_str(raw, "address", f"{where}.addresses[{aid!r}]"),
        label=_optional_str(raw, "label", f"{where}.addresses[{aid!r}]"),
        default=bool(raw.get("default", False)),
    )


def _parse_organization(org_id: str, raw: Any) -> Organization:
    where = f"organizations.{org_id}"
    if not isinstance(raw, dict):
        raise CatalogError("INVALID_CATALOG", f"{where} must be a mapping")

    contacts = tuple(_parse_contact(c, where) for c in (raw.get("contacts") or []))
    addresses = tuple(_parse_address(a, where) for a in (raw.get("addresses") or []))
    _check_unique_ids([c.id for c in contacts], f"{where}.contacts")
    _check_unique_ids([a.id for a in addresses], f"{where}.addresses")

    default_contacts = [c for c in contacts if c.default]
    if len(default_contacts) > 1:
        raise CatalogError("INVALID_CATALOG", f"{where}: multiple default contacts ({[c.id for c in default_contacts]})")
    default_addresses = [a for a in addresses if a.default]
    if len(default_addresses) > 1:
        raise CatalogError("INVALID_CATALOG", f"{where}: multiple default addresses ({[a.id for a in default_addresses]})")

    seal_raw = raw.get("seal")
    if seal_raw is not None and not isinstance(seal_raw, dict):
        raise CatalogError("INVALID_CATALOG", f"{where}: 'seal' must be a mapping")
    seal = Seal(path=_require_str(seal_raw, "path", f"{where}.seal")) if seal_raw is not None else None

    return Organization(
        id=org_id,
        name=_require_str(raw, "name", where),
        roles=_str_list(raw, "roles", where),
        aliases=_str_list(raw, "aliases", where),
        contacts=contacts,
        addresses=addresses,
        seal=seal,
    )


def _parse_product(product_id: str, raw: Any) -> Product:
    where = f"products.{product_id}"
    if not isinstance(raw, dict):
        raise CatalogError("INVALID_CATALOG", f"{where} must be a mapping")
    return Product(
        id=product_id,
        name=_require_str(raw, "name", where),
        specification=_optional_str(raw, "specification", where),
        unit=_optional_str(raw, "unit", where),
        aliases=_str_list(raw, "aliases", where),
    )


def _parse_template(key: str, raw: Any) -> TemplateEntry:
    where = f"templates.{key}"
    if not isinstance(raw, dict):
        raise CatalogError("INVALID_CATALOG", f"{where} must be a mapping")
    return TemplateEntry(
        key=key,
        document_type=_require_str(raw, "document_type", where),
        path=_require_str(raw, "path", where),
    )


def parse_catalog_dict(
    organizations_raw: dict[str, Any],
    products_raw: dict[str, Any],
    templates_raw: dict[str, Any],
) -> Catalog:
    """Parse+validate already-loaded raw dicts (shared by loader and mutation,
    so a candidate post-mutation state is validated with the exact same
    rules as a catalog freshly read from disk)."""
    organizations = {org_id: _parse_organization(org_id, raw) for org_id, raw in organizations_raw.items()}
    products = {product_id: _parse_product(product_id, raw) for product_id, raw in products_raw.items()}
    templates = {key: _parse_template(key, raw) for key, raw in templates_raw.items()}
    return Catalog(organizations=organizations, products=products, templates=templates)


def load_raw_sections(root: Path) -> tuple[dict, dict, dict]:
    organizations_raw = _load_yaml_section(root / "organizations.yaml", "organizations")
    products_raw = _load_yaml_section(root / "products.yaml", "products")
    templates_raw = _load_yaml_section(root / "templates.yaml", "templates")
    return organizations_raw, products_raw, templates_raw


def load_catalog(root: Path) -> Catalog:
    organizations_raw, products_raw, templates_raw = load_raw_sections(root)
    return parse_catalog_dict(organizations_raw, products_raw, templates_raw)
