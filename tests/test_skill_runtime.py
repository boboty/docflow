"""Integration tests for the Skill-bundled, self-contained DocFlow runtime
(skills/docflow/{scripts/docflow, runtime/}).

These spawn real subprocesses (the actual launcher, actual `uv`) rather
than mocking anything - the whole point of this runtime is that it works
with zero dependency on this repo's dev environment, and that can only be
verified by actually running it that way. Requires `uv` to be available
on this machine (skipped otherwise, since that's exactly what a real
WorkBuddy-style environment needs too).
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
SKILL_DIR = REPO_ROOT / "skills" / "docflow"
LAUNCHER = SKILL_DIR / "scripts" / "docflow"

_UV_ON_PATH = shutil.which("uv")
_UV_AT_HOME = Path.home() / ".local" / "bin" / "uv"
_UV_AVAILABLE = bool(_UV_ON_PATH) or _UV_AT_HOME.exists()

pytestmark = pytest.mark.skipif(
    not (LAUNCHER.exists() and _UV_AVAILABLE),
    reason="bundled skill runtime and/or uv not available on this machine",
)


def _run(args: list[str], cwd: Path, env: dict[str, str] | None = None, launcher: Path = LAUNCHER, timeout: int = 180):
    return subprocess.run(
        [str(launcher), *args],
        cwd=str(cwd),
        env=os.environ.copy() if env is None else env,
        capture_output=True,
        text=True,
        timeout=timeout,
    )


def _minimal_env(extra_path: str | None = None, home: str | None = None) -> dict[str, str]:
    path = "/usr/bin:/bin"
    if extra_path:
        path = f"{extra_path}:{path}"
    return {"HOME": home or os.environ["HOME"], "PATH": path}


# 1. launcher runs with no global `docflow` reachable via PATH
def test_launcher_works_without_a_global_docflow_on_path(tmp_path):
    uv_dir = str(Path(_UV_ON_PATH).parent) if _UV_ON_PATH else str(_UV_AT_HOME.parent)
    result = _run(["catalog", "init"], cwd=tmp_path, env=_minimal_env(extra_path=uv_dir))
    assert result.returncode == 0, result.stderr
    assert (tmp_path / ".docflow" / "catalog" / "organizations.yaml").exists()


# 2. PATH has no uv, but $HOME/.local/bin/uv exists
def test_launcher_falls_back_to_home_local_bin_uv(tmp_path):
    if not _UV_AT_HOME.exists():
        pytest.skip("uv is not installed at $HOME/.local/bin/uv on this machine")
    result = _run(["catalog", "validate"], cwd=tmp_path, env=_minimal_env())
    assert result.returncode == 0, result.stderr


# 3. uv completely unavailable -> structured failure, not a crash/traceback
def test_launcher_structured_failure_when_uv_entirely_unavailable(tmp_path):
    fake_home = tmp_path / "fake-home-no-uv"
    fake_home.mkdir()
    result = _run(["catalog", "validate"], cwd=tmp_path, env=_minimal_env(home=str(fake_home)))
    assert result.returncode == 127
    assert "DOCFLOW_RUNTIME_UNAVAILABLE" in result.stderr
    assert "Traceback" not in result.stderr


# 4. launcher passes through --help
def test_launcher_passes_through_help(tmp_path):
    result = _run(["--help"], cwd=tmp_path)
    assert result.returncode == 0
    assert "usage: docflow" in result.stdout


# 5. launcher passes through DocFlow's own exit code unmodified
def test_launcher_passes_through_exit_code(tmp_path):
    batch = tmp_path / "batch.json"
    batch.write_text("[]", encoding="utf-8")
    result = _run([
        "generate",
        "--input", str(batch),
        "--contract-template", str(tmp_path / "missing-contract.xlsx"),
        "--delivery-template", str(tmp_path / "missing-delivery.xlsx"),
        "--output", str(tmp_path / "out"),
    ], cwd=tmp_path)
    assert result.returncode == 2  # template preflight failure
    assert "TEMPLATE PREFLIGHT FAILED" in result.stderr


# 6-9. catalog init / validate / resolve / apply all runnable through the launcher
def test_catalog_init_through_launcher(tmp_path):
    result = _run(["catalog", "init"], cwd=tmp_path)
    assert result.returncode == 0, result.stderr


def test_catalog_validate_through_launcher(tmp_path):
    _run(["catalog", "init"], cwd=tmp_path)
    result = _run(["catalog", "validate"], cwd=tmp_path)
    assert result.returncode == 0, result.stderr


def test_catalog_resolve_through_launcher(tmp_path):
    _run(["catalog", "init"], cwd=tmp_path)
    result = _run(["catalog", "resolve", "--kind", "organization", "--query", "不存在"], cwd=tmp_path)
    assert result.returncode == 1
    assert json.loads(result.stdout)["status"] == "NOT_FOUND"


def test_catalog_apply_through_launcher(tmp_path):
    _run(["catalog", "init"], cwd=tmp_path)
    change_file = tmp_path / "change.json"
    change_file.write_text(json.dumps([{
        "operation": "upsert_organization", "id": "acme", "name": "测试公司", "roles": ["supplier"],
    }]), encoding="utf-8")
    result = _run(["catalog", "apply", "--input", str(change_file)], cwd=tmp_path)
    assert result.returncode == 0, result.stderr

    result = _run(["catalog", "resolve", "--kind", "organization", "--query", "测试公司"], cwd=tmp_path)
    assert json.loads(result.stdout)["status"] == "RESOLVED"


# 10/11. `generate` runs through the bundled runtime and correctly loads
# package data (template mappings) - a real render, not just a syntax check.
def test_generate_through_bundled_runtime_loads_template_mappings(tmp_path):
    sys.path.insert(0, str(REPO_ROOT / "tests"))
    from fixtures.synthetic_templates import build_contract_template, build_delivery_template

    contract_template = build_contract_template(tmp_path / "contract-template.xlsx")
    delivery_template = build_delivery_template(tmp_path / "delivery-template.xlsx")
    batch_path = SKILL_DIR / "examples" / "batch.example.json"
    output_dir = tmp_path / "output"

    result = _run([
        "generate",
        "--input", str(batch_path),
        "--contract-template", str(contract_template),
        "--delivery-template", str(delivery_template),
        "--output", str(output_dir),
    ], cwd=tmp_path)

    assert result.returncode == 0, result.stderr
    manifest = json.loads((output_dir / "manifest.json").read_text(encoding="utf-8"))
    assert all(e["validation_status"] == "PASS" for e in manifest)


# 12/13/14. THE critical independence test: copy ONLY skills/docflow/ to an
# isolated location, with no repo access, no PYTHONPATH, no editable
# install - and confirm it still works, including after switching to a
# second, unrelated empty workspace.
def test_isolated_skill_copy_works_with_zero_repo_dependency(tmp_path):
    isolated_skill = tmp_path / "isolated-skill"
    shutil.copytree(SKILL_DIR, isolated_skill, ignore=shutil.ignore_patterns(".venv"))
    isolated_launcher = isolated_skill / "scripts" / "docflow"

    clean_env = os.environ.copy()
    clean_env.pop("PYTHONPATH", None)

    workspace_a = tmp_path / "workspace-a"
    workspace_a.mkdir()
    result = _run(["--help"], cwd=workspace_a, env=clean_env, launcher=isolated_launcher)
    assert result.returncode == 0, result.stderr

    result = _run(["catalog", "init"], cwd=workspace_a, env=clean_env, launcher=isolated_launcher)
    assert result.returncode == 0, result.stderr

    result = _run(["catalog", "validate"], cwd=workspace_a, env=clean_env, launcher=isolated_launcher)
    assert result.returncode == 0, result.stderr

    # No hardcoded reference to this dev repo leaked into any output.
    assert str(REPO_ROOT) not in result.stdout
    assert str(REPO_ROOT) not in result.stderr

    change_file = workspace_a / "change.json"
    change_file.write_text(json.dumps([{
        "operation": "upsert_organization", "id": "acme", "name": "隔离测试公司", "roles": ["supplier"],
    }]), encoding="utf-8")
    result = _run(["catalog", "apply", "--input", str(change_file)], cwd=workspace_a, env=clean_env, launcher=isolated_launcher)
    assert result.returncode == 0, result.stderr

    # 14. switch cwd to a second, unrelated, empty workspace - isolated.
    workspace_b = tmp_path / "workspace-b"
    workspace_b.mkdir()
    result = _run(["catalog", "resolve", "--kind", "organization", "--query", "隔离测试公司"], cwd=workspace_b, env=clean_env, launcher=isolated_launcher)
    assert json.loads(result.stdout)["status"] == "NOT_FOUND"  # workspace_a's data must not leak here

    result = _run(["catalog", "init"], cwd=workspace_b, env=clean_env, launcher=isolated_launcher)
    assert result.returncode == 0, result.stderr

    # And workspace_a's own data is still resolvable from within workspace_a.
    result = _run(["catalog", "resolve", "--kind", "organization", "--query", "隔离测试公司"], cwd=workspace_a, env=clean_env, launcher=isolated_launcher)
    assert json.loads(result.stdout)["status"] == "RESOLVED"


# 16. no hardcoded reference to this developer's machine/repo path
def test_no_hardcoded_repo_path_in_launcher_or_runtime_source():
    forbidden = str(REPO_ROOT)
    launcher_text = LAUNCHER.read_text(encoding="utf-8")
    assert forbidden not in launcher_text

    for py_file in (SKILL_DIR / "runtime" / "src").rglob("*.py"):
        assert forbidden not in py_file.read_text(encoding="utf-8"), py_file


# 17. SKILL.md no longer *instructs* installing DocFlow globally - the
# banned phrases may still appear in prose telling the agent NOT to do
# them (that's the point), but never inside a runnable ```bash block,
# which is what an agent would actually execute.
def test_skill_doc_no_longer_requires_global_docflow_install():
    import re

    text = (SKILL_DIR / "SKILL.md").read_text(encoding="utf-8")
    bash_blocks = re.findall(r"```bash\n(.*?)```", text, flags=re.DOTALL)
    banned = ["pip install", "uv tool install", "python -m docflow.cli", "command -v docflow"]
    for block in bash_blocks:
        for phrase in banned:
            assert phrase not in block, f"{phrase!r} found in a runnable bash block:\n{block}"

    assert "bundled" in text.lower()
    assert "$DOCFLOW" in text
