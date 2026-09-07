from decimal import Decimal

from docflow.domain.facts import LineItemFacts
from docflow.rules.money import (
    compute_line_item_amounts,
    compute_totals,
    source_consistency_tolerance,
)


def _item(quantity: str, gross_unit_price: str, gross_amount: str, tax_rate: str = "0.13") -> LineItemFacts:
    return LineItemFacts(
        sku="SKU-1",
        product_name="产品",
        specification="型号SKU-1",
        quantity=Decimal(quantity),
        unit="件",
        gross_unit_price=Decimal(gross_unit_price),
        gross_amount=Decimal(gross_amount),
        tax_rate=Decimal(tax_rate),
    )


def test_gross_amount_is_the_source_not_unit_price_times_quantity():
    # 113.00 * 2 == 226.00 here, but the point of gross pricing is that
    # gross_amount is taken as given, never recomputed from unit price.
    amounts = compute_line_item_amounts(_item("2", "113.00", "226.00"))
    assert amounts.gross_amount == Decimal("226.00")
    assert amounts.net_amount == Decimal("200.00")
    assert amounts.tax_amount == Decimal("26.00")
    assert amounts.net_unit_price == Decimal("100.00")


def test_real_world_regression_qty42_gross_unit_price_49():
    """The exact real-sample line this repair round targets:
    quantity=42, gross_unit_price=49, gross_amount=2058, tax_rate=13%
    -> net_unit_price=43.36, net_amount=1821.24, tax_amount=236.76.
    Multiplying 43.36 * 42 = 1821.12, which is NOT 1821.24 - this test
    guards against ever deriving net_amount from unit price again.
    """
    amounts = compute_line_item_amounts(_item("42", "49", "2058", "0.13"))
    assert amounts.net_unit_price == Decimal("43.36")
    assert amounts.net_amount == Decimal("1821.24")
    assert amounts.tax_amount == Decimal("236.76")
    assert amounts.gross_amount == Decimal("2058.00")
    assert Decimal("43.36") * Decimal("42") != amounts.net_amount


def test_gross_equals_net_plus_tax_by_construction():
    amounts = compute_line_item_amounts(_item("7", "18.05", "126.35"))
    assert amounts.gross_amount == amounts.net_amount + amounts.tax_amount


def test_compute_totals_sums_all_items():
    items = [
        compute_line_item_amounts(_item("2", "113.00", "226.00")),
        compute_line_item_amounts(_item("1", "56.50", "56.50")),
    ]
    totals = compute_totals(items)
    assert totals.gross_total == Decimal("282.50")
    assert totals.net_total == Decimal("200.00") + Decimal("50.00")
    assert totals.tax_total == totals.gross_total - totals.net_total


def test_source_consistency_tolerance_scales_with_quantity():
    assert source_consistency_tolerance(Decimal("1")) == Decimal("0.01")
    assert source_consistency_tolerance(Decimal("42")) == Decimal("0.21")
