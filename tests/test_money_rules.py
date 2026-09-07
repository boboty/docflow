from decimal import Decimal

from docflow.domain.facts import LineItemFacts
from docflow.rules.money import compute_line_item_amounts, compute_totals


def _item(quantity: str, net_unit_price: str, tax_rate: str = "0.13") -> LineItemFacts:
    return LineItemFacts(
        sku="SKU-1",
        product_name="产品",
        specification="型号SKU-1",
        quantity=Decimal(quantity),
        unit="件",
        net_unit_price=Decimal(net_unit_price),
        tax_rate=Decimal(tax_rate),
    )


def test_line_item_amounts_forward_derivation():
    amounts = compute_line_item_amounts(_item("3", "100.00"))
    assert amounts.net_amount == Decimal("300.00")
    assert amounts.tax_amount == Decimal("39.00")
    assert amounts.gross_amount == Decimal("339.00")
    assert amounts.gross_unit_price == Decimal("113.00")


def test_line_item_amounts_round_half_up():
    # net_amount = 10.005 -> rounds to 10.01 (half up), not banker's rounding.
    amounts = compute_line_item_amounts(_item("1", "10.005"))
    assert amounts.net_amount == Decimal("10.01")


def test_gross_equals_net_plus_tax():
    amounts = compute_line_item_amounts(_item("7", "15.93"))
    assert amounts.gross_amount == amounts.net_amount + amounts.tax_amount


def test_compute_totals_sums_all_items():
    items = [
        compute_line_item_amounts(_item("2", "100.00")),
        compute_line_item_amounts(_item("1", "50.00")),
    ]
    totals = compute_totals(items)
    assert totals.net_total == Decimal("250.00")
    assert totals.tax_total == Decimal("32.50")
    assert totals.gross_total == Decimal("282.50")
