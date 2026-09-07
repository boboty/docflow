from dataclasses import replace
from decimal import Decimal

from docflow.domain.document import DocumentType, build_projection
from docflow.domain.facts import ShipTo
from docflow.domain.validation import (
    validate_amounts,
    validate_cross_document,
    validate_fact_pack,
)
from tests.conftest import make_fact_pack


def test_valid_fact_pack_has_no_issues():
    pack = make_fact_pack()
    result = validate_fact_pack(pack)
    assert result.is_valid


def test_missing_required_field_fails():
    pack = replace(make_fact_pack(), buyer="")
    result = validate_fact_pack(pack)
    assert not result.is_valid
    assert any(issue.code == "REQUIRED_FIELD_MISSING" for issue in result.issues)


def test_missing_ship_to_company_fails():
    pack = make_fact_pack()
    pack = replace(pack, ship_to=ShipTo(company="", contact="c", phone="p", address="a"))
    result = validate_fact_pack(pack)
    assert not result.is_valid
    assert any(issue.field == "ship_to.company" for issue in result.issues)


def test_zero_quantity_fails():
    pack = make_fact_pack()
    bad_item = replace(pack.items[0], quantity=Decimal("0"))
    pack = replace(pack, items=(bad_item,))
    result = validate_fact_pack(pack)
    assert not result.is_valid
    assert any(issue.code == "QUANTITY_NOT_POSITIVE" for issue in result.issues)


def test_no_items_fails():
    pack = replace(make_fact_pack(), items=())
    result = validate_fact_pack(pack)
    assert not result.is_valid
    assert any(issue.code == "NO_LINE_ITEMS" for issue in result.issues)


def test_amount_validation_passes_for_engine_derived_projection():
    pack = make_fact_pack(item_count=3)
    projection = build_projection(pack, DocumentType.PROCUREMENT_CONTRACT_V1)
    result = validate_amounts(projection)
    assert result.is_valid


def test_cross_document_validation_passes_for_same_fact_pack():
    pack = make_fact_pack(item_count=3)
    contract = build_projection(pack, DocumentType.PROCUREMENT_CONTRACT_V1)
    delivery = build_projection(pack, DocumentType.DELIVERY_NOTE_V1)
    result = validate_cross_document(contract, delivery)
    assert result.is_valid


def test_cross_document_validation_detects_item_mismatch():
    pack = make_fact_pack(item_count=3)
    other_pack = make_fact_pack(item_count=2)
    contract = build_projection(pack, DocumentType.PROCUREMENT_CONTRACT_V1)
    delivery = build_projection(other_pack, DocumentType.DELIVERY_NOTE_V1)
    result = validate_cross_document(contract, delivery)
    assert not result.is_valid
    assert any(issue.code == "CROSS_DOCUMENT_ITEMS_MISMATCH" for issue in result.issues)
