"""XLSX renderer: fills a copy of a real template from a DocumentProjection.

The renderer performs no business calculation. It only:
  - substitutes header text placeholders,
  - writes already-derived item values into fixed template rows,
  - clears leftover sample rows when fewer items than template capacity,
  - fails explicitly when items exceed template capacity.

Native Excel subtotal formulas already present in the template (row sums,
`=Dn*Fn` per-row amounts) are left untouched; `fullCalcOnLoad` is set so
Excel recalculates them the moment the generated file is opened.
"""
from __future__ import annotations

from pathlib import Path

import openpyxl
from openpyxl.workbook.properties import CalcProperties

from docflow.domain.document import DocumentProjection, chinese_date
from docflow.rules.money import LineItemAmounts
from docflow.templates.definition import TemplateDefinition

TEMPLATE_ITEM_CAPACITY_EXCEEDED = "TEMPLATE_ITEM_CAPACITY_EXCEEDED"


class TemplateRenderError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


def _header_context(projection: DocumentProjection) -> dict[str, str]:
    return {
        "buyer": projection.buyer,
        "seller": projection.seller,
        "contract_no": projection.contract_no,
        "delivery_no": projection.delivery_no,
        "contract_date": chinese_date(projection.contract_date),
        "delivery_date": chinese_date(projection.delivery_date),
        "amount_in_words": projection.amount_in_words,
        "ship_to_company": projection.ship_to.company,
        "ship_to_contact": projection.ship_to.contact,
        "ship_to_phone": projection.ship_to.phone,
        "ship_to_address": projection.ship_to.address,
        "seller_contact": projection.seller_contact or "",
        "seller_phone": projection.seller_phone or "",
        "seller_address": projection.seller_address or "",
    }


_NUMERIC_ITEM_FIELDS = {
    "quantity",
    "net_unit_price",
    "gross_unit_price",
    "net_amount",
    "tax_amount",
    "gross_amount",
}


def _item_cell_value(item: LineItemAmounts, index: int, field_name: str):
    if field_name == "index":
        return index
    if field_name == "remarks":
        return item.remarks or ""
    value = getattr(item, field_name)
    if field_name in _NUMERIC_ITEM_FIELDS:
        return float(value)
    return value


def render(
    definition: TemplateDefinition,
    source_template_path: Path,
    projection: DocumentProjection,
    output_path: Path,
) -> None:
    capacity = definition.items.capacity
    if len(projection.items) > capacity:
        raise TemplateRenderError(
            TEMPLATE_ITEM_CAPACITY_EXCEEDED,
            f"{len(projection.items)} line items exceed template capacity {capacity} "
            f"for {definition.id}",
        )

    wb = openpyxl.load_workbook(source_template_path)
    ws = wb[definition.sheet]

    header_context = _header_context(projection)
    for cell_address, template_str in definition.header.items():
        ws[cell_address] = template_str.format(**header_context)

    columns = definition.items.columns
    start_row = definition.items.start_row
    for offset, item in enumerate(projection.items):
        row = start_row + offset
        for field_name, column_letter in columns.items():
            ws[f"{column_letter}{row}"] = _item_cell_value(item, offset + 1, field_name)

    for row in range(start_row + len(projection.items), definition.items.end_row + 1):
        for column_letter in columns.values():
            ws[f"{column_letter}{row}"] = None

    if wb.calculation is None:
        wb.calculation = CalcProperties(fullCalcOnLoad=True)
    else:
        wb.calculation.fullCalcOnLoad = True

    output_path.parent.mkdir(parents=True, exist_ok=True)
    wb.save(output_path)
