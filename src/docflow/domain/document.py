"""Document-level projection: the derived, template-ready view of a FactPack.

A DocumentProjection carries only already-decided values (money, dates,
formatted text). Renderers must not perform business calculation; they only
place these values onto template cells.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from enum import Enum

from docflow.domain.facts import DocumentFactPack, ShipTo
from docflow.rules.chinese_amount import to_rmb_capital
from docflow.rules.money import LineItemAmounts, Totals, compute_line_item_amounts, compute_totals


class DocumentType(str, Enum):
    PROCUREMENT_CONTRACT_V1 = "procurement.contract.v1"
    DELIVERY_NOTE_V1 = "delivery.note.v1"


def chinese_date(d: date) -> str:
    return f"{d.year}年{d.month}月{d.day}日"


def chinese_month_day(d: date) -> str:
    """Month/day only, no year - e.g. 2026-09-09 -> "9月9日".

    Pure display formatting of an existing transaction fact (a date
    already on the FactPack), not a new fact. Used for body-text template
    cells that reference "the delivery date" without repeating the year
    (matching the real contract's own clause wording).
    """
    return f"{d.month}月{d.day}日"


@dataclass(frozen=True, slots=True)
class DocumentProjection:
    document_type: DocumentType
    business_reference: str
    contract_no: str
    delivery_no: str
    contract_date: date
    delivery_date: date
    buyer: str
    seller: str
    ship_to: ShipTo
    currency: str
    items: tuple[LineItemAmounts, ...]
    totals: Totals
    amount_in_words: str
    seller_contact: str | None = None
    seller_phone: str | None = None
    seller_address: str | None = None

    @property
    def item_identity_sequence(self) -> tuple[tuple[str, Decimal], ...]:
        """(sku, quantity) pairs in order - the invariant checked cross-document."""
        return tuple((i.sku, i.quantity) for i in self.items)


def build_projection(fact_pack: DocumentFactPack, document_type: DocumentType) -> DocumentProjection:
    item_amounts = [compute_line_item_amounts(item) for item in fact_pack.items]
    totals = compute_totals(item_amounts)
    return DocumentProjection(
        document_type=document_type,
        business_reference=fact_pack.business_reference,
        contract_no=fact_pack.contract_no,
        delivery_no=fact_pack.delivery_no,
        contract_date=fact_pack.contract_date,
        delivery_date=fact_pack.delivery_date,
        buyer=fact_pack.buyer,
        seller=fact_pack.seller,
        ship_to=fact_pack.ship_to,
        currency=fact_pack.currency,
        items=tuple(item_amounts),
        totals=totals,
        amount_in_words=to_rmb_capital(totals.gross_total),
        seller_contact=fact_pack.seller_contact,
        seller_phone=fact_pack.seller_phone,
        seller_address=fact_pack.seller_address,
    )
