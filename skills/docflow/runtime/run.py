#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = [
#   "openpyxl>=3.1",
#   "Pillow>=10.0",
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
