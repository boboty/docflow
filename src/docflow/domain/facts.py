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
    sku: str
    product_name: str
    specification: str
    quantity: Decimal
    unit: str
    net_unit_price: Decimal
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
    # Escape hatch for document-specific values not yet promoted to a
    # canonical field. Deliberately untyped and unstructured (YAGNI) -
    # do not build a generic schema around this.
    extra: dict[str, str] = field(default_factory=dict)
