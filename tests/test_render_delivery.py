from pathlib import Path

import openpyxl

from docflow.domain.document import DocumentType, build_projection
from docflow.renderers.xlsx import render
from docflow.templates.registry import TemplateRegistry
from tests.conftest import make_fact_pack


def test_single_delivery_note_generation(delivery_template_path: Path, tmp_path: Path):
    pack = make_fact_pack(item_count=3)
    projection = build_projection(pack, DocumentType.DELIVERY_NOTE_V1)
    definition = TemplateRegistry().get(DocumentType.DELIVERY_NOTE_V1)
    output_path = tmp_path / "delivery-note.xlsx"

    render(definition, delivery_template_path, projection, output_path)

    assert output_path.exists()
    wb = openpyxl.load_workbook(output_path)
    ws = wb["送货单"]
    assert ws["A3"].value == f"收货单位：{pack.ship_to.company}"
    assert ws["D3"].value == f"联系人：{pack.ship_to.contact}"
    assert ws["F3"].value == f"NO：{pack.delivery_no}"
    assert ws["A4"].value == f"收货地址：{pack.ship_to.address}"

    first_item = projection.items[0]
    assert ws["A7"].value == 1
    assert ws["B7"].value == first_item.product_name
    assert ws["F7"].value == float(first_item.gross_unit_price)
    # Column G (金额) is a native formula, left untouched by the renderer.
    assert ws["G7"].value == "=D7*F7"
