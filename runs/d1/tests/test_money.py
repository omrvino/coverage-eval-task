from decimal import Decimal

import pytest

from tally import money, split


def test_money_accepts_int_str_decimal():
    assert money(3) == Decimal("3.00")
    assert money("3.5") == Decimal("3.50")
    assert money(Decimal("3.25")) == Decimal("3.25")


def test_money_rejects_float():
    with pytest.raises(TypeError):
        money(1.5)


def test_money_rounds_to_the_cent():
    assert money("2.665") == Decimal("2.67")
    assert money("2.675") == Decimal("2.68")


def test_split_even():
    assert split("10.00", [1, 1]) == [Decimal("5.00"), Decimal("5.00")]
