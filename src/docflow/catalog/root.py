"""Single source of truth for resolving the Catalog root.

Priority: explicit --catalog-root > DOCFLOW_CATALOG_ROOT >
$PWD/.docflow/catalog. Every `docflow catalog *` subcommand must call this
one function - never re-implement the priority order locally.

`$PWD/.docflow/catalog` is a fixed, documented, workspace-local
convention - not filesystem search. This function never walks up to a
parent directory and never looks in `$HOME`; switching `$PWD` (i.e. the
agent's working directory) switches to a completely different, isolated
catalog.
"""
from __future__ import annotations

import os
from pathlib import Path

WORKSPACE_CATALOG_SUBPATH = Path(".docflow") / "catalog"


def resolve_catalog_root(explicit: Path | None = None, cwd: Path | None = None) -> Path:
    if explicit is not None:
        return explicit
    env = os.environ.get("DOCFLOW_CATALOG_ROOT")
    if env:
        return Path(env)
    return (cwd if cwd is not None else Path.cwd()) / WORKSPACE_CATALOG_SUBPATH


def managed_template_root(catalog_root: Path) -> Path:
    """Where imported (workspace-managed) template assets live - always a
    fixed sibling of the catalog root, never independently configurable
    (no new env var, no `--template-root`; see Managed Template Lifecycle
    section 4 - YAGNI). For the default catalog root
    ($PWD/.docflow/catalog) this is $PWD/.docflow/templates.
    """
    return catalog_root.parent / "templates"
