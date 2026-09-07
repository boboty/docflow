"""Centralized, deterministic money and tax derivation rules.

All monetary derivation for documents must go through this module. Renderers
must never compute money values themselves - they only consume already
-derived projection values.

Pricing model (Phase 0 Repair): **gross pricing**. ``gross_amount`` is the
authoritative source fact per line (what the real business documents
settle on); tax-exclusive figures are display values derived FROM it, never
the other way around:

    net_amount     = round(gross_amount / (1 + tax_rate), 2)
    tax_amount     = gross_amount - net_amount
    net_unit_price = round(gross_unit_price / (1 + tax_rate), 2)

Rounding policy: round-half-up to 2 decimal places. ``net_amount`` is
rounded once, directly from the source ``gross_amount``; ``tax_amount`` is
then whatever remains (gross - net), which guarantees
``net_amount + tax_amount == gross_amount`` exactly, with no compounding
rounding error. ``net_unit_price`` is rounded independently the same way,
purely for display - it is never used to derive line totals.

Earlier (pre-repair) revisions of this module treated the tax-exclusive
*unit price* as authoritative and multiplied it forward by quantity. That
does not match real business documents, where the unit price shown is
itself a rounded-for-display figure and the line amount is the true
source fact. See docs/phase-0-repair-task-brief.md.
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal

from docflow.domain.facts import LineItemFacts

CENTS = Decimal("0.01")

# Source-consistency tolerance policy: gross_unit_price is assumed to be a
# value rounded to 2dp from gross_amount / quantity, so the worst-case gap
# between gross_unit_price * quantity and the true gross_amount is half a
# rounding unit per unit of quantity (0.005 * quantity), floored at one
# cent to allow for a single-unit line. See domain.validation.
CONSISTENCY_TOLERANCE_PER_UNIT = Decimal("0.005")
MIN_CONSISTENCY_TOLERANCE = Decimal("0.01")


def round_money(value: Decimal) -> Decimal:
    return value.quantize(CENTS, rounding=ROUND_HALF_UP)


def source_consistency_tolerance(quantity: Decimal) -> Decimal:
    return max(MIN_CONSISTENCY_TOLERANCE, round_money(quantity * CONSISTENCY_TOLERANCE_PER_UNIT))


@dataclass(frozen=True, slots=True)
class LineItemAmounts:
    sku: str
    product_name: str
    specification: str
    quantity: Decimal
    unit: str
    gross_unit_price: Decimal
    net_unit_price: Decimal
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
    gross_amount = round_money(item.gross_amount)
    net_amount = round_money(gross_amount / (1 + item.tax_rate))
    tax_amount = gross_amount - net_amount
    net_unit_price = round_money(item.gross_unit_price / (1 + item.tax_rate))
    return LineItemAmounts(
        sku=item.sku,
        product_name=item.product_name,
        specification=item.specification,
        quantity=item.quantity,
        unit=item.unit,
        gross_unit_price=round_money(item.gross_unit_price),
        net_unit_price=net_unit_price,
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
