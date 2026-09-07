from __future__ import annotations

from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from docflow.domain.facts import DocumentFactPack, LineItemFacts, ShipTo
from tests.fixtures.synthetic_templates import build_contract_template, build_delivery_template

CONTRACT_CAPACITY = 18
DELIVERY_CAPACITY = 18


@pytest.fixture
def contract_template_path(tmp_path: Path) -> Path:
    return build_contract_template(tmp_path / "contract-template.xlsx")


@pytest.fixture
def delivery_template_path(tmp_path: Path) -> Path:
    return build_delivery_template(tmp_path / "delivery-template.xlsx")


def make_line_item(index: int, quantity: int = 2, net_unit_price: str = "100.00") -> LineItemFacts:
    return LineItemFacts(
        sku=f"SKU-{index:03d}",
        product_name=f"测试产品{index}",
        specification=f"型号SKU-{index:03d}",
        quantity=Decimal(quantity),
        unit="件",
        net_unit_price=Decimal(net_unit_price),
        tax_rate=Decimal("0.13"),
    )


def make_fact_pack(business_reference: str = "BR-0001", item_count: int = 2) -> DocumentFactPack:
    return DocumentFactPack(
        business_reference=business_reference,
        contract_no=f"CT-{business_reference}",
        delivery_no=f"DN-{business_reference}",
        contract_date=date(2026, 5, 16),
        delivery_date=date(2026, 6, 9),
        buyer="测试采购方有限公司",
        seller="测试供应商有限公司",
        seller_contact="测试联系人",
        seller_phone="10000000000",
        seller_address="测试省测试市测试地址",
        ship_to=ShipTo(
            company="测试收货单位",
            contact="测试收货联系人",
            phone="20000000000",
            address="测试收货地址",
        ),
        items=tuple(make_line_item(i) for i in range(1, item_count + 1)),
    )


@pytest.fixture
def sample_fact_pack() -> DocumentFactPack:
    return make_fact_pack()


@pytest.fixture
def sample_batch_dict() -> dict:
    return {
        "business_reference": "BR-BATCH-0001",
        "contract_no": "CT-BR-BATCH-0001",
        "delivery_no": "DN-BR-BATCH-0001",
        "contract_date": "2026-05-16",
        "delivery_date": "2026-06-09",
        "buyer": "测试采购方有限公司",
        "seller": "测试供应商有限公司",
        "seller_contact": "测试联系人",
        "seller_phone": "10000000000",
        "seller_address": "测试省测试市测试地址",
        "ship_to": {
            "company": "测试收货单位",
            "contact": "测试收货联系人",
            "phone": "20000000000",
            "address": "测试收货地址",
        },
        "items": [
            {
                "sku": "SKU-001",
                "product_name": "测试产品1",
                "specification": "型号SKU-001",
                "quantity": 2,
                "unit": "件",
                "net_unit_price": "100.00",
                "tax_rate": "0.13",
            }
        ],
    }
