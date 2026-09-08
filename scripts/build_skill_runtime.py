#!/usr/bin/env python3
"""Sync src/docflow (source of truth) into skills/docflow/runtime/src/docflow
(the published, Skill-bundled runtime artifact).

This is a developer-run tool, not something the Skill or an agent ever
invokes. There is exactly one place DocFlow's engine code is written:
`src/docflow`. This script deterministically copies it - unmodified,
minus dev-only cruft (`__pycache__`, `.pyc`, `.pytest_cache`) - into the
Skill's `runtime/src/docflow`, so a copy of `skills/docflow/` is a
complete, runnable DocFlow install with no dependency on this repo.

The runtime is executed as a PEP 723 script (`run.py`, resolved via
`uv run`) - there is deliberately no `pyproject.toml`/setuptools build
and no editable install of a `docflow` package: `run.py` puts this
runtime's own `src/` on `sys.path` and calls `docflow.cli.main()`
directly, so `uv` only ever needs to resolve run.py's own declared
dependencies (openpyxl, PyYAML), never build or install anything of ours.

Usage:
    python3 scripts/build_skill_runtime.py
"""
from __future__ import annotations

import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SOURCE_PACKAGE = REPO_ROOT / "src" / "docflow"
SKILL_RUNTIME_DIR = REPO_ROOT / "skills" / "docflow" / "runtime"
DEST_PACKAGE = SKILL_RUNTIME_DIR / "src" / "docflow"
RUN_PY = SKILL_RUNTIME_DIR / "run.py"

_IGNORE = shutil.ignore_patterns("__pycache__", "*.pyc", "*.pyo", ".pytest_cache")

# Obsolete artifacts from the pre-PEP-723 (`uv run --project`) runtime
# layout - removed on sync so a stale copy never lingers and confuses
# anyone about which execution mechanism is in effect.
_OBSOLETE_PATHS = ("pyproject.toml", "uv.lock", ".venv")

_RUN_PY = '''\
#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = [
#   "openpyxl>=3.1",
#   "PyYAML>=6.0",
# ]
# ///
"""DocFlow Skill-bundled runtime entry point.

This is a PEP 723 script: `uv run run.py ...` resolves ONLY the
dependencies declared in the block above, into an isolated environment
managed entirely by uv's own cache - it never builds or installs a
`docflow` package (no pyproject.toml here, no setuptools, no editable
install). `docflow` itself is used directly from this runtime's own
`src/` via sys.path, exactly as shipped: the runtime is source, not a
build artifact.

Never invoked directly by a human or agent - always through
scripts/docflow (this Skill's launcher), which is what finds `uv` and
execs this file with the CLI arguments appended.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

from docflow.cli import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main())
'''


def _git(*args: str) -> str | None:
    try:
        result = subprocess.run(
            ["git", *args], cwd=REPO_ROOT, capture_output=True, text=True, timeout=10
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if result.returncode != 0:
        return None
    return result.stdout.strip()


def _source_commit_info() -> tuple[str, bool]:
    commit = _git("rev-parse", "HEAD") or "unknown"
    status = _git("status", "--porcelain", "--", str(SOURCE_PACKAGE))
    dirty = bool(status) if status is not None else True  # unknown git state -> assume dirty
    return commit, dirty


def _remove_obsolete_artifacts() -> None:
    for name in _OBSOLETE_PATHS:
        path = SKILL_RUNTIME_DIR / name
        if path.is_dir():
            shutil.rmtree(path)
        elif path.exists():
            path.unlink()


def _lock_run_py() -> bool:
    uv = shutil.which("uv")
    if uv is None:
        print("WARNING: uv not found on PATH - skipping run.py.lock generation", file=sys.stderr)
        return False
    result = subprocess.run(
        [uv, "lock", "--script", str(RUN_PY)], cwd=str(SKILL_RUNTIME_DIR), capture_output=True, text=True
    )
    if result.returncode != 0:
        print(result.stdout, file=sys.stderr)
        print(result.stderr, file=sys.stderr)
        raise SystemExit("uv lock --script run.py failed - see output above")
    return True


def sync() -> None:
    if not SOURCE_PACKAGE.is_dir():
        raise SystemExit(f"source package not found: {SOURCE_PACKAGE}")

    if DEST_PACKAGE.exists():
        shutil.rmtree(DEST_PACKAGE)
    shutil.copytree(SOURCE_PACKAGE, DEST_PACKAGE, ignore=_IGNORE)

    _remove_obsolete_artifacts()

    RUN_PY.write_text(_RUN_PY, encoding="utf-8")
    RUN_PY.chmod(0o755)

    locked = _lock_run_py()

    commit, dirty = _source_commit_info()
    built_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    version_lines = [
        "docflow-skill-runtime",
        f"source_commit: {commit}{' (dirty: uncommitted changes under src/docflow)' if dirty else ''}",
        f"built_at: {built_at}",
    ]
    (SKILL_RUNTIME_DIR / "VERSION").write_text("\n".join(version_lines) + "\n", encoding="utf-8")

    copied_files = sorted(p.relative_to(DEST_PACKAGE) for p in DEST_PACKAGE.rglob("*") if p.is_file())
    print(f"synced {len(copied_files)} files: {SOURCE_PACKAGE} -> {DEST_PACKAGE}")
    print(f"wrote {RUN_PY} (PEP 723 script, no pyproject.toml/setuptools)")
    print(f"wrote {RUN_PY}.lock" if locked else "run.py.lock NOT regenerated (uv unavailable)")
    print(f"wrote {SKILL_RUNTIME_DIR / 'VERSION'} (source_commit={commit}, dirty={dirty})")


if __name__ == "__main__":
    sys.exit(sync() or 0)
