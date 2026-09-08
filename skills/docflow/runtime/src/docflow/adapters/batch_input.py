"""JSON batch input adapter.

Converts one raw batch record (a plain dict, as parsed from a JSON array)
into a DocumentFactPack. This is the only place that knows about the JSON
batch layout - the engine (domain/rules/templates) never depends on it, so
a future Excel batch adapter can be added without touching the engine.

Robustness policy (Phase 0 Repair section 6): every place that reads a
value out of untrusted JSON input validates its shape explicitly and
raises BatchRecordError with a code, rather than letting a malformed
record's TypeError/AttributeError/KeyError escape as an unhandled
exception that would abort the whole batch. This module deliberately does
NOT wrap everything in a blanket ``except Exception`` - that would also
hide genuine docflow bugs. Each validation is narrow and explicit instead.
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


def _require_dict(value: Any, what: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise BatchRecordError("INVALID_RECORD_SHAPE", f"{what} must be a JSON object, got {type(value).__name__}")
    return value


def _require(raw: dict[str, Any], key: str) -> Any:
    if key not in raw or raw[key] in (None, ""):
        raise BatchRecordError("MISSING_FIELD", f"missing required field: {key}")
    return raw[key]


def _optional_str(raw: dict[str, Any], key: str) -> str | None:
    value = raw.get(key)
    if value is None:
        return None
    return str(value)


def _parse_decimal(key: str, value: Any) -> Decimal:
    try:
        parsed = Decimal(str(value))
    except InvalidOperation as exc:
        raise BatchRecordError("INVALID_DECIMAL", f"field {key} is not a valid decimal: {value!r}") from exc
    if not parsed.is_finite():
        # Decimal("NaN") / Decimal("Infinity") / Decimal("-Infinity") all
        # parse successfully but are not usable amounts - reject them here,
        # at the input boundary, rather than let arithmetic on them raise
        # decimal.InvalidOperation deep inside money/validation code.
        raise BatchRecordError("NON_FINITE_DECIMAL", f"field {key} must be a finite number, got {value!r}")
    return parsed


def _decimal(raw: dict[str, Any], key: str) -> Decimal:
    return _parse_decimal(key, _require(raw, key))


def _date(raw: dict[str, Any], key: str) -> date:
    value = _require(raw, key)
    try:
        return date.fromisoformat(str(value))
    except ValueError as exc:
        raise BatchRecordError("INVALID_DATE", f"field {key} is not ISO date (YYYY-MM-DD): {value!r}") from exc


def _ship_to(raw: dict[str, Any]) -> ShipTo:
    ship_to_raw = _require_dict(raw.get("ship_to"), "ship_to")
    return ShipTo(
        company=str(_require(ship_to_raw, "company")),
        contact=str(_require(ship_to_raw, "contact")),
        phone=str(_require(ship_to_raw, "phone")),
        address=str(_require(ship_to_raw, "address")),
    )


def _line_item(raw: Any, index: int) -> LineItemFacts:
    try:
        item_raw = _require_dict(raw, f"items[{index}]")
        return LineItemFacts(
            sku=str(_require(item_raw, "sku")),
            product_name=str(_require(item_raw, "product_name")),
            specification=str(_require(item_raw, "specification")),
            quantity=_decimal(item_raw, "quantity"),
            unit=str(_require(item_raw, "unit")),
            gross_unit_price=_decimal(item_raw, "gross_unit_price"),
            gross_amount=_decimal(item_raw, "gross_amount"),
            tax_rate=_decimal(item_raw, "tax_rate"),
            remarks=_optional_str(item_raw, "remarks"),
        )
    except BatchRecordError as exc:
        raise BatchRecordError(exc.code, f"items[{index}]: {exc}") from exc


def _optional_decimal(raw: dict[str, Any], key: str) -> Decimal | None:
    if raw.get(key) is None:
        return None
    return _parse_decimal(key, raw[key])


def _extra(raw: dict[str, Any]) -> dict[str, str]:
    extra_raw = raw.get("extra", {})
    extra_raw = _require_dict(extra_raw, "extra")
    return {str(k): str(v) for k, v in extra_raw.items()}


def fact_pack_from_record(raw: Any) -> DocumentFactPack:
    raw = _require_dict(raw, "record")

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
        seller_contact=_optional_str(raw, "seller_contact"),
        seller_phone=_optional_str(raw, "seller_phone"),
        seller_address=_optional_str(raw, "seller_address"),
        gross_total=_optional_decimal(raw, "gross_total"),
        extra=_extra(raw),
    )
