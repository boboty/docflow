import json
from dataclasses import replace
from pathlib import Path

import pytest
import yaml

from docflow.application.generation import generate_batch
from docflow.domain.document import DocumentType
from docflow.renderers.xlsx import TemplatePreflightError, preflight
from docflow.templates.definition import TemplateDefinitionError, load_template_definition
from docflow.templates.registry import TemplateRegistry


def test_preflight_missing_template_file(tmp_path: Path):
    definition = TemplateRegistry().get(DocumentType.PROCUREMENT_CONTRACT_V1)
    with pytest.raises(TemplatePreflightError) as exc_info:
        preflight(definition, tmp_path / "does-not-exist.xlsx")
    assert exc_info.value.code == "TEMPLATE_FILE_MISSING"


def test_preflight_invalid_xlsx_file(tmp_path: Path):
    bad_file = tmp_path / "not-really-xlsx.xlsx"
    bad_file.write_text("this is not a zip/xlsx file at all", encoding="utf-8")

    definition = TemplateRegistry().get(DocumentType.PROCUREMENT_CONTRACT_V1)
    with pytest.raises(TemplatePreflightError) as exc_info:
        preflight(definition, bad_file)
    assert exc_info.value.code == "TEMPLATE_FILE_INVALID"


def test_preflight_missing_sheet(contract_template_path: Path):
    definition = TemplateRegistry().get(DocumentType.PROCUREMENT_CONTRACT_V1)
    wrong_sheet_definition = replace(definition, sheet="NoSuchSheet")

    with pytest.raises(TemplatePreflightError) as exc_info:
        preflight(wrong_sheet_definition, contract_template_path)
    assert exc_info.value.code == "TEMPLATE_SHEET_MISSING"


def test_preflight_rejects_unknown_header_placeholder(contract_template_path: Path):
    definition = TemplateRegistry().get(DocumentType.PROCUREMENT_CONTRACT_V1)
    bad_header = dict(definition.header)
    bad_header["C3"] = "购方：{unknown_fact}"
    broken_definition = replace(definition, header=bad_header)

    with pytest.raises(TemplatePreflightError) as exc_info:
        preflight(broken_definition, contract_template_path)
    assert exc_info.value.code == "TEMPLATE_MAPPING_INVALID"


def test_preflight_rejects_unknown_item_column_field(contract_template_path: Path):
    from docflow.templates.definition import ItemsMapping

    definition = TemplateRegistry().get(DocumentType.PROCUREMENT_CONTRACT_V1)
    bad_items = ItemsMapping(
        start_row=definition.items.start_row,
        end_row=definition.items.end_row,
        columns={**definition.items.columns, "totally_unknown_field": "A"},
    )
    broken_definition = replace(definition, items=bad_items)

    with pytest.raises(TemplatePreflightError) as exc_info:
        preflight(broken_definition, contract_template_path)
    assert exc_info.value.code == "TEMPLATE_MAPPING_INVALID"


def test_preflight_rejects_header_cell_inside_non_anchor_merged_range(contract_template_path: Path):
    """D3 sits inside the real template's C3:H3 merge (购方 line) but is not
    its top-left anchor - openpyxl raises AttributeError writing to it
    ('MergedCell ... is read-only'). preflight must catch this before any
    record is rendered, not let it surface as an AttributeError mid-batch.
    """
    definition = TemplateRegistry().get(DocumentType.PROCUREMENT_CONTRACT_V1)
    bad_header = dict(definition.header)
    bad_header["D3"] = "{buyer}"
    broken_definition = replace(definition, header=bad_header)

    with pytest.raises(TemplatePreflightError) as exc_info:
        preflight(broken_definition, contract_template_path)
    assert exc_info.value.code == "TEMPLATE_MAPPING_INVALID"


def test_preflight_rejects_malformed_format_string(contract_template_path: Path):
    definition = TemplateRegistry().get(DocumentType.PROCUREMENT_CONTRACT_V1)
    bad_header = dict(definition.header)
    bad_header["C3"] = "购方：{buyer"  # unmatched brace -> str.format raises ValueError
    broken_definition = replace(definition, header=bad_header)

    with pytest.raises(TemplatePreflightError) as exc_info:
        preflight(broken_definition, contract_template_path)
    assert exc_info.value.code == "TEMPLATE_MAPPING_INVALID"


def test_preflight_rejects_unknown_text_placeholder(contract_template_path: Path):
    definition = TemplateRegistry().get(DocumentType.PROCUREMENT_CONTRACT_V1)
    bad_text = dict(definition.text)
    bad_text["C29"] = "{unknown_fact}前发货"
    broken_definition = replace(definition, text=bad_text)

    with pytest.raises(TemplatePreflightError) as exc_info:
        preflight(broken_definition, contract_template_path)
    assert exc_info.value.code == "TEMPLATE_MAPPING_INVALID"


def test_preflight_rejects_text_cell_inside_non_anchor_merged_range(contract_template_path: Path):
    """D29 sits inside the synthetic/real template's C29:K29 merge but is
    not its top-left anchor.
    """
    definition = TemplateRegistry().get(DocumentType.PROCUREMENT_CONTRACT_V1)
    bad_text = dict(definition.text)
    bad_text["D29"] = "{delivery_month_day}前发货"
    broken_definition = replace(definition, text=bad_text)

    with pytest.raises(TemplatePreflightError) as exc_info:
        preflight(broken_definition, contract_template_path)
    assert exc_info.value.code == "TEMPLATE_MAPPING_INVALID"


def test_preflight_rejects_malformed_text_format_string(contract_template_path: Path):
    definition = TemplateRegistry().get(DocumentType.PROCUREMENT_CONTRACT_V1)
    bad_text = dict(definition.text)
    bad_text["C29"] = "{delivery_month_day前发货"  # unmatched brace
    broken_definition = replace(definition, text=bad_text)

    with pytest.raises(TemplatePreflightError) as exc_info:
        preflight(broken_definition, contract_template_path)
    assert exc_info.value.code == "TEMPLATE_MAPPING_INVALID"


def test_load_template_definition_rejects_text_cell_beyond_excel_limit(tmp_path: Path):
    bad_mapping = tmp_path / "bad.yaml"
    bad_mapping.write_text(
        "id: x\nformat: xlsx\nsheet: Sheet1\n"
        "text:\n  A1048577: \"{delivery_month_day}\"\n"
        "items:\n  start_row: 1\n  end_row: 5\n  columns:\n    sku: A\n",
        encoding="utf-8",
    )
    with pytest.raises(TemplateDefinitionError):
        load_template_definition(bad_mapping)


def test_load_template_definition_rejects_invalid_text_cell_address(tmp_path: Path):
    bad_mapping = tmp_path / "bad.yaml"
    bad_mapping.write_text(
        "id: x\nformat: xlsx\nsheet: Sheet1\n"
        "text:\n  \"not-a-cell\": \"{delivery_month_day}\"\n"
        "items:\n  start_row: 1\n  end_row: 5\n  columns:\n    sku: A\n",
        encoding="utf-8",
    )
    with pytest.raises(TemplateDefinitionError):
        load_template_definition(bad_mapping)


def test_load_template_definition_rejects_non_mapping_text_section(tmp_path: Path):
    bad_mapping = tmp_path / "bad.yaml"
    bad_mapping.write_text(
        "id: x\nformat: xlsx\nsheet: Sheet1\n"
        "text: not-a-mapping\n"
        "items:\n  start_row: 1\n  end_row: 5\n  columns:\n    sku: A\n",
        encoding="utf-8",
    )
    with pytest.raises(TemplateDefinitionError):
        load_template_definition(bad_mapping)


def test_load_template_definition_rejects_row_beyond_excel_limit(tmp_path: Path):
    bad_mapping = tmp_path / "bad.yaml"
    bad_mapping.write_text(
        "id: x\nformat: xlsx\nsheet: Sheet1\n"
        "header:\n  A1048577: \"{buyer}\"\n"
        "items:\n  start_row: 1\n  end_row: 5\n  columns:\n    sku: A\n",
        encoding="utf-8",
    )
    with pytest.raises(TemplateDefinitionError):
        load_template_definition(bad_mapping)


def test_load_template_definition_rejects_end_row_beyond_excel_limit(tmp_path: Path):
    bad_mapping = tmp_path / "bad.yaml"
    bad_mapping.write_text(
        "id: x\nformat: xlsx\nsheet: Sheet1\n"
        "items:\n  start_row: 1\n  end_row: 1048577\n  columns:\n    sku: A\n",
        encoding="utf-8",
    )
    with pytest.raises(TemplateDefinitionError):
        load_template_definition(bad_mapping)


def test_generate_batch_does_not_render_anything_when_mapping_is_broken(
    tmp_path, contract_template_path, delivery_template_path
):
    """The exact reported repro: an invalid delivery mapping (unknown
    placeholder) must be caught in preflight, BEFORE the contract for any
    record is rendered - not surface as a KeyError mid-batch after the
    contract already succeeded.
    """
    mapping_dir = tmp_path / "mappings"
    mapping_dir.mkdir()

    good_registry = TemplateRegistry()
    contract_def = good_registry.get(DocumentType.PROCUREMENT_CONTRACT_V1)
    delivery_def = good_registry.get(DocumentType.DELIVERY_NOTE_V1)

    def _print_section(definition):
        profile = definition.print_profile
        return {
            "paper_size": profile.paper_size,
            "orientation": profile.orientation,
            "print_area": profile.print_area,
            "scale_percent": profile.scale_percent,
        }

    (mapping_dir / "procurement.contract.v1.yaml").write_text(
        yaml.safe_dump({
            "id": contract_def.id, "format": contract_def.format, "sheet": contract_def.sheet,
            "header": contract_def.header,
            "print": _print_section(contract_def),
            "items": {
                "start_row": contract_def.items.start_row,
                "end_row": contract_def.items.end_row,
                "columns": contract_def.items.columns,
            },
        }, allow_unicode=True),
        encoding="utf-8",
    )

    broken_header = dict(delivery_def.header)
    broken_header["B3"] = "收货单位：{unknown_fact}"
    (mapping_dir / "delivery.note.v1.yaml").write_text(
        yaml.safe_dump({
            "id": delivery_def.id, "format": delivery_def.format, "sheet": delivery_def.sheet,
            "header": broken_header,
            "print": _print_section(delivery_def),
            "items": {
                "start_row": delivery_def.items.start_row,
                "end_row": delivery_def.items.end_row,
                "columns": delivery_def.items.columns,
            },
        }, allow_unicode=True),
        encoding="utf-8",
    )

    batch_path = tmp_path / "batch.json"
    batch_path.write_text(json.dumps([{
        "business_reference": "BR-1", "contract_no": "CT-1", "delivery_no": "DN-1",
        "contract_date": "2026-05-16", "delivery_date": "2026-06-09",
        "buyer": "b", "seller": "s",
        "ship_to": {"company": "c", "contact": "c", "phone": "p", "address": "a"},
        "items": [{"sku": "S1", "product_name": "p", "specification": "s", "quantity": 1,
                   "unit": "u", "gross_unit_price": "10", "gross_amount": "10", "tax_rate": "0.13"}],
    }]), encoding="utf-8")
    output_dir = tmp_path / "output"

    with pytest.raises(TemplatePreflightError) as exc_info:
        generate_batch(
            batch_path,
            contract_template_path=contract_template_path,
            delivery_template_path=delivery_template_path,
            output_dir=output_dir,
            registry=TemplateRegistry(mapping_dir=mapping_dir),
        )
    assert exc_info.value.code == "TEMPLATE_MAPPING_INVALID"
    assert not output_dir.exists()


def test_load_template_definition_rejects_illegal_row_range(tmp_path: Path):
    bad_mapping = tmp_path / "bad.yaml"
    bad_mapping.write_text(
        "id: x\nformat: xlsx\nsheet: Sheet1\nitems:\n  start_row: not-a-number\n  end_row: 5\n  columns:\n    sku: A\n",
        encoding="utf-8",
    )
    with pytest.raises(TemplateDefinitionError):
        load_template_definition(bad_mapping)


def test_load_template_definition_rejects_invalid_yaml(tmp_path: Path):
    bad_mapping = tmp_path / "bad.yaml"
    bad_mapping.write_text("id: [unterminated", encoding="utf-8")
    with pytest.raises(TemplateDefinitionError):
        load_template_definition(bad_mapping)


def test_load_template_definition_rejects_wrong_structure(tmp_path: Path):
    bad_mapping = tmp_path / "bad.yaml"
    bad_mapping.write_text("id: x\nformat: xlsx\nsheet: Sheet1\nitems: not-a-mapping\n", encoding="utf-8")
    with pytest.raises(TemplateDefinitionError):
        load_template_definition(bad_mapping)


def test_generate_batch_aborts_whole_batch_when_template_missing(
    sample_batch_dict, delivery_template_path, tmp_path
):
    batch_path = tmp_path / "batch.json"
    batch_path.write_text(json.dumps([sample_batch_dict]), encoding="utf-8")
    output_dir = tmp_path / "output"

    with pytest.raises(TemplatePreflightError):
        generate_batch(
            batch_path,
            contract_template_path=tmp_path / "missing-contract.xlsx",
            delivery_template_path=delivery_template_path,
            output_dir=output_dir,
        )

    # A whole-batch preflight failure must not be disguised as per-record
    # FAILED entries, and must not produce a manifest.
    assert not output_dir.exists()
