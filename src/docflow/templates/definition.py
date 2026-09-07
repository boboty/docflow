"""Template mapping definitions.

A TemplateDefinition is pure configuration: cell coordinates and column
letters. It carries no business logic and no document facts. Template
mapping is hand-authored per template (see templates/mappings/*.yaml) -
there is no visual template designer and none is planned.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml

from docflow.domain.document import DocumentType


class TemplateDefinitionError(Exception):
    pass


@dataclass(frozen=True, slots=True)
class ItemsMapping:
    start_row: int
    end_row: int
    columns: dict[str, str]

    @property
    def capacity(self) -> int:
        return self.end_row - self.start_row + 1


@dataclass(frozen=True, slots=True)
class TemplateDefinition:
    id: str
    format: str
    sheet: str
    header: dict[str, str]
    items: ItemsMapping


def load_template_definition(path: Path) -> TemplateDefinition:
    with path.open("r", encoding="utf-8") as f:
        raw = yaml.safe_load(f)

    try:
        items_raw = raw["items"]
        items = ItemsMapping(
            start_row=int(items_raw["start_row"]),
            end_row=int(items_raw["end_row"]),
            columns=dict(items_raw["columns"]),
        )
        return TemplateDefinition(
            id=raw["id"],
            format=raw["format"],
            sheet=raw["sheet"],
            header=dict(raw.get("header", {})),
            items=items,
        )
    except KeyError as exc:
        raise TemplateDefinitionError(f"malformed template mapping {path}: missing {exc}") from exc


def document_type_from_id(template_id: str) -> DocumentType:
    return DocumentType(template_id)
