import json
from pathlib import Path

from docflow.cli import main


def _seed(root: Path) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    (root / "organizations.yaml").write_text("""
organizations:
  acme:
    name: 甲公司
    roles: [supplier]
    aliases: [小甲]
""", encoding="utf-8")
    return root


# 5/6/7. no-arg validate/resolve/apply default to $PWD/.docflow/catalog
def test_validate_defaults_to_workspace_local_catalog(tmp_path, monkeypatch, capsys):
    _seed(tmp_path / ".docflow" / "catalog")
    monkeypatch.delenv("DOCFLOW_CATALOG_ROOT", raising=False)
    monkeypatch.chdir(tmp_path)

    exit_code = main(["catalog", "validate"])
    assert exit_code == 0
    assert str(tmp_path / ".docflow" / "catalog") in capsys.readouterr().out


def test_resolve_defaults_to_workspace_local_catalog(tmp_path, monkeypatch, capsys):
    _seed(tmp_path / ".docflow" / "catalog")
    monkeypatch.delenv("DOCFLOW_CATALOG_ROOT", raising=False)
    monkeypatch.chdir(tmp_path)

    exit_code = main(["catalog", "resolve", "--kind", "organization", "--query", "甲公司"])
    assert exit_code == 0
    assert json.loads(capsys.readouterr().out)["status"] == "RESOLVED"


def test_apply_defaults_to_workspace_local_catalog(tmp_path, monkeypatch, capsys):
    _seed(tmp_path / ".docflow" / "catalog")
    monkeypatch.delenv("DOCFLOW_CATALOG_ROOT", raising=False)
    monkeypatch.chdir(tmp_path)

    change_file = tmp_path / "change.json"
    change_file.write_text(json.dumps([{
        "operation": "upsert_contact", "organization": "acme",
        "contact": {"id": "c1", "name": "张三", "default": True},
    }]), encoding="utf-8")

    exit_code = main(["catalog", "apply", "--input", str(change_file)])
    assert exit_code == 0
    assert (tmp_path / ".docflow" / "catalog" / "organizations.yaml").exists()


# an empty, not-yet-initialized default workspace is still a valid (empty) catalog
def test_validate_on_fresh_workspace_with_no_docflow_dir_is_valid_and_empty(tmp_path, monkeypatch, capsys):
    monkeypatch.delenv("DOCFLOW_CATALOG_ROOT", raising=False)
    monkeypatch.chdir(tmp_path)
    exit_code = main(["catalog", "validate"])
    assert exit_code == 0
    assert not (tmp_path / ".docflow").exists()  # validate never creates anything


# 8. explicit --catalog-root overrides workspace default
def test_explicit_catalog_root_overrides_workspace_default(tmp_path, monkeypatch, capsys):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    other_root = tmp_path / "elsewhere"
    _seed(other_root)
    monkeypatch.delenv("DOCFLOW_CATALOG_ROOT", raising=False)
    monkeypatch.chdir(workspace)

    exit_code = main(["catalog", "validate", "--catalog-root", str(other_root)])
    assert exit_code == 0
    assert not (workspace / ".docflow").exists()


# 9. DOCFLOW_CATALOG_ROOT overrides workspace default
def test_env_var_overrides_workspace_default(tmp_path, monkeypatch, capsys):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    other_root = tmp_path / "elsewhere"
    _seed(other_root)
    monkeypatch.setenv("DOCFLOW_CATALOG_ROOT", str(other_root))
    monkeypatch.chdir(workspace)

    exit_code = main(["catalog", "validate"])
    assert exit_code == 0
    assert not (workspace / ".docflow").exists()


# 10. explicit flag takes priority over env var
def test_explicit_flag_takes_priority_over_env_var(tmp_path, monkeypatch, capsys):
    _seed(tmp_path)
    monkeypatch.setenv("DOCFLOW_CATALOG_ROOT", "/nonexistent/env/path")
    exit_code = main(["catalog", "validate", "--catalog-root", str(tmp_path)])
    assert exit_code == 0


# 11. workspace A / B isolation
def test_two_workspaces_have_isolated_catalogs(tmp_path, monkeypatch, capsys):
    monkeypatch.delenv("DOCFLOW_CATALOG_ROOT", raising=False)
    workspace_a = tmp_path / "client-a"
    workspace_b = tmp_path / "client-b"
    _seed(workspace_a / ".docflow" / "catalog")
    workspace_b.mkdir()

    monkeypatch.chdir(workspace_a)
    exit_code = main(["catalog", "resolve", "--kind", "organization", "--query", "甲公司"])
    assert exit_code == 0
    assert json.loads(capsys.readouterr().out)["status"] == "RESOLVED"

    monkeypatch.chdir(workspace_b)
    exit_code = main(["catalog", "resolve", "--kind", "organization", "--query", "甲公司"])
    assert exit_code == 1
    assert json.loads(capsys.readouterr().out)["status"] == "NOT_FOUND"


# 12. no recursion to parent directories looking for .docflow
def test_does_not_search_parent_directories_for_docflow_dir(tmp_path, monkeypatch, capsys):
    _seed(tmp_path / ".docflow" / "catalog")  # only at the grandparent level
    nested_cwd = tmp_path / "sub" / "nested"
    nested_cwd.mkdir(parents=True)
    monkeypatch.delenv("DOCFLOW_CATALOG_ROOT", raising=False)
    monkeypatch.chdir(nested_cwd)

    exit_code = main(["catalog", "resolve", "--kind", "organization", "--query", "甲公司"])
    assert exit_code == 1
    assert json.loads(capsys.readouterr().out)["status"] == "NOT_FOUND"


def test_validate_exits_2_on_invalid_catalog(tmp_path, capsys):
    (tmp_path / "organizations.yaml").write_text("organizations: [not, a, mapping]", encoding="utf-8")
    exit_code = main(["catalog", "validate", "--catalog-root", str(tmp_path)])
    assert exit_code == 2


def test_resolve_exit_codes_match_status(tmp_path, capsys):
    _seed(tmp_path)

    exit_code = main(["catalog", "resolve", "--catalog-root", str(tmp_path), "--kind", "organization", "--query", "甲公司"])
    assert exit_code == 0
    assert json.loads(capsys.readouterr().out)["status"] == "RESOLVED"

    exit_code = main(["catalog", "resolve", "--catalog-root", str(tmp_path), "--kind", "organization", "--query", "不存在"])
    assert exit_code == 1
    assert json.loads(capsys.readouterr().out)["status"] == "NOT_FOUND"


def test_apply_cli_end_to_end(tmp_path, capsys):
    _seed(tmp_path)
    change_file = tmp_path / "change.json"
    change_file.write_text(json.dumps([{
        "operation": "upsert_contact",
        "organization": "acme",
        "contact": {"id": "c1", "name": "张三", "default": True},
    }]), encoding="utf-8")

    exit_code = main(["catalog", "apply", "--catalog-root", str(tmp_path), "--input", str(change_file)])
    assert exit_code == 0
    capsys.readouterr()  # discard the apply command's plain-text output

    exit_code = main(["catalog", "resolve", "--catalog-root", str(tmp_path), "--kind", "organization", "--query", "小甲"])
    assert exit_code == 0
    result = json.loads(capsys.readouterr().out)
    assert result["contact"]["id"] == "c1"


def test_apply_cli_rejects_malformed_change_file(tmp_path, capsys):
    _seed(tmp_path)
    change_file = tmp_path / "change.json"
    change_file.write_text("not json at all {{{", encoding="utf-8")

    exit_code = main(["catalog", "apply", "--catalog-root", str(tmp_path), "--input", str(change_file)])
    assert exit_code == 2
    assert "No changes were written" in capsys.readouterr().err


def test_init_cli_creates_workspace_local_catalog(tmp_path, monkeypatch, capsys):
    monkeypatch.delenv("DOCFLOW_CATALOG_ROOT", raising=False)
    monkeypatch.chdir(tmp_path)

    exit_code = main(["catalog", "init"])
    assert exit_code == 0
    assert (tmp_path / ".docflow" / "catalog" / "organizations.yaml").exists()
    assert (tmp_path / ".docflow" / "catalog" / "products.yaml").exists()
    assert (tmp_path / ".docflow" / "catalog" / "templates.yaml").exists()


def test_init_cli_rejects_and_preserves_malformed_existing_catalog(tmp_path, capsys):
    root = tmp_path / "catalog"
    root.mkdir()
    bad_content = "organizations: [not, a, mapping]"
    (root / "organizations.yaml").write_text(bad_content, encoding="utf-8")

    exit_code = main(["catalog", "init", "--catalog-root", str(root)])
    assert exit_code == 2
    assert (root / "organizations.yaml").read_text(encoding="utf-8") == bad_content


def test_import_template_cli_end_to_end(tmp_path, capsys):
    from tests.fixtures.synthetic_templates import build_contract_template

    catalog_root = tmp_path / "catalog"
    source = build_contract_template(tmp_path / "external.xlsx")

    exit_code = main([
        "catalog", "import-template", "--catalog-root", str(catalog_root),
        "--key", "procurement_contract", "--document-type", "procurement.contract.v1",
        "--source", str(source),
    ])
    assert exit_code == 0, capsys.readouterr()
    capsys.readouterr()

    exit_code = main([
        "catalog", "resolve", "--catalog-root", str(catalog_root),
        "--kind", "template", "--query", "procurement_contract",
    ])
    assert exit_code == 0
    import json
    result = json.loads(capsys.readouterr().out)
    assert result["status"] == "RESOLVED"
    assert Path(result["path"]).exists()
    assert "external" not in result["path"]


def test_import_template_cli_rejects_existing_without_replace(tmp_path, capsys):
    from tests.fixtures.synthetic_templates import build_contract_template

    catalog_root = tmp_path / "catalog"
    source = build_contract_template(tmp_path / "external.xlsx")
    args = [
        "catalog", "import-template", "--catalog-root", str(catalog_root),
        "--key", "procurement_contract", "--document-type", "procurement.contract.v1",
        "--source", str(source),
    ]
    assert main(args) == 0
    capsys.readouterr()

    exit_code = main(args)  # no --replace
    assert exit_code == 2
    assert "TEMPLATE_ALREADY_EXISTS" in capsys.readouterr().err

    exit_code = main([*args, "--replace"])
    assert exit_code == 0


def test_import_seal_cli_end_to_end(tmp_path, capsys):
    from PIL import Image

    catalog_root = _seed(tmp_path / "catalog")
    source = tmp_path / "seal.png"
    Image.new("RGBA", (32, 32), (200, 0, 0, 180)).save(source, "PNG")

    exit_code = main([
        "catalog", "import-seal", "--catalog-root", str(catalog_root),
        "--organization", "acme", "--source", str(source),
    ])
    assert exit_code == 0, capsys.readouterr()
    managed = catalog_root.parent / "assets" / "seals" / "acme.png"
    assert managed.is_file()
    organizations = (catalog_root / "organizations.yaml").read_text(encoding="utf-8")
    assert "../assets/seals/acme.png" in organizations
