from dataclasses import replace
from decimal import Decimal

from docflow.domain.document import DocumentType, build_projection
from docflow.domain.facts import ShipTo
from docflow.domain.validation import (
    validate_aggregate_consistency,
    validate_cross_document,
    validate_derived_consistency,
    validate_fact_pack,
    validate_source_consistency,
)
from tests.conftest import make_fact_pack, make_line_item


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


def test_negative_gross_amount_fails():
    pack = make_fact_pack()
    bad_item = replace(pack.items[0], gross_amount=Decimal("-1"))
    pack = replace(pack, items=(bad_item,))
    result = validate_fact_pack(pack)
    assert not result.is_valid
    assert any(issue.code == "NEGATIVE_GROSS_AMOUNT" for issue in result.issues)


def test_no_items_fails():
    pack = replace(make_fact_pack(), items=())
    result = validate_fact_pack(pack)
    assert not result.is_valid
    assert any(issue.code == "NO_LINE_ITEMS" for issue in result.issues)


def test_source_consistency_passes_when_unit_price_times_quantity_matches():
    pack = make_fact_pack(item_count=1)  # default fixture is source-consistent
    result = validate_source_consistency(pack)
    assert result.is_valid


def test_source_consistency_detects_mismatch_beyond_tolerance():
    bad_item = make_line_item(1, quantity=2, gross_unit_price="113.00", gross_amount="500.00")
    pack = replace(make_fact_pack(item_count=0), items=(bad_item,))
    result = validate_source_consistency(pack)
    assert not result.is_valid
    assert any(issue.code == "GROSS_UNIT_PRICE_INCONSISTENT" for issue in result.issues)


def test_source_consistency_allows_documented_rounding_tolerance():
    # gross_unit_price*quantity = 226.00; real per-unit rounding noise of a
    # cent or two should not fail the batch.
    item = make_line_item(1, quantity=2, gross_unit_price="113.00", gross_amount="225.99")
    pack = replace(make_fact_pack(item_count=0), items=(item,))
    result = validate_source_consistency(pack)
    assert result.is_valid


def test_aggregate_consistency_skipped_when_no_source_total():
    pack = make_fact_pack(item_count=2)
    assert pack.gross_total is None
    result = validate_aggregate_consistency(pack)
    assert result.is_valid


def test_aggregate_consistency_passes_when_matching_source_total():
    pack = make_fact_pack(item_count=2, gross_total=Decimal("452.00"))  # 2 * 226.00
    result = validate_aggregate_consistency(pack)
    assert result.is_valid


def test_aggregate_consistency_detects_mismatch():
    pack = make_fact_pack(item_count=2, gross_total=Decimal("999.00"))
    result = validate_aggregate_consistency(pack)
    assert not result.is_valid
    assert any(issue.code == "SOURCE_TOTAL_MISMATCH" for issue in result.issues)


def test_derived_consistency_passes_for_engine_derived_projection():
    pack = make_fact_pack(item_count=3)
    projection = build_projection(pack, DocumentType.PROCUREMENT_CONTRACT_V1)
    result = validate_derived_consistency(projection)
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
