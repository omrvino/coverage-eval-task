from decimal import ROUND_HALF_EVEN, Decimal, InvalidOperation
from fractions import Fraction

CENT = Decimal("0.01")


def money(value):
    """Return ``value`` as a Decimal rounded to whole cents."""
    if isinstance(value, (bool, float)) or not isinstance(value, (int, str, Decimal)):
        raise TypeError(f"cannot use {type(value).__name__} as money")
    try:
        amount = Decimal(value)
    except InvalidOperation:
        raise ValueError(f"not a number: {value!r}") from None
    if not amount.is_finite():
        raise ValueError(f"not a finite amount: {value!r}")
    return amount.quantize(CENT, rounding=ROUND_HALF_EVEN)


def split(total, weights):
    """Divide ``total`` in proportion to ``weights`` without losing a cent."""
    total = money(total)
    shares = [Fraction(w) for w in weights]
    if any(w < 0 for w in shares):
        raise ValueError("weights must not be negative")
    if sum(shares) == 0:
        raise ValueError("weights must not all be zero")
    cents = int(abs(total) * 100)
    exact = [cents * w / sum(shares) for w in shares]
    parts = [int(e) for e in exact]
    leftover = cents - sum(parts)
    by_remainder = sorted(range(len(parts)), key=lambda i: (-(exact[i] - parts[i]), i))
    for i in by_remainder[:leftover]:
        parts[i] += 1
    sign = -1 if total < 0 else 1
    return [money(sign * Decimal(p) / 100) for p in parts]
