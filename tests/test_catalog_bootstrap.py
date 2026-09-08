from pathlib import Path

import pytest

from docflow.catalog.bootstrap import init_catalog
from docflow.catalog.loader import CatalogError, load_catalog


# 1. init creates 3 files in an empty workspace
def test_init_creates_all_three_files_in_empty_workspace(tmp_path: Path):
    root = tmp_path / ".docflow" / "catalog"
    init_catalog(root)

    assert (root / "organizations.yaml").read_text(encoding="utf-8").strip() == "organizations: {}"
    assert (root / "products.yaml").read_text(encoding="utf-8").strip() == "products: {}"
    assert (root / "templates.yaml").read_text(encoding="utf-8").strip() == "templates: {}"

    catalog = load_catalog(root)
    assert catalog.organizations == {}
    assert catalog.products == {}
    assert catalog.templates == {}


# 2. second init does not overwrite existing data
def test_second_init_does_not_overwrite_existing_data(tmp_path: Path):
    root = tmp_path / ".docflow" / "catalog"
    init_catalog(root)

    (root / "organizations.yaml").write_text("""
organizations:
  acme:
    name: 甲公司
""", encoding="utf-8")

    init_catalog(root)  # run again

    catalog = load_catalog(root)
    assert "acme" in catalog.organizations
    assert catalog.organizations["acme"].name == "甲公司"


# 3. partial files existing -> only missing ones created
def test_init_only_creates_missing_files(tmp_path: Path):
    root = tmp_path / ".docflow" / "catalog"
    root.mkdir(parents=True)
    (root / "organizations.yaml").write_text("""
organizations:
  acme:
    name: 甲公司
""", encoding="utf-8")
    # products.yaml and templates.yaml deliberately absent

    init_catalog(root)

    assert (root / "products.yaml").exists()
    assert (root / "templates.yaml").exists()
    catalog = load_catalog(root)
    assert "acme" in catalog.organizations  # untouched
    assert catalog.products == {}
    assert catalog.templates == {}


# 4. malformed existing YAML -> init rejects, does not overwrite
def test_init_rejects_and_preserves_malformed_existing_file(tmp_path: Path):
    root = tmp_path / ".docflow" / "catalog"
    root.mkdir(parents=True)
    bad_content = "organizations:\n  acme:\n    contacts:\n      - id: c1\n        name: a\n        default: true\n      - id: c2\n        name: b\n        default: true\n"
    (root / "organizations.yaml").write_text(bad_content, encoding="utf-8")

    with pytest.raises(CatalogError) as exc_info:
        init_catalog(root)
    assert exc_info.value.code == "INVALID_CATALOG"

    # Untouched - init must not "fix" or rewrite it to force success.
    assert (root / "organizations.yaml").read_text(encoding="utf-8") == bad_content
    # And it must not have silently created the other two either, leaving
    # a half-initialized catalog masquerading as done - actually it's fine
    # for them to exist since they'd be empty/valid; what matters is the
    # bad file was left alone and init reported failure.


def test_init_is_idempotent_when_nothing_changes(tmp_path: Path):
    root = tmp_path / ".docflow" / "catalog"
    init_catalog(root)
    first_snapshot = {p.name: p.read_text(encoding="utf-8") for p in root.iterdir()}

    init_catalog(root)
    second_snapshot = {p.name: p.read_text(encoding="utf-8") for p in root.iterdir()}

    assert first_snapshot == second_snapshot


# 13. init then synthetic empty catalog validate PASS
def test_init_then_validate_passes(tmp_path: Path):
    root = tmp_path / ".docflow" / "catalog"
    init_catalog(root)
    load_catalog(root)  # must not raise
