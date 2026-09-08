from pathlib import Path

import pytest

from docflow.catalog.loader import CatalogError, load_catalog

REPO_ROOT = Path(__file__).resolve().parent.parent
EXAMPLE_CATALOG_DIR = REPO_ROOT / "skills" / "docflow" / "examples" / "catalog"


def _write_catalog(tmp_path: Path, organizations_yaml: str) -> Path:
    (tmp_path / "organizations.yaml").write_text(organizations_yaml, encoding="utf-8")
    return tmp_path


# 15. duplicate default -> INVALID_CATALOG
def test_duplicate_default_contact_is_invalid_catalog(tmp_path: Path):
    root = _write_catalog(tmp_path, """
organizations:
  acme:
    name: 甲公司
    contacts:
      - id: c1
        name: 张三
        default: true
      - id: c2
        name: 李四
        default: true
""")
    with pytest.raises(CatalogError) as exc_info:
        load_catalog(root)
    assert exc_info.value.code == "INVALID_CATALOG"


def test_duplicate_default_address_is_invalid_catalog(tmp_path: Path):
    root = _write_catalog(tmp_path, """
organizations:
  acme:
    name: 甲公司
    addresses:
      - id: a1
        address: 地址1
        default: true
      - id: a2
        address: 地址2
        default: true
""")
    with pytest.raises(CatalogError) as exc_info:
        load_catalog(root)
    assert exc_info.value.code == "INVALID_CATALOG"


def test_duplicate_contact_id_is_invalid_catalog(tmp_path: Path):
    root = _write_catalog(tmp_path, """
organizations:
  acme:
    name: 甲公司
    contacts:
      - id: c1
        name: 张三
      - id: c1
        name: 李四
""")
    with pytest.raises(CatalogError) as exc_info:
        load_catalog(root)
    assert exc_info.value.code == "INVALID_CATALOG"


# 18. malformed YAML -> INVALID_CATALOG
def test_malformed_yaml_is_invalid_catalog(tmp_path: Path):
    (tmp_path / "organizations.yaml").write_text("organizations: [this is not\n  a valid: mapping", encoding="utf-8")
    with pytest.raises(CatalogError) as exc_info:
        load_catalog(tmp_path)
    assert exc_info.value.code == "INVALID_CATALOG"


def test_missing_files_yield_empty_valid_catalog(tmp_path: Path):
    catalog = load_catalog(tmp_path)
    assert catalog.organizations == {}
    assert catalog.products == {}
    assert catalog.templates == {}


def test_organization_missing_name_is_invalid_catalog(tmp_path: Path):
    root = _write_catalog(tmp_path, """
organizations:
  acme:
    roles: [supplier]
""")
    with pytest.raises(CatalogError) as exc_info:
        load_catalog(root)
    assert exc_info.value.code == "INVALID_CATALOG"


# 22. synthetic Catalog example validate PASS
def test_synthetic_example_catalog_is_valid(tmp_path: Path):
    # The repo stores these as *.example.yaml so they're unmistakably not a
    # real catalog root; load_catalog expects the real filenames, so copy
    # them over for the actual validation pass.
    for name in ("organizations", "products", "templates"):
        source = EXAMPLE_CATALOG_DIR / f"{name}.example.yaml"
        (tmp_path / f"{name}.yaml").write_text(source.read_text(encoding="utf-8"), encoding="utf-8")

    catalog = load_catalog(tmp_path)
    assert catalog.organizations
    assert catalog.products
    assert catalog.templates
