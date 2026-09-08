#!/usr/bin/env python3
"""Sync src/docflow (source of truth) into skills/docflow/runtime/src/docflow
(the published, Skill-bundled runtime artifact).

This is a developer-run tool, not something the Skill or an agent ever
invokes. There is exactly one place DocFlow's engine code is written:
`src/docflow`. This script deterministically copies it - unmodified,
minus dev-only cruft (`__pycache__`, `.pyc`, `.pytest_cache`) - into the
Skill's `runtime/src/docflow`, so a copy of `skills/docflow/` is a
complete, runnable DocFlow install with no dependency on this repo.

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

_IGNORE = shutil.ignore_patterns("__pycache__", "*.pyc", "*.pyo", ".pytest_cache")

_RUNTIME_PYPROJECT = """\
[project]
name = "docflow"
version = "0.1.0"
description = "DocFlow deterministic runtime, bundled with the docflow Skill."
requires-python = ">=3.11"
dependencies = [
    "openpyxl>=3.1",
    "PyYAML>=6.0",
]

[project.scripts]
docflow = "docflow.cli:main"

[build-system]
requires = ["setuptools>=68", "wheel"]
build-backend = "setuptools.build_meta"

[tool.setuptools.packages.find]
where = ["src"]

[tool.setuptools.package-data]
"docflow.templates" = ["mappings/*.yaml"]
"""


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


def sync() -> None:
    if not SOURCE_PACKAGE.is_dir():
        raise SystemExit(f"source package not found: {SOURCE_PACKAGE}")

    if DEST_PACKAGE.exists():
        shutil.rmtree(DEST_PACKAGE)
    shutil.copytree(SOURCE_PACKAGE, DEST_PACKAGE, ignore=_IGNORE)

    (SKILL_RUNTIME_DIR / "pyproject.toml").write_text(_RUNTIME_PYPROJECT, encoding="utf-8")

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
    print(f"wrote {SKILL_RUNTIME_DIR / 'pyproject.toml'}")
    print(f"wrote {SKILL_RUNTIME_DIR / 'VERSION'} (source_commit={commit}, dirty={dirty})")


if __name__ == "__main__":
    sys.exit(sync() or 0)
