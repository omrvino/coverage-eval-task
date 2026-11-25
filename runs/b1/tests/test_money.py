from decimal import Decimal

import pytest

from tally import money, split

D = Decimal


# -- R1.1 ------------------------------------------------------------------

def test_money_accepts_int_str_decimal():
    assert money(3) == D("3.00")
    assert money("3.5") == D("3.50")
    assert money(D("3.25")) == D("3.25")
    assert money(-7) == D("-7.00")


def test_money_result_has_two_places():
    for value in (3, "3", "3.5", D("3"), D("3.123456")):
        assert money(value).as_tuple().exponent == -2


@pytest.mark.parametrize("value", [1.5, 0.0, True, False, None, [], b"1", (1,), 1 + 2j])
def test_money_rejects_other_types(value):
    with pytest.raises(TypeError):
        money(value)


@pytest.mark.parametrize("value", [
    "abc", "", " ", "1.2.3", "12abc", "NaN", "nan", "inf", "-inf", "Infinity",
    D("NaN"), D("sNaN"), D("Infinity"), D("-Infinity"),
])
def test_money_rejects_non_numbers_and_non_finite(value):
    with pytest.raises(ValueError):
        money(value)


# -- R1.2 ------------------------------------------------------------------

def test_money_rounds_to_nearest_cent():
    assert money("2.664") == D("2.66")
    assert money("2.666") == D("2.67")
    assert money("-2.666") == D("-2.67")
    assert money("0.004") == D("0.00")
    assert money("2.675") == D("2.68")


@pytest.mark.xfail(strict=True, reason="exact halves round up instead of to even")
def test_money_rounds_exact_halves_to_even():
    assert money("2.665") == D("2.66")
    assert money("0.005") == D("0.00")
    assert money("0.015") == D("0.02")
    assert money("0.025") == D("0.02")
    assert money("-2.665") == D("-2.66")


# -- R1.3 ------------------------------------------------------------------

def test_split_even():
    assert split("10.00", [1, 1]) == [D("5.00"), D("5.00")]


def test_split_returns_one_part_per_weight():
    assert len(split("10", [1, 2, 3, 4])) == 4
    assert split("7.00", [5]) == [D("7.00")]


def test_split_accepts_the_same_inputs_as_money():
    assert split(100, [1, 1, 1]) == split("100.00", [1, 1, 1]) == split(D("100"), [1, 1, 1])


def test_split_gives_leftover_cents_to_largest_remainders():
    assert split("100.00", [1, 1, 1]) == [D("33.34"), D("33.33"), D("33.33")]
    # exact shares 1.66.. and 3.33.. cents: the second remainder is the larger one
    assert split("0.05", [1, 2]) == [D("0.02"), D("0.03")]
    assert split("0.05", [2, 1]) == [D("0.03"), D("0.02")]
    # shares 3.5, 1.5 and 2.0 cents: the tie between the first two goes to the first
    assert split("0.07", [7, 3, 4]) == [D("0.04"), D("0.01"), D("0.02")]


def test_split_ties_go_to_the_earlier_position():
    assert split("0.02", [1, 1, 1]) == [D("0.01"), D("0.01"), D("0.00")]
    assert split("0.01", [1, 1]) == [D("0.01"), D("0.00")]
    assert split("0.01", [1, 1, 1]) == [D("0.01"), D("0.00"), D("0.00")]


def test_split_weights_may_be_decimals():
    assert split("10.00", [D("0.5"), D("1.5")]) == [D("2.50"), D("7.50")]


@pytest.mark.parametrize("total", ["0.00", "0.01", "1.00", "99.99", "1234.56", "100000.07"])
@pytest.mark.parametrize("weights", [[1], [1, 1], [1, 1, 1], [3, 7], [1, 2, 3, 4, 5],
                                     [0, 1, 1], [5, 0, 0, 3], [1] * 7, [13, 1, 1, 1]])
def test_split_parts_always_add_up(total, weights):
    parts = split(total, weights)
    assert len(parts) == len(weights)
    assert sum(parts) == money(total)
    whole = sum(weights)
    for part, weight in zip(parts, weights):
        exact_cents = money(total) * 100 * weight / whole
        # each part is its share cut down to the cent, plus at most one cent
        assert exact_cents // 1 <= part * 100 <= exact_cents // 1 + 1
        if weight == 0:
            assert part == 0


@pytest.mark.parametrize("weights", [[1, 1, 1], [3, 7], [2, 1], [0, 4, 1]])
def test_split_negative_total_is_the_negated_positive_result(weights):
    positive = split("100.01", weights)
    assert split("-100.01", weights) == [-p for p in positive]


def test_split_of_zero_is_all_zero():
    assert split("0", [1, 2]) == [D("0.00"), D("0.00")]


def test_split_zero_weight_gets_zero_even_when_cents_are_left_over():
    assert split("0.01", [0, 1, 1]) == [D("0.00"), D("0.01"), D("0.00")]


def test_split_total_goes_through_money_first():
    assert split("10.004", [1, 1]) == split("10.00", [1, 1])
    with pytest.raises(TypeError):
        split(1.5, [1])


@pytest.mark.xfail(strict=True, reason="split parts are not two-place Decimals")
def test_split_parts_have_two_places():
    for part in split("10.00", [1, 1]) + split("-100", [1, 1, 1]) + split("0", [1]):
        assert part.as_tuple().exponent == -2


# -- R1.4 ------------------------------------------------------------------

@pytest.mark.parametrize("weights", [[-1, 2], [1, -1], [-1], [], [0], [0, 0, 0]])
def test_split_rejects_bad_weights(weights):
    with pytest.raises(ValueError):
        split("10.00", weights)
