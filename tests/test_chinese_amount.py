from decimal import Decimal

from docflow.rules.chinese_amount import to_rmb_capital


def test_known_real_world_total():
    # This total (3952.00) is a real subtotal figure this project was built
    # against; the expected capitalization was cross-checked against the
    # real template it came from.
    assert to_rmb_capital(Decimal("3952.00")) == "叁仟玖佰伍拾贰元整"


def test_zero():
    assert to_rmb_capital(Decimal("0.00")) == "零元整"


def test_yuan_only_no_fraction():
    assert to_rmb_capital(Decimal("100.00")) == "壹佰元整"


def test_with_jiao_and_fen():
    assert to_rmb_capital(Decimal("100.56")) == "壹佰元伍角陆分"


def test_with_zero_jiao_nonzero_fen():
    assert to_rmb_capital(Decimal("100.06")) == "壹佰元零陆分"


def test_negative_rejected():
    import pytest

    with pytest.raises(ValueError):
        to_rmb_capital(Decimal("-1.00"))
