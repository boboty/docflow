"""Centralized, deterministic money and tax derivation rules.

All monetary derivation for documents must go through this module. Renderers
must never compute money values themselves - they only consume already
-derived projection values.

Rounding policy: round-half-up to 2 decimal places, applied at the point
each derived value is produced (net_amount, tax_amount, then gross_amount
as their sum, then gross_unit_price from gross_amount). This mirrors how
the real paper contract/delivery-note pair round line by line rather than
rounding a grand total in one step.
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal

from docflow.domain.facts import LineItemFacts

CENTS = Decimal("0.01")


def round_money(value: Decimal) -> Decimal:
    return value.quantize(CENTS, rounding=ROUND_HALF_UP)


@dataclass(frozen=True, slots=True)
class LineItemAmounts:
    sku: str
    product_name: str
    specification: str
    quantity: Decimal
    unit: str
    net_unit_price: Decimal
    gross_unit_price: Decimal
    net_amount: Decimal
    tax_amount: Decimal
    gross_amount: Decimal
    remarks: str | None = None


@dataclass(frozen=True, slots=True)
class Totals:
    net_total: Decimal
    tax_total: Decimal
    gross_total: Decimal


def compute_line_item_amounts(item: LineItemFacts) -> LineItemAmounts:
    net_amount = round_money(item.net_unit_price * item.quantity)
    tax_amount = round_money(net_amount * item.tax_rate)
    gross_amount = net_amount + tax_amount
    gross_unit_price = round_money(gross_amount / item.quantity)
    return LineItemAmounts(
        sku=item.sku,
        product_name=item.product_name,
        specification=item.specification,
        quantity=item.quantity,
        unit=item.unit,
        net_unit_price=round_money(item.net_unit_price),
        gross_unit_price=gross_unit_price,
        net_amount=net_amount,
        tax_amount=tax_amount,
        gross_amount=gross_amount,
        remarks=item.remarks,
    )


def compute_totals(items: list[LineItemAmounts]) -> Totals:
    net_total = round_money(sum((i.net_amount for i in items), Decimal("0")))
    tax_total = round_money(sum((i.tax_amount for i in items), Decimal("0")))
    gross_total = round_money(sum((i.gross_amount for i in items), Decimal("0")))
    return Totals(net_total=net_total, tax_total=tax_total, gross_total=gross_total)
