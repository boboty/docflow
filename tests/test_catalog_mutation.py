from pathlib import Path

import pytest

from docflow.catalog.loader import load_catalog
from docflow.catalog.mutation import CatalogMutationError, apply_operations
from docflow.catalog.resolve import resolve_organization


def _seed(tmp_path: Path) -> Path:
    (tmp_path / "organizations.yaml").write_text("""
organizations:
  zhongyi:
    name: 广州市众壹供应链有限公司
    roles: [freight_forwarder, ship_to]
    aliases: [众壹]
    addresses:
      - id: yiwu
        label: 义乌仓
        address: 浙江省金华市示例地址
        default: false
      - id: guangzhou
        label: 广州仓
        address: 广州市示例地址
        default: false
""", encoding="utf-8")
    return tmp_path


# 19. mutation add address
def test_apply_adds_new_address(tmp_path: Path):
    root = _seed(tmp_path)
    apply_operations(root, [{
        "operation": "upsert_address",
        "organization": "zhongyi",
        "address": {"id": "ningbo", "label": "宁波仓", "address": "浙江省宁波市示例地址", "default": False},
    }])

    catalog = load_catalog(root)
    org = catalog.organizations["zhongyi"]
    assert any(a.id == "ningbo" for a in org.addresses)
    assert len(org.addresses) == 3


# 20. mutation then immediately resolvable
def test_apply_then_resolve_finds_new_address(tmp_path: Path):
    root = _seed(tmp_path)
    apply_operations(root, [{
        "operation": "upsert_address",
        "organization": "zhongyi",
        "address": {"id": "ningbo", "label": "宁波仓", "address": "浙江省宁波市示例地址", "default": False},
    }])

    catalog = load_catalog(root)
    result = resolve_organization(catalog, "众壹", address_query="宁波仓")
    assert result["status"] == "RESOLVED"
    assert result["address"]["id"] == "ningbo"


# 21. mutation producing duplicate default must be rejected, atomically
def test_apply_rejects_duplicate_default_and_writes_nothing(tmp_path: Path):
    root = _seed(tmp_path)
    original_content = (root / "organizations.yaml").read_text(encoding="utf-8")

    with pytest.raises(CatalogMutationError) as exc_info:
        apply_operations(root, [
            {"operation": "upsert_address", "organization": "zhongyi",
             "address": {"id": "yiwu", "label": "义乌仓", "address": "地址", "default": True}},
            {"operation": "upsert_address", "organization": "zhongyi",
             "address": {"id": "guangzhou", "label": "广州仓", "address": "地址", "default": True}},
        ])
    assert exc_info.value.code == "DUPLICATE_DEFAULT"

    # Atomic: nothing was written, not even the first (individually valid) op.
    assert (root / "organizations.yaml").read_text(encoding="utf-8") == original_content


def test_apply_rejects_unknown_organization(tmp_path: Path):
    root = _seed(tmp_path)
    with pytest.raises(CatalogMutationError) as exc_info:
        apply_operations(root, [{
            "operation": "upsert_contact",
            "organization": "no_such_org",
            "contact": {"id": "c1", "name": "张三"},
        }])
    assert exc_info.value.code == "ORGANIZATION_NOT_FOUND"


def test_apply_bootstraps_catalog_from_nothing(tmp_path: Path):
    apply_operations(tmp_path, [{
        "operation": "upsert_organization",
        "id": "new_org",
        "name": "全新公司",
        "roles": ["supplier"],
    }])
    catalog = load_catalog(tmp_path)
    assert catalog.organizations["new_org"].name == "全新公司"


def test_apply_upsert_product(tmp_path: Path):
    apply_operations(tmp_path, [{
        "operation": "upsert_product",
        "id": "SKU-X",
        "product": {"name": "示例产品X", "unit": "件", "aliases": ["X产品"]},
    }])
    catalog = load_catalog(tmp_path)
    assert catalog.products["SKU-X"].name == "示例产品X"


def test_apply_set_template(tmp_path: Path):
    apply_operations(tmp_path, [{
        "operation": "set_template",
        "key": "procurement_contract",
        "document_type": "procurement.contract.v1",
        "path": "/abs/path/contract.xlsx",
    }])
    catalog = load_catalog(tmp_path)
    assert catalog.templates["procurement_contract"].path == "/abs/path/contract.xlsx"
