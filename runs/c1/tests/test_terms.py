"""SPEC section 2: terms and dates."""

from datetime import date
from decimal import Decimal as D

import pytest

from helpers import JAN_5, invoice, issue, ledger_with
from tally import Ledger, TermsError, parse_terms


def due(terms, day, *args):
    return parse_terms(terms).due_date(day, *args)


# -- due dates ----------------------------------------------------------------


@pytest.mark.parametrize(
    "terms, day, expected",
    [
        ("NET 30", JAN_5, date(2026, 2, 4)),
        ("NET 0", JAN_5, JAN_5),
        ("NET 1", JAN_5, date(2026, 1, 6)),
        ("NET 10", JAN_5, date(2026, 1, 15)),
        ("NET 91", JAN_5, date(2026, 4, 6)),
        ("NET 30", date(2025, 12, 15), date(2026, 1, 14)),
        ("NET 1", date(2028, 2, 28), date(2028, 2, 29)),
    ],
)
def test_net_days_are_calendar_days(terms, day, expected):
    assert due(terms, day) == expected


@pytest.mark.parametrize(
    "day, expected",
    [
        (date(2026, 3, 1), date(2026, 3, 31)),
        (date(2026, 3, 25), date(2026, 3, 31)),
        (date(2026, 3, 26), date(2026, 4, 30)),
        (date(2026, 3, 31), date(2026, 4, 30)),
        (date(2026, 11, 26), date(2026, 12, 31)),
        (date(2026, 12, 25), date(2026, 12, 31)),
        (date(2024, 12, 26), date(2025, 1, 31)),
        (date(2024, 12, 31), date(2025, 1, 31)),
        (date(2028, 2, 10), date(2028, 2, 29)),  # leap year
        (date(2029, 1, 31), date(2029, 2, 28)),
        (date(2025, 12, 26), date(2026, 2, 2)),  # 31 January 2026 is a Saturday
    ],
)
def test_end_of_month(day, expected):
    assert due("EOM", day) == expected


@pytest.mark.parametrize(
    "day, expected",
    [
        (date(2026, 1, 8), date(2026, 1, 9)),  # Friday stays
        (date(2026, 1, 9), date(2026, 1, 12)),  # Saturday moves
        (date(2026, 1, 10), date(2026, 1, 12)),  # Sunday moves
        (date(2026, 1, 11), date(2026, 1, 12)),  # Monday stays
    ],
)
def test_weekend_due_dates_move_to_monday(day, expected):
    assert due("NET 1", day) == expected


def test_holidays_move_the_due_date():
    tuesday = date(2026, 1, 13)
    assert due("NET 1", date(2026, 1, 12), {tuesday}) == date(2026, 1, 14)
    assert due("NET 1", date(2026, 1, 12), {date(2026, 1, 14)}) == tuesday


def test_moving_continues_past_every_weekend_day_and_holiday():
    friday, monday = date(2026, 1, 16), date(2026, 1, 19)
    assert due("NET 1", date(2026, 1, 15), {friday, monday}) == date(2026, 1, 20)
    assert due("NET 1", date(2026, 1, 16), {monday}) == date(2026, 1, 20)


def test_end_of_month_moves_for_holidays():
    assert due("EOM", date(2026, 3, 1), {date(2026, 3, 31)}) == date(2026, 4, 1)


def test_discount_terms_have_the_net_due_date():
    assert due("2/10 NET 30", JAN_5) == date(2026, 2, 4)
    assert due("2/10 NET 30", JAN_5, {date(2026, 2, 4)}) == date(2026, 2, 5)


def test_ledger_uses_its_holidays_for_the_due_date():
    assert issue(Ledger([date(2026, 2, 4)])).due == date(2026, 2, 5)


# -- discount deadline --------------------------------------------------------


@pytest.mark.parametrize(
    "text, expected",
    [
        ("2/10 NET 30", date(2026, 1, 15)),
        ("1.5/1 NET 30", date(2026, 1, 6)),
        ("2/0 NET 30", JAN_5),
        ("2/30 NET 30", date(2026, 2, 4)),  # window as long as the net days
    ],
)
def test_discount_deadline_is_calendar_days_from_the_invoice_date(text, expected):
    assert parse_terms(text).discount_deadline(JAN_5) == expected


@pytest.mark.parametrize("text", ["NET 30", "EOM"])
def test_no_discount_deadline_without_a_discount(text):
    assert parse_terms(text).discount_deadline(JAN_5) is None


@pytest.mark.xfail(strict=True, reason="R2.4: the discount deadline moves past weekends and holidays")
@pytest.mark.parametrize(
    "day, deadline", [(date(2026, 1, 7), date(2026, 1, 17)), (date(2026, 1, 8), date(2026, 1, 18))]
)
def test_discount_deadline_stays_on_a_weekend(day, deadline):
    assert parse_terms("2/10 NET 30").discount_deadline(day) == deadline


@pytest.mark.xfail(strict=True, reason="R2.4: the discount deadline moves past weekends and holidays")
def test_no_discount_on_the_monday_after_a_weekend_deadline():
    ledger = ledger_with(invoice(terms="2/10 NET 30", day=date(2026, 1, 7)))
    ledger.receive("P1", "acme", "98.00", date(2026, 1, 19))
    assert ledger.invoices["INV-1"].balance == D("2.00")


@pytest.mark.xfail(strict=True, reason="R2.4: the discount deadline moves past weekends and holidays")
def test_no_discount_the_day_after_a_holiday_deadline():
    ledger = ledger_with(invoice(terms="2/10 NET 30"), holidays=[date(2026, 1, 15)])
    ledger.receive("P1", "acme", "98.00", date(2026, 1, 16))
    assert ledger.invoices["INV-1"].balance == D("2.00")


def test_discount_is_available_on_a_weekend_or_holiday_deadline():
    weekend = ledger_with(invoice(terms="2/10 NET 30", day=date(2026, 1, 7)))
    weekend.receive("P1", "acme", "98.00", date(2026, 1, 17))
    assert weekend.invoices["INV-1"].status == "paid"

    holiday = ledger_with(invoice(terms="2/10 NET 30"), holidays=[date(2026, 1, 15)])
    holiday.receive("P1", "acme", "98.00", date(2026, 1, 15))
    assert holiday.invoices["INV-1"].status == "paid"


# -- terms text ---------------------------------------------------------------


@pytest.mark.parametrize("text", ["net 30", "Net 30", "  NET 30  "])
def test_net_terms_ignore_case_and_surrounding_spaces(text):
    assert due(text, JAN_5) == date(2026, 2, 4)


@pytest.mark.parametrize("text", ["eom", " Eom ", "EOM"])
def test_eom_terms_ignore_case_and_surrounding_spaces(text):
    assert due(text, date(2026, 3, 1)) == date(2026, 3, 31)


@pytest.mark.parametrize("text", [" 2/10 net 30 ", "2/10 Net 30"])
def test_discount_terms_ignore_case_and_surrounding_spaces(text):
    terms = parse_terms(text)
    assert terms.due_date(JAN_5) == date(2026, 2, 4)
    assert terms.discount_deadline(JAN_5) == date(2026, 1, 15)


@pytest.mark.parametrize(
    "text",
    [
        "", "   ", "NET", "30", "NET -5", "NET 30.5", "NET thirty", "NET 30 DAYS", "DUE NET 30",
        "COD", "EOM 10", "EOMX", "2/10", "2/10 EOM", "/10 NET 30", "2/ NET 30", "2/10 NET",
        "-2/10 NET 30", "2/-1 NET 30", "2%/10 NET 30", "2/10 NET 30 EOM",
    ],
)
def test_anything_else_is_a_terms_error(text):
    with pytest.raises(TermsError):
        parse_terms(text)


@pytest.mark.parametrize("text", ["100/10 NET 30", "100.0/10 NET 30", "150/10 NET 30"])
def test_discount_of_100_percent_or_more_is_a_terms_error(text):
    with pytest.raises(TermsError):
        parse_terms(text)


def test_discount_just_under_100_percent_is_allowed():
    ledger = ledger_with(invoice(terms="99/10 NET 30"))
    ledger.receive("P1", "acme", "1.00", JAN_5)
    assert ledger.invoices["INV-1"].status == "paid"


@pytest.mark.parametrize("text", ["2/31 NET 30", "2/1 NET 0"])
def test_discount_window_longer_than_the_net_days_is_a_terms_error(text):
    with pytest.raises(TermsError):
        parse_terms(text)


def test_bad_terms_never_produce_an_open_invoice():
    ledger = Ledger()
    with pytest.raises(TermsError):
        issue(ledger, terms="whenever")
    assert ledger.events == []
