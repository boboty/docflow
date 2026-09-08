"""Reference Catalog data model.

The Catalog is a small, YAML-backed store of long-lived, reusable business
facts (organizations and their contacts/addresses, products, template
paths) - it is deliberately NOT a system of record, NOT an ERP, and holds
no transaction facts (quantities, prices, dates, document numbers). This
module is intentionally decoupled from ``docflow.domain`` /
``docflow.rules`` / ``docflow.templates`` - the Catalog knows nothing about
DocumentFactPack, money derivation, or xlsx rendering. It only answers
"what do we already know about this name" for an agent to consult before
asking the user, or before building a DocumentFactPack by hand.
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True, slots=True)
class Contact:
    id: str
    name: str
    label: str | None = None
    phone: str | None = None
    default: bool = False


@dataclass(frozen=True, slots=True)
class Address:
    id: str
    address: str
    label: str | None = None
    default: bool = False


@dataclass(frozen=True, slots=True)
class Seal:
    path: str


@dataclass(frozen=True, slots=True)
class Organization:
    id: str
    name: str
    roles: tuple[str, ...] = ()
    aliases: tuple[str, ...] = ()
    contacts: tuple[Contact, ...] = ()
    addresses: tuple[Address, ...] = ()
    seal: Seal | None = None


@dataclass(frozen=True, slots=True)
class Product:
    id: str
    name: str
    specification: str | None = None
    unit: str | None = None
    aliases: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class TemplateEntry:
    key: str
    document_type: str
    path: str


@dataclass(frozen=True, slots=True)
class Catalog:
    organizations: dict[str, Organization] = field(default_factory=dict)
    products: dict[str, Product] = field(default_factory=dict)
    templates: dict[str, TemplateEntry] = field(default_factory=dict)
