"""SPEC section 2: terms and dates."""

from datetime import date

import pytest

from helpers import JAN_5, D, days, issued, make_invoice
from tally import TermsError, parse_terms


def due(terms, on, holidays=()):
    """The due date an invoice gets when it is issued."""
    ledger = issued(make_invoice(terms=terms, on=on), holidays=holidays)
    return ledger.invoices["INV-1"].due


def discount_on(paid_on, *, invoice_date, terms="2/10 NET 30", holidays=()):
    """The discount earned by paying a 100.00 invoice in full on ``paid_on``."""
    ledger = issued(make_invoice(terms=terms, on=invoice_date), holidays=holidays)
    ledger.receive("P1", "acme", "100.00", paid_on)
    return ledger.credit("acme")


# -- R2.1 ------------------------------------------------------------------


@pytest.mark.parametrize("terms, on, expected", [
    ("NET 30", JAN_5, date(2026, 2, 4)),
    ("NET 0", JAN_5, JAN_5),
    ("NET 1", JAN_5, date(2026, 1, 6)),
    ("NET 10", date(2026, 2, 23), date(2026, 3, 5)),  # over a short month end
    ("NET 10", date(2028, 2, 21), date(2028, 3, 2)),  # leap year
    ("NET 45", date(2025, 12, 15), date(2026, 1, 29)),  # over a year end
    ("2/10 NET 30", JAN_5, date(2026, 2, 4)),
])
def test_r2_1_net_days(terms, on, expected):
    assert parse_terms(terms).due_date(on) == expected
    assert due(terms, on) == expected


# -- R2.2 ------------------------------------------------------------------


@pytest.mark.parametrize("on, expected", [
    (date(2026, 3, 1), date(2026, 3, 31)),
    (date(2026, 3, 25), date(2026, 3, 31)),
    (date(2026, 3, 26), date(2026, 4, 30)),
    (date(2026, 3, 27), date(2026, 4, 30)),
    (date(2026, 3, 31), date(2026, 4, 30)),
    (date(2026, 1, 30), date(2026, 3, 2)),  # end of February is a Saturday
    (date(2028, 2, 10), date(2028, 2, 29)),  # leap year
    (date(2026, 11, 26), date(2026, 12, 31)),
    (date(2026, 12, 25), date(2026, 12, 31)),
    (date(2025, 12, 26), date(2026, 2, 2)),  # end of January is a Saturday
    (date(2026, 12, 31), date(2027, 2, 1)),  # end of January is a Sunday
])
def test_r2_2_end_of_month(on, expected):
    assert parse_terms("EOM").due_date(on) == expected
    assert due("EOM", on) == expected


# -- R2.3 ------------------------------------------------------------------


@pytest.mark.parametrize("net, expected", [
    (4, date(2026, 1, 9)),  # Friday stays
    (5, date(2026, 1, 12)),  # Saturday
    (6, date(2026, 1, 12)),  # Sunday
    (7, date(2026, 1, 12)),  # Monday stays
])
def test_r2_3_weekends_move_forward(net, expected):
    assert due(f"NET {net}", JAN_5) == expected


@pytest.mark.parametrize("net, holidays, expected", [
    (2, [date(2026, 1, 7)], date(2026, 1, 8)),
    (2, [date(2026, 1, 7), date(2026, 1, 8)], date(2026, 1, 9)),
    (4, [date(2026, 1, 9)], date(2026, 1, 12)),  # Friday holiday, then the weekend
    (5, [date(2026, 1, 12)], date(2026, 1, 13)),  # weekend, then a Monday holiday
    (2, [date(2026, 1, 6), date(2026, 1, 8)], date(2026, 1, 7)),  # holidays elsewhere
])
def test_r2_3_holidays_move_forward(net, holidays, expected):
    assert due(f"NET {net}", JAN_5, holidays) == expected


def test_r2_3_end_of_month_can_move_into_the_next_month():
    assert due("EOM", date(2026, 3, 3), [date(2026, 3, 31)]) == date(2026, 4, 1)


# -- R2.4 ------------------------------------------------------------------


@pytest.mark.parametrize("paid_on, expected", [
    (JAN_5, "2.00"),
    (JAN_5 + days(9), "2.00"),
    (JAN_5 + days(10), "2.00"),  # Thursday, the last day
    (JAN_5 + days(11), "0.00"),
    (JAN_5 + days(30), "0.00"),
])
def test_r2_4_discount_window(paid_on, expected):
    assert discount_on(paid_on, invoice_date=JAN_5) == D(expected)


def test_r2_4_fractional_percentage():
    assert discount_on(JAN_5, invoice_date=JAN_5, terms="1.5/10 NET 30") == D("1.50")


def test_r2_4_window_may_be_as_long_as_the_net_days():
    assert discount_on(JAN_5 + days(10), invoice_date=JAN_5, terms="2/10 NET 10") == D("2.00")


@pytest.mark.parametrize("terms", ["NET 30", "EOM"])
def test_r2_4_no_discount_without_discount_terms(terms):
    assert discount_on(JAN_5, invoice_date=JAN_5, terms=terms) == 0


SATURDAY = date(2026, 1, 17)


def test_r2_4_weekend_deadline_itself_still_counts():
    assert discount_on(SATURDAY, invoice_date=SATURDAY - days(10)) == D("2.00")


def test_r2_4_weekend_deadline_has_passed_by_tuesday():
    assert discount_on(SATURDAY + days(3), invoice_date=SATURDAY - days(10)) == 0


R2_4 = pytest.mark.xfail(strict=True, reason="R2.4: the deadline moves past weekends and holidays")


@R2_4
@pytest.mark.parametrize("deadline, paid_on", [
    (SATURDAY, SATURDAY + days(1)),
    (SATURDAY, SATURDAY + days(2)),
    (SATURDAY + days(1), SATURDAY + days(2)),
])
def test_r2_4_deadline_does_not_move_for_weekends(deadline, paid_on):
    assert discount_on(paid_on, invoice_date=deadline - days(10)) == 0


@R2_4
def test_r2_4_deadline_does_not_move_for_holidays():
    deadline = JAN_5 + days(10)  # a Thursday
    assert discount_on(deadline + days(1), invoice_date=JAN_5, holidays=[deadline]) == 0


# -- R2.5 ------------------------------------------------------------------


@pytest.mark.parametrize("text, on, expected", [
    ("net 30", JAN_5, date(2026, 2, 4)),
    ("Net 30", JAN_5, date(2026, 2, 4)),
    ("  NET 30  ", JAN_5, date(2026, 2, 4)),
    ("  2/10 net 30 ", JAN_5, date(2026, 2, 4)),
    ("eom", date(2026, 3, 3), date(2026, 3, 31)),
    (" Eom ", date(2026, 3, 3), date(2026, 3, 31)),
])
def test_r2_5_case_and_surrounding_spaces_are_ignored(text, on, expected):
    assert parse_terms(text).due_date(on) == expected
    assert due(text, on) == expected


def test_r2_5_discount_terms_ignore_case_and_surrounding_spaces():
    assert discount_on(JAN_5, invoice_date=JAN_5, terms=" 2/10 net 30 ") == D("2.00")


BAD_TERMS = [
    "", "   ", "COD", "NET", "30", "NET thirty", "NET -5", "NET 30.5", "NET 30 DAYS", "X NET 30",
    "EOM 30", "EOMX", "PROX", "2/10", "2/ NET 30", "/10 NET 30", "2/10 EOM", "-2/10 NET 30",
    "2/-1 NET 30", "2/10/5 NET 30", "x/10 NET 30",
    "100/10 NET 30", "100.5/10 NET 30", "250/10 NET 30",  # a discount of 100 percent or more
    "2/31 NET 30", "2/10 NET 9", "2/1 NET 0",  # a window longer than the net days
]


@pytest.mark.parametrize("text", BAD_TERMS, ids=repr)
def test_r2_5_anything_else_is_a_terms_error(text):
    with pytest.raises(TermsError):
        parse_terms(text)


@pytest.mark.parametrize("text", ["COD", "100/10 NET 30"])
def test_r2_5_bad_terms_cannot_be_issued(text):
    with pytest.raises(TermsError):
        issued(make_invoice(terms=text))


@pytest.mark.parametrize("text", ["99.99/10 NET 30", "2/30 NET 30", "2/0 NET 0"])
def test_r2_5_limits_that_are_still_allowed(text):
    parse_terms(text)
