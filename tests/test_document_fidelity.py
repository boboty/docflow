from __future__ import annotations

import json
import shutil
from pathlib import Path

import openpyxl
import pytest
import yaml
from PIL import Image as PILImage

from docflow.application.generation import PASS, generate_batch
from docflow.catalog.loader import load_catalog
import docflow.catalog.mutation as mutation
from docflow.catalog.mutation import CatalogMutationError, import_seal


def _png(path: Path, color: tuple[int, int, int, int]) -> Path:
    PILImage.new("RGBA", (120, 120), color).save(path, "PNG")
    return path


def _catalog(root: Path, seller_name: str) -> Path:
    root.mkdir(parents=True)
    (root / "organizations.yaml").write_text(
        yaml.safe_dump({"organizations": {"linyi_yier": {
            "name": seller_name, "roles": ["supplier"], "aliases": ["临沂亦尔"]
        }}}, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
    return root


def _batch(path: Path, record: dict) -> Path:
    path.write_text(json.dumps([record], ensure_ascii=False), encoding="utf-8")
    return path


def _print_signature(path: Path) -> dict:
    workbook = openpyxl.load_workbook(path)
    ws = workbook[workbook.sheetnames[0]]
    setup = ws.page_setup
    margins = ws.page_margins
    options = ws.print_options
    return {
        "paperSize": setup.paperSize,
        "orientation": setup.orientation,
        "scale": setup.scale,
        "fitToWidth": setup.fitToWidth,
        "fitToHeight": setup.fitToHeight,
        "fitToPage": ws.sheet_properties.pageSetUpPr.fitToPage,
        "margins": (margins.left, margins.right, margins.top, margins.bottom, margins.header, margins.footer),
        "options": (options.horizontalCentered, options.verticalCentered, options.gridLines, options.headings),
        "print_area": str(ws.print_area),
        "print_title_rows": ws.print_title_rows,
        "print_title_cols": ws.print_title_cols,
        "row_breaks": tuple(brk.id for brk in ws.row_breaks.brk),
        "col_breaks": tuple(brk.id for brk in ws.col_breaks.brk),
        "header": ws.oddHeader.center.text,
        "footer": ws.oddFooter.right.text,
    }


def test_import_seal_managed_copy_survives_source_delete_and_workspace_move(tmp_path: Path):
    workspace = tmp_path / "workspace"
    root = _catalog(workspace / ".docflow" / "catalog", "临沂亦尔科技有限公司")
    source = _png(tmp_path / "external.png", (220, 0, 0, 180))

    import_seal(root, "linyi_yier", source, replace=False)
    source.unlink()
    org = load_catalog(root).organizations["linyi_yier"]
    assert org.seal is not None and org.seal.path == "../assets/seals/linyi_yier.png"
    assert (root / org.seal.path).resolve().is_file()

    moved = tmp_path / "moved-workspace"
    shutil.copytree(workspace, moved)
    moved_root = moved / ".docflow" / "catalog"
    moved_org = load_catalog(moved_root).organizations["linyi_yier"]
    assert (moved_root / moved_org.seal.path).resolve().is_file()


def test_import_seal_replace_and_invalid_inputs_are_atomic(tmp_path: Path):
    root = _catalog(tmp_path / "workspace" / ".docflow" / "catalog", "临沂亦尔科技有限公司")
    first = _png(tmp_path / "first.png", (200, 0, 0, 255))
    second = _png(tmp_path / "second.png", (0, 0, 200, 255))
    import_seal(root, "linyi_yier", first, replace=False)
    managed = root.parent / "assets" / "seals" / "linyi_yier.png"
    first_bytes = managed.read_bytes()

    with pytest.raises(CatalogMutationError) as existing:
        import_seal(root, "linyi_yier", second, replace=False)
    assert existing.value.code == "SEAL_ALREADY_EXISTS"
    assert managed.read_bytes() == first_bytes

    import_seal(root, "linyi_yier", second, replace=True)
    second_bytes = managed.read_bytes()
    assert second_bytes != first_bytes

    catalog_before = (root / "organizations.yaml").read_bytes()
    bad = tmp_path / "bad.png"
    bad.write_bytes(b"not a png")
    with pytest.raises(CatalogMutationError) as invalid:
        import_seal(root, "linyi_yier", bad, replace=True)
    assert invalid.value.code == "SEAL_SOURCE_INVALID"
    assert managed.read_bytes() == second_bytes
    assert (root / "organizations.yaml").read_bytes() == catalog_before

    with pytest.raises(CatalogMutationError) as missing:
        import_seal(root, "linyi_yier", tmp_path / "missing.png", replace=True)
    assert missing.value.code == "SEAL_SOURCE_MISSING"
    assert managed.read_bytes() == second_bytes


def test_import_seal_commit_failure_rolls_back_binary_and_catalog(tmp_path: Path, monkeypatch):
    root = _catalog(tmp_path / "workspace" / ".docflow" / "catalog", "临沂亦尔科技有限公司")
    first = _png(tmp_path / "first.png", (200, 0, 0, 255))
    second = _png(tmp_path / "second.png", (0, 0, 200, 255))
    import_seal(root, "linyi_yier", first, replace=False)
    managed = root.parent / "assets" / "seals" / "linyi_yier.png"
    managed_before = managed.read_bytes()
    catalog_before = (root / "organizations.yaml").read_bytes()

    def fail_write(*args, **kwargs):
        raise OSError("simulated catalog write failure")

    monkeypatch.setattr(mutation, "_write_yaml_atomic", fail_write)
    with pytest.raises(CatalogMutationError) as failed:
        import_seal(root, "linyi_yier", second, replace=True)
    assert failed.value.code == "SEAL_IMPORT_FAILED"
    assert managed.read_bytes() == managed_before
    assert (root / "organizations.yaml").read_bytes() == catalog_before
    assert not list(managed.parent.glob(".*.tmp"))
    assert not list(managed.parent.glob(".*.bak"))


def test_generation_inserts_seal_and_preserves_print_settings_for_both_documents(
    tmp_path: Path, sample_batch_dict: dict, contract_template_path: Path, delivery_template_path: Path,
):
    root = _catalog(tmp_path / "workspace" / ".docflow" / "catalog", sample_batch_dict["seller"])
    source = _png(tmp_path / "seal.png", (220, 0, 0, 180))
    import_seal(root, "linyi_yier", source, replace=False)
    output = tmp_path / "output"
    summary = generate_batch(
        _batch(tmp_path / "batch.json", sample_batch_dict),
        contract_template_path, delivery_template_path, output,
        catalog_root=root,
    )

    assert summary.failed_documents == 0
    assert all(entry.validation_status == PASS for entry in summary.entries)
    assert all("IMAGE_INSERTED seller_seal" in entry.enhancements for entry in summary.entries)
    for entry, template in zip(summary.entries, (contract_template_path, delivery_template_path), strict=True):
        generated = output / entry.output_file
        ws = openpyxl.load_workbook(generated)[openpyxl.load_workbook(generated).sheetnames[0]]
        assert len(ws._images) == 1
        anchor = ws._images[0].anchor
        assert (anchor.ext.cx, anchor.ext.cy) == (38 * 36_000, 38 * 36_000)
        expected_anchor = (5, 45) if entry.document_type == "procurement.contract.v1" else (1, 30)
        assert (anchor._from.col, anchor._from.row) == expected_anchor
        assert _print_signature(generated) == _print_signature(template)


def test_missing_seal_is_skipped_without_affecting_pass(
    tmp_path: Path, sample_batch_dict: dict, contract_template_path: Path, delivery_template_path: Path,
):
    root = _catalog(tmp_path / "workspace" / ".docflow" / "catalog", sample_batch_dict["seller"])
    output = tmp_path / "output"
    summary = generate_batch(
        _batch(tmp_path / "batch.json", sample_batch_dict),
        contract_template_path, delivery_template_path, output,
        catalog_root=root,
    )
    assert summary.failed_documents == 0
    assert all(any("IMAGE_SKIPPED seller_seal" in note for note in entry.enhancements) for entry in summary.entries)
    assert all(not openpyxl.load_workbook(output / entry.output_file).active._images for entry in summary.entries)
