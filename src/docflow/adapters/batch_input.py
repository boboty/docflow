"""JSON batch input adapter.

Converts one raw batch record (a plain dict, as parsed from a JSON array)
into a DocumentFactPack. This is the only place that knows about the JSON
batch layout - the engine (domain/rules/templates) never depends on it, so
a future Excel batch adapter can be added without touching the engine.
"""
from __future__ import annotations

import json
from datetime import date
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from docflow.domain.facts import DocumentFactPack, LineItemFacts, ShipTo


class BatchFileError(Exception):
    """Whole-file structural error (not a single record's fault)."""


class BatchRecordError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


def load_batch_records(path: Path) -> list[dict[str, Any]]:
    try:
        with path.open("r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError) as exc:
        raise BatchFileError(f"cannot read batch file {path}: {exc}") from exc

    if not isinstance(data, list):
        raise BatchFileError(f"batch file {path} must contain a JSON array of records")
    return data


def _require(raw: dict[str, Any], key: str) -> Any:
    if key not in raw or raw[key] in (None, ""):
        raise BatchRecordError("MISSING_FIELD", f"missing required field: {key}")
    return raw[key]


def _decimal(raw: dict[str, Any], key: str) -> Decimal:
    value = _require(raw, key)
    try:
        return Decimal(str(value))
    except InvalidOperation as exc:
        raise BatchRecordError("INVALID_DECIMAL", f"field {key} is not a valid decimal: {value!r}") from exc


def _date(raw: dict[str, Any], key: str) -> date:
    value = _require(raw, key)
    try:
        return date.fromisoformat(str(value))
    except ValueError as exc:
        raise BatchRecordError("INVALID_DATE", f"field {key} is not ISO date (YYYY-MM-DD): {value!r}") from exc


def _ship_to(raw: dict[str, Any]) -> ShipTo:
    ship_to_raw = raw.get("ship_to")
    if not isinstance(ship_to_raw, dict):
        raise BatchRecordError("MISSING_FIELD", "missing required object field: ship_to")
    return ShipTo(
        company=str(_require(ship_to_raw, "company")),
        contact=str(_require(ship_to_raw, "contact")),
        phone=str(_require(ship_to_raw, "phone")),
        address=str(_require(ship_to_raw, "address")),
    )


def _line_item(raw: dict[str, Any], index: int) -> LineItemFacts:
    try:
        return LineItemFacts(
            sku=str(_require(raw, "sku")),
            product_name=str(_require(raw, "product_name")),
            specification=str(_require(raw, "specification")),
            quantity=_decimal(raw, "quantity"),
            unit=str(_require(raw, "unit")),
            net_unit_price=_decimal(raw, "net_unit_price"),
            tax_rate=_decimal(raw, "tax_rate"),
            remarks=raw.get("remarks"),
        )
    except BatchRecordError as exc:
        raise BatchRecordError(exc.code, f"items[{index}]: {exc}") from exc


def fact_pack_from_record(raw: dict[str, Any]) -> DocumentFactPack:
    items_raw = raw.get("items")
    if not isinstance(items_raw, list) or not items_raw:
        raise BatchRecordError("MISSING_FIELD", "missing required non-empty array field: items")

    return DocumentFactPack(
        business_reference=str(_require(raw, "business_reference")),
        contract_no=str(_require(raw, "contract_no")),
        delivery_no=str(_require(raw, "delivery_no")),
        contract_date=_date(raw, "contract_date"),
        delivery_date=_date(raw, "delivery_date"),
        buyer=str(_require(raw, "buyer")),
        seller=str(_require(raw, "seller")),
        ship_to=_ship_to(raw),
        items=tuple(_line_item(item, i) for i, item in enumerate(items_raw)),
        currency=str(raw.get("currency", "CNY")),
        seller_contact=raw.get("seller_contact"),
        seller_phone=raw.get("seller_phone"),
        seller_address=raw.get("seller_address"),
        extra=dict(raw.get("extra", {})),
    )
