"""Deterministic Catalog resolution.

Every function here returns a plain, JSON-serializable dict with a
`status` of exactly one of RESOLVED / NOT_FOUND / AMBIGUOUS - matching the
CLI's output contract 1:1, so `docflow catalog resolve` can just
`json.dumps()` the return value. No fuzzy matching, no ranking, no "best
guess": a query either resolves to exactly one entity or it doesn't.
"""
from __future__ import annotations

from typing import Any, Sequence

from docflow.catalog.loader import normalize
from docflow.catalog.models import Address, Catalog, Contact, Organization, Product


def _contact_dict(contact: Contact) -> dict[str, Any]:
    return {"id": contact.id, "label": contact.label, "name": contact.name, "phone": contact.phone}


def _address_dict(address: Address) -> dict[str, Any]:
    return {"id": address.id, "label": address.label, "address": address.address}


def _select_entry(
    entries: Sequence[Contact | Address], explicit_query: str | None
) -> tuple[str, Contact | Address | None, tuple[Contact | Address, ...]]:
    """Selection priority (Reference Catalog v0 section 6):
    explicit query > exact id/label match > catalog default > sole
    candidate > AMBIGUOUS. Returns (status, selected_or_None, candidates).
    RESOLVED with a None entry means "nothing to resolve, and that's fine"
    (the organization simply has no contacts/addresses at all).
    """
    if not entries:
        return "RESOLVED", None, ()

    if explicit_query:
        nq = normalize(explicit_query)
        matches = [e for e in entries if normalize(e.id) == nq or (e.label and normalize(e.label) == nq)]
        if not matches:
            return "NOT_FOUND", None, ()
        if len(matches) > 1:
            return "AMBIGUOUS", None, tuple(matches)
        return "RESOLVED", matches[0], ()

    defaults = [e for e in entries if e.default]
    if len(defaults) == 1:
        return "RESOLVED", defaults[0], ()
    if len(defaults) > 1:
        # A validated catalog can't reach this (loader rejects duplicate
        # defaults), but resolve() must not assume its input was validated.
        return "AMBIGUOUS", None, tuple(defaults)

    if len(entries) == 1:
        return "RESOLVED", entries[0], ()

    return "AMBIGUOUS", None, tuple(entries)


def _match_organizations(catalog: Catalog, query: str) -> list[Organization]:
    nq = normalize(query)
    matches = []
    for org in catalog.organizations.values():
        keys = {normalize(org.id), normalize(org.name), *(normalize(a) for a in org.aliases)}
        if nq in keys:
            matches.append(org)
    return matches


def resolve_organization(
    catalog: Catalog,
    query: str,
    role: str | None = None,
    contact_query: str | None = None,
    address_query: str | None = None,
) -> dict[str, Any]:
    candidates = _match_organizations(catalog, query)
    if role:
        candidates = [org for org in candidates if role in org.roles]

    if not candidates:
        return {"status": "NOT_FOUND", "kind": "organization", "query": query, "role": role, "field": "organization"}
    if len(candidates) > 1:
        return {
            "status": "AMBIGUOUS",
            "kind": "organization",
            "query": query,
            "role": role,
            "field": "organization",
            "candidates": [{"id": o.id, "name": o.name, "roles": list(o.roles)} for o in candidates],
        }
    org = candidates[0]

    contact_status, contact, contact_candidates = _select_entry(org.contacts, contact_query)
    if contact_status != "RESOLVED":
        return {
            "status": contact_status,
            "kind": "organization",
            "query": query,
            "role": role,
            "field": "contact",
            "organization": {"id": org.id, "name": org.name},
            "candidates": [_contact_dict(c) for c in contact_candidates],
        }

    address_status, address, address_candidates = _select_entry(org.addresses, address_query)
    if address_status != "RESOLVED":
        return {
            "status": address_status,
            "kind": "organization",
            "query": query,
            "role": role,
            "field": "address",
            "organization": {"id": org.id, "name": org.name},
            "candidates": [_address_dict(a) for a in address_candidates],
        }

    return {
        "status": "RESOLVED",
        "kind": "organization",
        "id": org.id,
        "name": org.name,
        "roles": list(org.roles),
        "role": role,
        "contact": _contact_dict(contact) if contact else None,
        "address": _address_dict(address) if address else None,
    }


def resolve_product(catalog: Catalog, query: str) -> dict[str, Any]:
    nq = normalize(query)
    candidates: list[Product] = []
    for product in catalog.products.values():
        keys = {normalize(product.id), normalize(product.name), *(normalize(a) for a in product.aliases)}
        if nq in keys:
            candidates.append(product)

    if not candidates:
        return {"status": "NOT_FOUND", "kind": "product", "query": query}
    if len(candidates) > 1:
        return {
            "status": "AMBIGUOUS",
            "kind": "product",
            "query": query,
            "candidates": [{"id": p.id, "name": p.name} for p in candidates],
        }
    product = candidates[0]
    return {
        "status": "RESOLVED",
        "kind": "product",
        "id": product.id,
        "name": product.name,
        "specification": product.specification,
        "unit": product.unit,
    }


def resolve_template(catalog: Catalog, query: str) -> dict[str, Any]:
    nq = normalize(query)
    candidates = [t for t in catalog.templates.values() if normalize(t.key) == nq]

    if not candidates:
        return {"status": "NOT_FOUND", "kind": "template", "query": query}
    if len(candidates) > 1:
        return {
            "status": "AMBIGUOUS",
            "kind": "template",
            "query": query,
            "candidates": [{"key": t.key, "document_type": t.document_type} for t in candidates],
        }
    template = candidates[0]
    return {
        "status": "RESOLVED",
        "kind": "template",
        "key": template.key,
        "document_type": template.document_type,
        "path": template.path,
    }
