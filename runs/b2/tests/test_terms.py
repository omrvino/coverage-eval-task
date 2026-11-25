from datetime import date

import pytest

from helpers import invoice, ledger_with
from tally import Ledger, TermsError, parse_terms


def due(text, day, holidays=()):
    return parse_terms(text).due_date(day, frozenset(holidays))


# R2.1 ---------------------------------------------------------------------

@pytest.mark.parametrize("text, day, expected", [
    ("NET 30", date(2026, 1, 5), date(2026, 2, 4)),
    ("NET 7", date(2026, 1, 5), date(2026, 1, 12)),
    ("NET 1", date(2026, 1, 5), date(2026, 1, 6)),
    ("NET 0", date(2026, 1, 5), date(2026, 1, 5)),
    ("NET 45", date(2026, 1, 5), date(2026, 2, 19)),
    ("NET 60", date(2026, 12, 15), date(2027, 2, 15)),   # across a year end
    ("NET 30", date(2028, 2, 1), date(2028, 3, 2)),       # leap year
    ("NET 30", date(2026, 2, 2), date(2026, 3, 4)),
])
def test_net_days_are_calendar_days(text, day, expected):
    assert due(text, day) == expected


# R2.2 ---------------------------------------------------------------------

@pytest.mark.parametrize("day, expected", [
    (date(2026, 3, 1), date(2026, 3, 31)),
    (date(2026, 3, 10), date(2026, 3, 31)),
    (date(2026, 3, 25), date(2026, 3, 31)),       # the 25th stays in its month
    (date(2026, 3, 26), date(2026, 4, 30)),       # the 26th moves to next month
    (date(2026, 3, 31), date(2026, 4, 30)),
    (date(2026, 12, 25), date(2026, 12, 31)),
    (date(2026, 12, 26), date(2027, 2, 1)),       # Jan 31 2027 is a Sunday
    (date(2028, 1, 26), date(2028, 2, 29)),       # leap February, a Tuesday
    (date(2028, 2, 20), date(2028, 2, 29)),
    (date(2026, 2, 10), date(2026, 3, 2)),        # Feb 28 is a Saturday
    (date(2026, 1, 5), date(2026, 2, 2)),         # Jan 31 is a Saturday
])
def test_eom_due_dates(day, expected):
    assert due("EOM", day) == expected


# R2.3 ---------------------------------------------------------------------

@pytest.mark.parametrize("text, day, expected", [
    ("NET 5", date(2026, 1, 5), date(2026, 1, 12)),    # Saturday
    ("NET 6", date(2026, 1, 5), date(2026, 1, 12)),    # Sunday
    ("NET 4", date(2026, 1, 5), date(2026, 1, 9)),     # Friday stays
    ("NET 7", date(2026, 1, 5), date(2026, 1, 12)),    # Monday stays
])
def test_weekend_due_dates_move_to_monday(text, day, expected):
    assert due(text, day) == expected


def test_holiday_due_date_moves_forward():
    assert due("NET 7", date(2026, 1, 5), [date(2026, 1, 12)]) == date(2026, 1, 13)


def test_due_date_skips_a_run_of_holidays_and_weekends():
    holidays = [date(2026, 1, 9), date(2026, 1, 12)]
    assert due("NET 4", date(2026, 1, 5), holidays) == date(2026, 1, 13)


def test_eom_moves_past_a_holiday():
    assert due("EOM", date(2026, 3, 10), [date(2026, 3, 31)]) == date(2026, 4, 1)


def test_holiday_on_another_day_changes_nothing():
    assert due("NET 7", date(2026, 1, 5), [date(2026, 1, 13)]) == date(2026, 1, 12)


def test_ledger_uses_its_holidays_when_issuing():
    ledger = ledger_with(invoice(terms="NET 7"), holidays=[date(2026, 1, 12)])
    assert ledger.invoices["INV-1"].due == date(2026, 1, 13)
    plain = ledger_with(invoice(terms="NET 7"))
    assert plain.invoices["INV-1"].due == date(2026, 1, 12)
    assert isinstance(Ledger().holidays, frozenset)


def test_discount_terms_use_the_net_days_for_the_due_date():
    assert due("2/10 NET 30", date(2026, 1, 5)) == date(2026, 2, 4)
    assert due("2/5 NET 5", date(2026, 1, 5)) == date(2026, 1, 12)


# R2.5 ---------------------------------------------------------------------

@pytest.mark.parametrize("variant", ["net 30", "  NET 30  ", "Net 30", " net 30 "])
def test_terms_ignore_case_and_surrounding_spaces(variant):
    assert due(variant, date(2026, 1, 5)) == date(2026, 2, 4)


def test_eom_and_discount_terms_ignore_case_and_spaces():
    assert due(" eom ", date(2026, 3, 10)) == date(2026, 3, 31)
    assert due(" 2/10 net 30 ", date(2026, 1, 5)) == date(2026, 2, 4)


@pytest.mark.parametrize("text", [
    "", "   ", "NET", "NET abc", "NET -5", "NET 3.5", "30", "EOM 30", "NET 30 days",
    "foo", "2/10", "2/10 EOM", "/10 NET 30", "2/ NET 30", "two/10 NET 30",
    "100/10 NET 30", "150/10 NET 30", "2/31 NET 30", "2/60 NET 30", "1/11 NET 10",
])
def test_unrecognised_or_impossible_terms_raise(text):
    with pytest.raises(TermsError):
        parse_terms(text)


@pytest.mark.parametrize("text", ["99/10 NET 30", "2/30 NET 30", "1/0 NET 30", "5/10 NET 10"])
def test_discount_terms_at_the_edges_are_valid(text):
    days = int(text.rsplit(" ", 1)[1])
    assert due(text, date(2026, 1, 5)) == due("NET %d" % days, date(2026, 1, 5))
