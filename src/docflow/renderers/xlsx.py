"""XLSX renderer: fills a copy of a real template from a DocumentProjection.

The renderer performs no business calculation. It only:
  - substitutes header text placeholders (document-identity cells),
  - substitutes body-text placeholders (mostly-static clauses that embed
    a transaction fact, e.g. a delivery-deadline sentence naming the
    actual delivery date),
  - writes already-derived item values into fixed template rows,
  - clears leftover sample rows when fewer items than template capacity,
  - fails explicitly when items exceed template capacity.

A template cell must never be left holding a *previous* business
transaction's value: if a cell's content depends on this transaction's
facts at all - even a single date embedded inside an otherwise-static
paragraph - it must be listed in the mapping's `header` or `text` section
so this renderer overwrites it. "Static template boilerplate we don't
touch" only covers cells whose content is genuinely transaction
-independent (legal clause headings, fixed disclaimer wording, etc).

Every written amount is a value already decided upstream (rules.money) -
this renderer never writes a per-row formula that could recompute a
*different* number than the source fact. A real template's own native,
fixed-range aggregate formulas (e.g. contract row 27's
``=SUM(G9:G26)``, delivery's ``D25 = SUM(G7:G24)``) are left untouched;
`fullCalcOnLoad` is set so Excel recalculates them the moment the
generated file is opened.
"""
from __future__ import annotations

from pathlib import Path

import openpyxl
from openpyxl.utils.cell import coordinate_to_tuple
from openpyxl.workbook.properties import CalcProperties

from docflow.domain.document import DocumentProjection, chinese_date, chinese_month_day
from docflow.rules.money import LineItemAmounts
from docflow.templates.definition import TemplateDefinition

TEMPLATE_ITEM_CAPACITY_EXCEEDED = "TEMPLATE_ITEM_CAPACITY_EXCEEDED"

# Single source of truth for the placeholder names available to BOTH
# `header` and `text` mapping cells - shared between the actual renderer
# (_cell_text_context) and preflight (which must reject a mapping
# referencing an unknown placeholder *before* any record is processed,
# rather than let it surface as a KeyError mid-batch).
_CELL_TEXT_CONTEXT_KEYS = (
    "buyer", "seller", "contract_no", "delivery_no", "contract_date", "delivery_date",
    "delivery_month_day", "amount_in_words", "ship_to_company", "ship_to_contact",
    "ship_to_phone", "ship_to_address", "seller_contact", "seller_phone", "seller_address",
)

# Field names a mapping's items.columns may legally reference: every
# LineItemAmounts attribute, plus the two renderer-synthesized ones.
_VALID_ITEM_FIELDS = frozenset(
    {"index", "remarks", "sku", "product_name", "specification", "quantity",
     "unit", "gross_unit_price", "net_unit_price", "net_amount", "tax_amount", "gross_amount"}
)


class TemplateRenderError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


class TemplatePreflightError(Exception):
    """A whole-batch-blocking error: the template file or mapping itself is
    unusable. This is distinct from a per-record TemplateRenderError - it
    means no record in the batch could possibly succeed, so batch
    processing must not even start the record loop.
    """

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


def _is_non_writable_merged_cell(ws, cell_address: str) -> bool:
    """True if writing to this address would hit an openpyxl MergedCell -
    i.e. the address falls inside a merged range but is not that range's
    top-left anchor cell (the only cell in a merge that's actually
    writable).
    """
    row, col = coordinate_to_tuple(cell_address)
    for merged_range in ws.merged_cells.ranges:
        if merged_range.min_row <= row <= merged_range.max_row and merged_range.min_col <= col <= merged_range.max_col:
            if (row, col) != (merged_range.min_row, merged_range.min_col):
                return True
    return False


def _preflight_cell_text_mapping(ws, mapping: dict[str, str], section_name: str, dummy_context: dict[str, str]) -> None:
    """Shared preflight check for both `header` and `text`: every
    placeholder must be satisfiable and every target cell must be
    writable. Used identically for both sections so a mapping author gets
    the same guarantees regardless of which one a cell lives in.
    """
    for cell_address, template_str in mapping.items():
        try:
            template_str.format(**dummy_context)
        except (KeyError, IndexError, ValueError) as exc:
            raise TemplatePreflightError(
                "TEMPLATE_MAPPING_INVALID",
                f"{section_name} template for {cell_address} is invalid: {exc}",
            ) from exc
        if _is_non_writable_merged_cell(ws, cell_address):
            raise TemplatePreflightError(
                "TEMPLATE_MAPPING_INVALID",
                f"{section_name} cell {cell_address} is inside a merged range but is not its "
                f"top-left cell, so it cannot be written to",
            )


def preflight(definition: TemplateDefinition, template_path: Path) -> None:
    """Verify a template file AND mapping are usable before any record is
    processed. This must catch everything render() could later choke on
    for reasons independent of any specific record's data - an unusable
    template must fail the whole batch up front, not surface mid-loop
    after some records already produced output.

    Deliberately catches broad exceptions from openpyxl when opening the
    file: a corrupt/invalid xlsx can surface as any of several unrelated
    exception types (bad zip, bad XML, missing parts). This is a
    file-usability gate, not a place where hiding a docflow programmer
    error would be a concern.
    """
    if not template_path.exists():
        raise TemplatePreflightError("TEMPLATE_FILE_MISSING", f"template file not found: {template_path}")

    try:
        # Not read_only: merged-cell writability (below) needs
        # ws.merged_cells.ranges, which read_only worksheets don't expose.
        wb = openpyxl.load_workbook(template_path)
    except Exception as exc:
        raise TemplatePreflightError(
            "TEMPLATE_FILE_INVALID", f"cannot open {template_path} as an xlsx workbook: {exc}"
        ) from exc

    if definition.sheet not in wb.sheetnames:
        raise TemplatePreflightError(
            "TEMPLATE_SHEET_MISSING",
            f"sheet {definition.sheet!r} not found in {template_path} (available: {wb.sheetnames})",
        )
    ws = wb[definition.sheet]

    dummy_context = {key: "" for key in _CELL_TEXT_CONTEXT_KEYS}
    _preflight_cell_text_mapping(ws, definition.header, "header", dummy_context)
    _preflight_cell_text_mapping(ws, definition.text, "text", dummy_context)

    unknown_fields = set(definition.items.columns) - _VALID_ITEM_FIELDS
    if unknown_fields:
        raise TemplatePreflightError(
            "TEMPLATE_MAPPING_INVALID",
            f"items.columns references unknown field(s): {sorted(unknown_fields)}",
        )

    for row in range(definition.items.start_row, definition.items.end_row + 1):
        for column_letter in definition.items.columns.values():
            cell_address = f"{column_letter}{row}"
            if _is_non_writable_merged_cell(ws, cell_address):
                raise TemplatePreflightError(
                    "TEMPLATE_MAPPING_INVALID",
                    f"item cell {cell_address} is inside a merged range but is not its "
                    f"top-left cell, so it cannot be written to",
                )


def _cell_text_context(projection: DocumentProjection) -> dict[str, str]:
    return {
        "buyer": projection.buyer,
        "seller": projection.seller,
        "contract_no": projection.contract_no,
        "delivery_no": projection.delivery_no,
        "contract_date": chinese_date(projection.contract_date),
        "delivery_date": chinese_date(projection.delivery_date),
        "delivery_month_day": chinese_month_day(projection.delivery_date),
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

    context = _cell_text_context(projection)
    for cell_address, template_str in definition.header.items():
        ws[cell_address] = template_str.format(**context)
    for cell_address, template_str in definition.text.items():
        ws[cell_address] = template_str.format(**context)

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
