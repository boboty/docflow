"""Template mapping definitions.

A TemplateDefinition is pure configuration: cell coordinates and column
letters. It carries no business logic and no document facts. Template
mapping is hand-authored per template (see templates/mappings/*.yaml) -
there is no visual template designer and none is planned.

Three mapping sections, all projection-only:

  - `header`: document-identity fields (buyer, seller, contract_no, ...) -
    a cell's entire text is one formatted placeholder value.
  - `text`: body cells that are *mostly* static boilerplate but embed a
    transaction fact inline (e.g. a delivery-deadline clause naming the
    actual delivery date). Same shape and validation as `header` - a
    dedicated section instead of overloading `header` because these cells
    are conceptually contract prose, not document metadata. A cell must
    never be left holding a template's leftover value from a previous
    business transaction; if a cell's content depends on this
    transaction's facts at all, it belongs in `header` or `text`, not in
    the "static boilerplate we don't touch" bucket.
  - `items`: the line-item table (start_row/end_row + per-field columns).
  - `totals`: optional ``{cell_address: field_name}`` numeric overrides for
    a document-level aggregate (net_total/tax_total/gross_total) that the
    real template holds as a plain literal number rather than a formula
    that recalculates on its own (e.g. a "合计金额" cell with no native
    SUM). The renderer writes the already-computed Totals field directly -
    this exists so a template with no self-updating total cell still never
    keeps a previous transaction's number, without asking an agent to do
    the arithmetic.
  - `images`: optional managed image placements. Size is declared as
    `printed_diameter_mm` - the image's target physical size on the PRINTED
    page, not its size inside the Excel workbook. Because a real template is
    printed at `print.scale_percent` (see below), the renderer inflates this
    by `1 / (scale_percent / 100)` to get the workbook-embedded size, so the
    printed output still comes out at the declared diameter. It describes
    layout only; image bytes are supplied separately by the generation
    orchestrator.
  - `print`: the template's fixed A4 print profile (paper size, orientation,
    print area, scale). This is authored once per template and calibrated
    against a real printout - it replaces ad hoc manual "fit to page"
    scaling, which is what silently shrinks mapped seal sizes on paper in
    the first place (a `width_mm` declared against the workbook means
    nothing once the sheet itself gets scaled down to fit a page).

Every parsing failure here (bad YAML, wrong types, illegal row numbers,
malformed cell/column references) is normalized to TemplateDefinitionError
so callers - specifically renderers.xlsx.preflight - can treat "this
mapping is unusable" as one predictable exception type instead of an
assortment of yaml.YAMLError / TypeError / ValueError leaking out.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

import yaml
from openpyxl.utils import column_index_from_string
from openpyxl.utils.cell import coordinate_from_string

from docflow.domain.document import DocumentType

_CELL_ADDRESS_RE = re.compile(r"^[A-Z]+[1-9][0-9]*$")
_COLUMN_LETTER_RE = re.compile(r"^[A-Z]+$")

# Excel's own hard limits (xlsx format, not any particular file) - a
# mapping referencing a row/column beyond these can never be valid,
# regardless of which template it is later paired with.
MAX_EXCEL_ROW = 1_048_576
MAX_EXCEL_COLUMN = 16_384  # column "XFD"


class TemplateDefinitionError(Exception):
    pass


@dataclass(frozen=True, slots=True)
class ItemsMapping:
    start_row: int
    end_row: int
    columns: dict[str, str]

    @property
    def capacity(self) -> int:
        return self.end_row - self.start_row + 1


@dataclass(frozen=True, slots=True)
class ImageMapping:
    anchor: str
    printed_diameter_mm: float
    x_offset_px: int = 0
    y_offset_px: int = 0


@dataclass(frozen=True, slots=True)
class PrintProfile:
    """A template's fixed A4 print profile. `scale_percent` is a calibrated
    business value, not a guess - it must be set by printing the real
    template and measuring the result, then hand-tuned until printed output
    matches (see `docflow.renderers.xlsx` for how it also drives printed
    image sizing). There is deliberately no dynamic fitToWidth/fitToHeight
    here: that's exactly the "user picks a reasonable-looking zoom" behavior
    this profile exists to replace.
    """

    paper_size: str
    orientation: str
    print_area: str
    scale_percent: int


@dataclass(frozen=True, slots=True)
class TemplateDefinition:
    id: str
    format: str
    sheet: str
    header: dict[str, str]
    text: dict[str, str]
    items: ItemsMapping
    images: dict[str, ImageMapping]
    print_profile: PrintProfile
    totals: dict[str, str] = field(default_factory=dict)


def _validate_column_letter(column: str, path: Path, what: str) -> None:
    if not _COLUMN_LETTER_RE.match(column):
        raise TemplateDefinitionError(f"malformed template mapping {path}: invalid column {column!r} for {what}")
    if column_index_from_string(column) > MAX_EXCEL_COLUMN:
        raise TemplateDefinitionError(
            f"malformed template mapping {path}: column {column!r} for {what} exceeds Excel's column limit (XFD)"
        )


def _require_str(raw: dict, key: str, path: Path) -> str:
    if key not in raw:
        raise TemplateDefinitionError(f"malformed template mapping {path}: missing '{key}'")
    value = raw[key]
    if not isinstance(value, str) or not value:
        raise TemplateDefinitionError(f"malformed template mapping {path}: '{key}' must be a non-empty string")
    return value


def _parse_items(items_raw: object, path: Path) -> ItemsMapping:
    if not isinstance(items_raw, dict):
        raise TemplateDefinitionError(f"malformed template mapping {path}: 'items' must be a mapping")

    if "start_row" not in items_raw or "end_row" not in items_raw:
        raise TemplateDefinitionError(f"malformed template mapping {path}: missing 'items.start_row'/'end_row'")
    try:
        start_row = int(items_raw["start_row"])
        end_row = int(items_raw["end_row"])
    except (TypeError, ValueError) as exc:
        raise TemplateDefinitionError(
            f"malformed template mapping {path}: 'items.start_row'/'end_row' must be integers"
        ) from exc
    if start_row < 1 or end_row < start_row or end_row > MAX_EXCEL_ROW:
        raise TemplateDefinitionError(
            f"malformed template mapping {path}: invalid item row range "
            f"start_row={start_row}, end_row={end_row} (Excel allows rows 1-{MAX_EXCEL_ROW})"
        )

    columns_raw = items_raw.get("columns")
    if not isinstance(columns_raw, dict) or not columns_raw:
        raise TemplateDefinitionError(f"malformed template mapping {path}: 'items.columns' must be a non-empty mapping")

    columns: dict[str, str] = {}
    for field_name, column in columns_raw.items():
        if not isinstance(field_name, str) or not isinstance(column, str):
            raise TemplateDefinitionError(
                f"malformed template mapping {path}: invalid column {column!r} for field {field_name!r}"
            )
        _validate_column_letter(column, path, f"field {field_name!r}")
        columns[field_name] = column

    return ItemsMapping(start_row=start_row, end_row=end_row, columns=columns)


def _parse_cell_text_mapping(section_raw: object, section_name: str, path: Path) -> dict[str, str]:
    """Shared parser for both `header` and `text`: both are just
    ``{cell_address: format_string}`` - one section for document-identity
    fields, one for body-text cells that embed a transaction fact inside
    otherwise-static prose (see `text` in the module docstring). Sharing
    this parser (and, in renderers.xlsx, the same preflight/render helpers)
    means a mapping author gets identical validation and identical
    placeholder semantics in both places, with no separate implementation
    to keep in sync.
    """
    if section_raw is None:
        return {}
    if not isinstance(section_raw, dict):
        raise TemplateDefinitionError(f"malformed template mapping {path}: '{section_name}' must be a mapping")

    result: dict[str, str] = {}
    for cell_address, template_str in section_raw.items():
        if not isinstance(cell_address, str) or not _CELL_ADDRESS_RE.match(cell_address):
            raise TemplateDefinitionError(
                f"malformed template mapping {path}: invalid {section_name} cell {cell_address!r}"
            )
        column_letters, row = coordinate_from_string(cell_address)
        if row > MAX_EXCEL_ROW or column_index_from_string(column_letters) > MAX_EXCEL_COLUMN:
            raise TemplateDefinitionError(
                f"malformed template mapping {path}: {section_name} cell {cell_address!r} is outside Excel's grid"
            )
        if not isinstance(template_str, str):
            raise TemplateDefinitionError(
                f"malformed template mapping {path}: {section_name} value for {cell_address} must be a string"
            )
        result[cell_address] = template_str
    return result


def _parse_images(images_raw: object, path: Path) -> dict[str, ImageMapping]:
    if images_raw is None:
        return {}
    if not isinstance(images_raw, dict):
        raise TemplateDefinitionError(f"malformed template mapping {path}: 'images' must be a mapping")

    result: dict[str, ImageMapping] = {}
    for image_id, raw in images_raw.items():
        where = f"images.{image_id}"
        if not isinstance(image_id, str) or not image_id or not isinstance(raw, dict):
            raise TemplateDefinitionError(f"malformed template mapping {path}: {where} must be a mapping")
        anchor = raw.get("anchor")
        if not isinstance(anchor, str) or not _CELL_ADDRESS_RE.match(anchor):
            raise TemplateDefinitionError(f"malformed template mapping {path}: invalid {where}.anchor {anchor!r}")
        column_letters, row = coordinate_from_string(anchor)
        if row > MAX_EXCEL_ROW or column_index_from_string(column_letters) > MAX_EXCEL_COLUMN:
            raise TemplateDefinitionError(f"malformed template mapping {path}: {where}.anchor is outside Excel's grid")
        try:
            printed_diameter_mm = float(raw["printed_diameter_mm"])
            x_offset_px = int(raw.get("x_offset_px", 0))
            y_offset_px = int(raw.get("y_offset_px", 0))
        except (KeyError, TypeError, ValueError) as exc:
            raise TemplateDefinitionError(
                f"malformed template mapping {path}: {where} requires a numeric printed_diameter_mm "
                f"and integer offsets"
            ) from exc
        if printed_diameter_mm <= 0 or x_offset_px < 0 or y_offset_px < 0:
            raise TemplateDefinitionError(
                f"malformed template mapping {path}: {where} dimensions must be positive and offsets non-negative"
            )
        result[image_id] = ImageMapping(anchor, printed_diameter_mm, x_offset_px, y_offset_px)
    return result


_VALID_TOTAL_FIELDS = frozenset({"net_total", "tax_total", "gross_total"})


def _parse_totals(totals_raw: object, path: Path) -> dict[str, str]:
    if totals_raw is None:
        return {}
    if not isinstance(totals_raw, dict):
        raise TemplateDefinitionError(f"malformed template mapping {path}: 'totals' must be a mapping")

    result: dict[str, str] = {}
    for cell_address, field_name in totals_raw.items():
        if not isinstance(cell_address, str) or not _CELL_ADDRESS_RE.match(cell_address):
            raise TemplateDefinitionError(f"malformed template mapping {path}: invalid totals cell {cell_address!r}")
        column_letters, row = coordinate_from_string(cell_address)
        if row > MAX_EXCEL_ROW or column_index_from_string(column_letters) > MAX_EXCEL_COLUMN:
            raise TemplateDefinitionError(
                f"malformed template mapping {path}: totals cell {cell_address!r} is outside Excel's grid"
            )
        if field_name not in _VALID_TOTAL_FIELDS:
            raise TemplateDefinitionError(
                f"malformed template mapping {path}: totals.{cell_address} references unknown field "
                f"{field_name!r} (expected one of {sorted(_VALID_TOTAL_FIELDS)})"
            )
        result[cell_address] = field_name
    return result


# Only A4/portrait are supported today - deliberately not a general
# printer-settings framework (there is exactly one real-world shape this
# project's templates need). Extend these sets only when an actual template
# needs it.
_SUPPORTED_PAPER_SIZES = {"A4"}
_SUPPORTED_ORIENTATIONS = {"portrait", "landscape"}
_MIN_SCALE_PERCENT = 10
_MAX_SCALE_PERCENT = 400


def _parse_print_profile(print_raw: object, path: Path) -> PrintProfile:
    if not isinstance(print_raw, dict):
        raise TemplateDefinitionError(f"malformed template mapping {path}: missing or invalid 'print' section")

    paper_size = print_raw.get("paper_size")
    if paper_size not in _SUPPORTED_PAPER_SIZES:
        raise TemplateDefinitionError(
            f"malformed template mapping {path}: print.paper_size must be one of {sorted(_SUPPORTED_PAPER_SIZES)}"
        )
    orientation = print_raw.get("orientation")
    if orientation not in _SUPPORTED_ORIENTATIONS:
        raise TemplateDefinitionError(
            f"malformed template mapping {path}: print.orientation must be one of {sorted(_SUPPORTED_ORIENTATIONS)}"
        )
    print_area = print_raw.get("print_area")
    if not isinstance(print_area, str) or not print_area:
        raise TemplateDefinitionError(f"malformed template mapping {path}: print.print_area must be a non-empty string")
    try:
        scale_percent = round(float(print_raw["scale_percent"]))
    except (KeyError, TypeError, ValueError) as exc:
        raise TemplateDefinitionError(
            f"malformed template mapping {path}: print.scale_percent must be numeric"
        ) from exc
    if not (_MIN_SCALE_PERCENT <= scale_percent <= _MAX_SCALE_PERCENT):
        raise TemplateDefinitionError(
            f"malformed template mapping {path}: print.scale_percent must be between "
            f"{_MIN_SCALE_PERCENT} and {_MAX_SCALE_PERCENT}"
        )

    return PrintProfile(paper_size=paper_size, orientation=orientation, print_area=print_area, scale_percent=scale_percent)


def load_template_definition(path: Path) -> TemplateDefinition:
    try:
        with path.open("r", encoding="utf-8") as f:
            raw = yaml.safe_load(f)
    except yaml.YAMLError as exc:
        raise TemplateDefinitionError(f"invalid YAML in template mapping {path}: {exc}") from exc
    except OSError as exc:
        raise TemplateDefinitionError(f"cannot read template mapping {path}: {exc}") from exc

    if not isinstance(raw, dict):
        raise TemplateDefinitionError(f"malformed template mapping {path}: document must be a mapping")

    if "items" not in raw:
        raise TemplateDefinitionError(f"malformed template mapping {path}: missing 'items'")
    if "print" not in raw:
        raise TemplateDefinitionError(f"malformed template mapping {path}: missing 'print'")

    return TemplateDefinition(
        id=_require_str(raw, "id", path),
        format=_require_str(raw, "format", path),
        sheet=_require_str(raw, "sheet", path),
        header=_parse_cell_text_mapping(raw.get("header"), "header", path),
        text=_parse_cell_text_mapping(raw.get("text"), "text", path),
        items=_parse_items(raw["items"], path),
        images=_parse_images(raw.get("images"), path),
        print_profile=_parse_print_profile(raw["print"], path),
        totals=_parse_totals(raw.get("totals"), path),
    )


def document_type_from_id(template_id: str) -> DocumentType:
    return DocumentType(template_id)
