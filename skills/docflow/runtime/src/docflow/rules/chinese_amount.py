"""RMB capitalization (人民币大写) for amounts already rounded to 2dp."""
from __future__ import annotations

from decimal import Decimal

_DIGITS = "零壹贰叁肆伍陆柒捌玖"
_SMALL_UNITS = ["", "拾", "佰", "仟"]
_BIG_UNITS = ["", "万", "亿", "万亿"]


def _group_to_words(group: str) -> str:
    """Convert a <=4 digit string (no leading/trailing group separators) to words."""
    result = []
    zero_pending = False
    for i, ch in enumerate(group):
        digit = int(ch)
        place = len(group) - i - 1
        if digit == 0:
            zero_pending = True
            continue
        if zero_pending and result:
            result.append(_DIGITS[0])
        zero_pending = False
        result.append(_DIGITS[digit] + _SMALL_UNITS[place])
    return "".join(result)


def _integer_to_words(n: int) -> str:
    if n == 0:
        return _DIGITS[0]
    groups: list[str] = []
    while n > 0:
        groups.append(str(n % 10000).zfill(4))
        n //= 10000
    groups.reverse()

    words = ""
    prev_group_zero = True
    for idx, group in enumerate(groups):
        unit = _BIG_UNITS[len(groups) - idx - 1]
        group_val = int(group)
        if group_val == 0:
            prev_group_zero = True
            continue
        group_words = _group_to_words(group)
        if not prev_group_zero and group[0] == "0":
            words += _DIGITS[0]
        words += group_words + unit
        prev_group_zero = False
    return words


def to_rmb_capital(amount: Decimal) -> str:
    """Render a non-negative amount (2dp) as Chinese RMB capital text.

    Examples: 3952.00 -> "叁仟玖佰伍拾贰元整"; 100.50 -> "壹佰元伍角整"(角非零)
    """
    if amount < 0:
        raise ValueError("to_rmb_capital does not support negative amounts")

    amount = amount.quantize(Decimal("0.01"))
    yuan = int(amount)
    fen_total = int((amount - yuan) * 100)
    jiao, fen = divmod(fen_total, 10)

    yuan_words = _integer_to_words(yuan) + "元" if yuan > 0 else ""

    if jiao == 0 and fen == 0:
        if not yuan_words:
            return "零元整"
        return yuan_words + "整"

    parts = [yuan_words] if yuan_words else []
    if yuan > 0 and jiao == 0 and fen > 0:
        parts.append("零")
    if jiao > 0:
        parts.append(_DIGITS[jiao] + "角")
    if fen > 0:
        parts.append(_DIGITS[fen] + "分")
    return "".join(parts)
