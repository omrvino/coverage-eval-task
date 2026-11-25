from decimal import Decimal as D

import pytest

from tally import money, split


@pytest.mark.parametrize("given, expected", [(3, "3.00"), ("3.5", "3.50"), (D("3.25"), "3.25"), ("2.675", "2.68"), ("-2.675", "-2.68")])
def test_money_accepts_and_rounds(given, expected):
    assert str(money(given)) == expected


@pytest.mark.xfail(strict=True, reason="R1.2: rounds half up")
def test_money_rounds_half_to_even():
    assert money("2.665") == D("2.66")


@pytest.mark.parametrize("bad", [1.5, True, False, None, [1], b"1"])
def test_money_wrong_type(bad):
    with pytest.raises(TypeError):
        money(bad)


@pytest.mark.parametrize("bad", ["abc", "", "NaN", "Infinity", "-Infinity", D("NaN"), D("Infinity")])
def test_money_not_a_number(bad):
    with pytest.raises(ValueError):
        money(bad)


@pytest.mark.parametrize("total, weights, expected", [
    ("10.00", [1, 1], ["5.00", "5.00"]),
    ("10.00", [1, 1, 1], ["3.34", "3.33", "3.33"]),
    ("0.02", [1, 1, 1], ["0.01", "0.01", "0.00"]),
    ("1.00", [1, 1, 4], ["0.17", "0.17", "0.66"]),
    ("0.05", [1, 2, 4], ["0.01", "0.01", "0.03"]),
    ("-10.00", [1, 1, 1], ["-3.34", "-3.33", "-3.33"]),
    ("0.01", [0, 1, 1], ["0.00", "0.01", "0.00"]),
    ("5.00", [0, 3], ["0.00", "5.00"]),
    ("0.00", [1, 2], ["0.00", "0.00"]),
])
def test_split(total, weights, expected):
    parts = split(total, weights)
    assert parts == [D(e) for e in expected]
    assert sum(parts) == D(total)


@pytest.mark.parametrize("weights", [[], [0, 0], [1, -1, 3], [-1, 5]])
def test_split_bad_weights(weights):
    with pytest.raises(ValueError):
        split("1.00", weights)
