from datetime import date

import pytest

from tally import TermsError, parse_terms


# -- R2.1 ------------------------------------------------------------------

def test_net_days_are_calendar_days():
    assert parse_terms("NET 30").due_date(date(2026, 1, 5)) == date(2026, 2, 4)
    assert parse_terms("NET 7").due_date(date(2026, 1, 5)) == date(2026, 1, 12)
    # across a leap day
    assert parse_terms("NET 30").due_date(date(2028, 2, 1)) == date(2028, 3, 2)


def test_net_zero_is_due_on_the_invoice_date():
    assert parse_terms("NET 0").due_date(date(2026, 1, 5)) == date(2026, 1, 5)


# -- R2.2 ------------------------------------------------------------------

@pytest.mark.parametrize("invoice_date, due", [
    (date(2026, 3, 2), date(2026, 3, 31)),     # Tuesday
    (date(2026, 3, 25), date(2026, 3, 31)),    # the 25th still ends this month
    (date(2026, 3, 26), date(2026, 4, 30)),    # the 26th goes to next month (Thursday)
    (date(2026, 3, 31), date(2026, 4, 30)),
    (date(2026, 11, 30), date(2026, 12, 31)),  # Thursday
    (date(2026, 12, 26), date(2027, 2, 1)),    # Jan 31 2027 is a Sunday, so Monday
    (date(2027, 1, 26), date(2027, 3, 1)),     # Feb 28 2027 is a Sunday, so Monday
    (date(2028, 1, 26), date(2028, 2, 29)),    # leap year, Tuesday
    (date(2026, 4, 10), date(2026, 4, 30)),    # 30-day month, Thursday
])
def test_eom_due_dates(invoice_date, due):
    assert parse_terms("EOM").due_date(invoice_date) == due


# -- R2.3 ------------------------------------------------------------------

def test_weekend_due_dates_move_to_monday():
    assert parse_terms("NET 30").due_date(date(2026, 2, 5)) == date(2026, 3, 9)  # Sat Mar 7
    assert parse_terms("NET 30").due_date(date(2026, 2, 6)) == date(2026, 3, 9)  # Sun Mar 8


def test_friday_and_monday_due_dates_do_not_move():
    assert parse_terms("NET 30").due_date(date(2026, 2, 4)) == date(2026, 3, 6)   # Fri
    assert parse_terms("NET 30").due_date(date(2026, 2, 7)) == date(2026, 3, 9)   # Mon


def test_holiday_due_date_moves_to_next_working_day():
    holidays = {date(2026, 3, 4)}
    assert parse_terms("NET 30").due_date(date(2026, 2, 2), holidays) == date(2026, 3, 5)


def test_holiday_chain_with_weekend_keeps_moving():
    # due Fri Mar 6 is a holiday, then Sat, Sun, and Monday is a holiday too
    holidays = {date(2026, 3, 6), date(2026, 3, 9)}
    assert parse_terms("NET 30").due_date(date(2026, 2, 4), holidays) == date(2026, 3, 10)


def test_holidays_apply_to_eom_too():
    holidays = {date(2026, 3, 31)}
    assert parse_terms("EOM").due_date(date(2026, 3, 2), holidays) == date(2026, 4, 1)


def test_other_holidays_change_nothing():
    assert parse_terms("NET 30").due_date(date(2026, 2, 2), {date(2026, 3, 3)}) == date(2026, 3, 4)


# -- R2.4 ------------------------------------------------------------------

def test_discount_terms_set_the_due_date_from_the_net_days():
    assert parse_terms("2/10 NET 30").due_date(date(2026, 2, 2)) == date(2026, 3, 4)


def test_discount_deadline_counts_calendar_days():
    assert parse_terms("2/10 NET 30").discount_deadline(date(2026, 2, 2)) == date(2026, 2, 12)


@pytest.mark.xfail(strict=True, reason="discount deadline is rolled past weekends")
def test_discount_deadline_does_not_move_for_weekends():
    terms = parse_terms("2/10 NET 30")
    assert terms.discount_deadline(date(2026, 2, 11)) == date(2026, 2, 21)  # a Saturday


@pytest.mark.xfail(strict=True, reason="discount deadline is rolled past holidays")
def test_discount_deadline_does_not_move_for_holidays():
    terms = parse_terms("2/10 NET 30")
    assert terms.discount_deadline(date(2026, 2, 2), {date(2026, 2, 12)}) == date(2026, 2, 12)


# -- R2.5 ------------------------------------------------------------------

@pytest.mark.parametrize("text, canonical", [
    ("net 30", "NET 30"),
    ("  NET 30  ", "NET 30"),
    ("Net 30", "NET 30"),
    ("\tNET 30 ", "NET 30"),
    ("eom", "EOM"),
    (" Eom ", "EOM"),
    ("2/10 net 30", "2/10 NET 30"),
    (" 2/10 NET 30 ", "2/10 NET 30"),
])
def test_terms_ignore_case_and_surrounding_spaces(text, canonical):
    assert parse_terms(text) == parse_terms(canonical)
    day = date(2026, 3, 2)
    assert parse_terms(text).due_date(day) == parse_terms(canonical).due_date(day)


@pytest.mark.parametrize("text", [
    "", "   ", "NET", "NET x", "NET -5", "30", "NET 30 days", "EOM 30", "NET 30 EOM",
    "2/10", "2/10 EOM", "/10 NET 30", "2/ NET 30", "COD", "2%/10 NET 30",
    "100/10 NET 30", "100.0/10 NET 30", "150/10 NET 30",   # discount of 100 percent or more
    "2/31 NET 30", "2/45 NET 30", "5/60 NET 30",           # window longer than the net days
])
def test_bad_terms_raise_terms_error(text):
    with pytest.raises(TermsError):
        parse_terms(text)


def test_discount_edges_that_are_allowed():
    parse_terms("99/10 NET 30")
    parse_terms("2/30 NET 30")      # window equal to the net days
