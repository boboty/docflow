"""Registry mapping a DocumentType to its (hand-authored) TemplateDefinition."""
from __future__ import annotations

from pathlib import Path

from docflow.domain.document import DocumentType
from docflow.templates.definition import TemplateDefinition, load_template_definition

DEFAULT_MAPPING_DIR = Path(__file__).parent / "mappings"


class TemplateRegistry:
    def __init__(self, mapping_dir: Path = DEFAULT_MAPPING_DIR):
        self._mapping_dir = mapping_dir
        self._cache: dict[DocumentType, TemplateDefinition] = {}

    def get(self, document_type: DocumentType) -> TemplateDefinition:
        if document_type not in self._cache:
            path = self._mapping_dir / f"{document_type.value}.yaml"
            if not path.exists():
                raise FileNotFoundError(f"no template mapping registered for {document_type.value} at {path}")
            self._cache[document_type] = load_template_definition(path)
        return self._cache[document_type]
