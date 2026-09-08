from datetime import date

from docflow.domain.document import chinese_month_day


def test_chinese_month_day_single_digits():
    assert chinese_month_day(date(2026, 1, 2)) == "1月2日"


def test_chinese_month_day_no_leading_zero_on_month():
    assert chinese_month_day(date(2026, 9, 9)) == "9月9日"


def test_chinese_month_day_double_digit_day():
    assert chinese_month_day(date(2026, 12, 31)) == "12月31日"


def test_chinese_month_day_omits_year():
    assert "2026" not in chinese_month_day(date(2026, 9, 9))
