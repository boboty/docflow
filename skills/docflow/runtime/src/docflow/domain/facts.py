"""Canonical input contract: DocumentFactPack.

This module defines the structured business facts that feed the engine.
It is an *input contract*, not a system of record: canonical facts contain
no Excel cell coordinates and no derived money values. Derivation lives in
``docflow.rules``; template mapping lives in ``docflow.templates``.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal


@dataclass(frozen=True, slots=True)
class ShipTo:
    company: str
    contact: str
    phone: str
    address: str


@dataclass(frozen=True, slots=True)
class LineItemFacts:
    """Gross-pricing input facts (Phase 0 Repair).

    ``gross_amount`` is the authoritative business fact (what the real
    contract/delivery-note pair actually settle on) - it is NOT derived from
    ``gross_unit_price * quantity``. ``gross_unit_price`` is a separate,
    independently supplied fact (the display unit price printed on the real
    delivery note); the two are expected to agree, and that agreement is a
    *validation* concern (see ``domain.validation.validate_source_consistency``),
    never a derivation shortcut. ``net_unit_price`` is not an input fact at
    all - it is a display value derived downstream in ``rules.money``.
    """

    sku: str
    product_name: str
    specification: str
    quantity: Decimal
    unit: str
    gross_unit_price: Decimal
    gross_amount: Decimal
    tax_rate: Decimal
    remarks: str | None = None


@dataclass(frozen=True, slots=True)
class DocumentFactPack:
    business_reference: str
    contract_no: str
    delivery_no: str
    contract_date: date
    delivery_date: date
    buyer: str
    seller: str
    ship_to: ShipTo
    items: tuple[LineItemFacts, ...]
    currency: str = "CNY"
    seller_contact: str | None = None
    seller_phone: str | None = None
    seller_address: str | None = None
    # Optional independently-supplied aggregate fact (e.g. from an upstream
    # PO total). When present, validation checks Σ item.gross_amount against
    # it; when absent, aggregate consistency is simply not checked.
    gross_total: Decimal | None = None
    # Escape hatch for document-specific values not yet promoted to a
    # canonical field. Deliberately untyped and unstructured (YAGNI) -
    # do not build a generic schema around this.
    extra: dict[str, str] = field(default_factory=dict)
