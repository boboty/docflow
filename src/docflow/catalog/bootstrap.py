"""Idempotent Catalog bootstrap: `docflow catalog init`.

Only ever CREATES a file that's missing, with an empty section. It never
touches, rewrites, or "repairs" a file that already exists - even if that
existing file turns out to be malformed. User data always wins over a
"successful init": if a pre-existing file is invalid, init must fail
(propagating CatalogError) rather than overwrite it to make validation
pass.
"""
from __future__ import annotations

from pathlib import Path

import yaml

from docflow.catalog.loader import load_catalog

_EMPTY_SECTIONS: dict[str, tuple[str, dict]] = {
    "organizations.yaml": ("organizations", {}),
    "products.yaml": ("products", {}),
    "templates.yaml": ("templates", {}),
}


def init_catalog(root: Path) -> None:
    root.mkdir(parents=True, exist_ok=True)

    for filename, (top_key, empty_value) in _EMPTY_SECTIONS.items():
        path = root / filename
        if path.exists():
            continue  # never overwrite existing data, even if it's empty/trivial
        with path.open("w", encoding="utf-8") as f:
            yaml.safe_dump({top_key: empty_value}, f, allow_unicode=True, sort_keys=False)

    # Validate whatever exists now (freshly created empty files and/or
    # untouched pre-existing ones). Raises CatalogError if pre-existing
    # data is malformed - init does not attempt to fix or overwrite it.
    load_catalog(root)
