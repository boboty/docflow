from pathlib import Path

from docflow.catalog.root import resolve_catalog_root


def test_explicit_wins_over_everything(monkeypatch, tmp_path):
    monkeypatch.setenv("DOCFLOW_CATALOG_ROOT", "/env/path")
    explicit = tmp_path / "explicit"
    assert resolve_catalog_root(explicit=explicit, cwd=tmp_path) == explicit


def test_env_var_wins_over_workspace_default(monkeypatch, tmp_path):
    monkeypatch.setenv("DOCFLOW_CATALOG_ROOT", "/env/path")
    assert resolve_catalog_root(explicit=None, cwd=tmp_path) == Path("/env/path")


def test_workspace_default_when_nothing_else_configured(monkeypatch, tmp_path):
    monkeypatch.delenv("DOCFLOW_CATALOG_ROOT", raising=False)
    assert resolve_catalog_root(explicit=None, cwd=tmp_path) == tmp_path / ".docflow" / "catalog"


def test_never_walks_up_to_a_parent_directory(monkeypatch, tmp_path):
    monkeypatch.delenv("DOCFLOW_CATALOG_ROOT", raising=False)
    (tmp_path / ".docflow" / "catalog").mkdir(parents=True)
    nested = tmp_path / "a" / "b"
    nested.mkdir(parents=True)

    result = resolve_catalog_root(explicit=None, cwd=nested)
    assert result == nested / ".docflow" / "catalog"
    assert result != tmp_path / ".docflow" / "catalog"


def test_defaults_to_real_cwd_when_not_given(monkeypatch, tmp_path):
    monkeypatch.delenv("DOCFLOW_CATALOG_ROOT", raising=False)
    monkeypatch.chdir(tmp_path)
    assert resolve_catalog_root() == tmp_path / ".docflow" / "catalog"
