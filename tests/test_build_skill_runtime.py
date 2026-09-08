"""Verifies scripts/build_skill_runtime.py actually produces a runtime
that matches src/docflow byte-for-byte (minus dev-only cruft). This is
what keeps 'src/docflow is the source of truth' from silently drifting
out of sync with the bundled Skill runtime.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SOURCE_PACKAGE = REPO_ROOT / "src" / "docflow"
DEST_PACKAGE = REPO_ROOT / "skills" / "docflow" / "runtime" / "src" / "docflow"
BUILD_SCRIPT = REPO_ROOT / "scripts" / "build_skill_runtime.py"

_IGNORED_SUFFIXES = {".pyc", ".pyo"}
_IGNORED_DIR_NAMES = {"__pycache__", ".pytest_cache"}


def _tracked_files(root: Path) -> dict[str, str]:
    files = {}
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        if path.suffix in _IGNORED_SUFFIXES or any(part in _IGNORED_DIR_NAMES for part in path.parts):
            continue
        files[str(path.relative_to(root))] = path.read_text(encoding="utf-8")
    return files


def test_sync_script_reproduces_source_exactly():
    result = subprocess.run(
        [sys.executable, str(BUILD_SCRIPT)], cwd=str(REPO_ROOT), capture_output=True, text=True, timeout=30
    )
    assert result.returncode == 0, result.stderr

    source_files = _tracked_files(SOURCE_PACKAGE)
    dest_files = _tracked_files(DEST_PACKAGE)

    assert source_files.keys() == dest_files.keys()
    for relative_path, content in source_files.items():
        assert dest_files[relative_path] == content, f"{relative_path} differs between src/docflow and bundled runtime"


def test_runtime_is_a_pep723_script_with_no_setuptools_project(tmp_path: Path):
    runtime_dir = DEST_PACKAGE.parent.parent

    run_py = runtime_dir / "run.py"
    assert run_py.exists()
    run_py_text = run_py.read_text(encoding="utf-8")
    assert "# /// script" in run_py_text
    assert "openpyxl" in run_py_text
    assert "PyYAML" in run_py_text

    assert (runtime_dir / "run.py.lock").exists()

    # No setuptools/editable-install project - PEP 723 resolves run.py's
    # own declared deps only, it never builds or installs a `docflow`
    # package.
    assert not (runtime_dir / "pyproject.toml").exists()
    assert not (runtime_dir / "uv.lock").exists()

    version_file = runtime_dir / "VERSION"
    assert version_file.exists()
    assert "source_commit" in version_file.read_text(encoding="utf-8")
