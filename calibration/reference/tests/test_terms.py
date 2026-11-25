from datetime import date

import pytest

from tally import TermsError, parse_terms


@pytest.mark.parametrize("text, day, due", [
    ("NET 30", date(2026, 1, 5), date(2026, 2, 4)),
    ("net 0", date(2026, 1, 5), date(2026, 1, 5)),
    (" Net 30 ", date(2026, 1, 5), date(2026, 2, 4)),
    ("2/10 net 30", date(2026, 1, 5), date(2026, 2, 4)),
    ("EOM", date(2026, 3, 25), date(2026, 3, 31)),
    ("eom", date(2026, 3, 26), date(2026, 4, 30)),
    ("EOM", date(2026, 12, 28), date(2027, 2, 1)),      # Jan 31 2027 is a Sunday
    ("EOM", date(2026, 11, 26), date(2026, 12, 31)),
    ("NET 10", date(2026, 1, 7), date(2026, 1, 19)),    # lands on Saturday
    ("NET 11", date(2026, 1, 7), date(2026, 1, 19)),    # lands on Sunday
])
def test_due_date(text, day, due):
    assert parse_terms(text).due_date(day) == due


def test_due_date_rolls_past_holidays():
    holidays = {date(2026, 1, 19), date(2026, 1, 20), date(2026, 1, 23)}
    assert parse_terms("NET 10").due_date(date(2026, 1, 7), holidays) == date(2026, 1, 21)
    assert parse_terms("NET 2").due_date(date(2026, 1, 21), holidays) == date(2026, 1, 26)


def test_discount_deadline():
    assert parse_terms("2/10 NET 30").discount_deadline(date(2026, 1, 5)) == date(2026, 1, 15)
    assert parse_terms("NET 30").discount_deadline(date(2026, 1, 5)) is None


@pytest.mark.xfail(strict=True, reason="R2.4: the deadline rolls forward")
def test_discount_deadline_does_not_roll():
    assert parse_terms("2/10 NET 30").discount_deadline(date(2026, 1, 7)) == date(2026, 1, 17)
    assert parse_terms("2/10 NET 30").discount_deadline(date(2026, 1, 5), {date(2026, 1, 15)}) == date(2026, 1, 15)


@pytest.mark.parametrize("text", ["", "SOON", "NET", "NET -1", "100/10 NET 30", "2/31 NET 30", "2/10"])
def test_bad_terms(text):
    with pytest.raises(TermsError):
        parse_terms(text)


def test_discount_window_may_equal_net_days():
    assert parse_terms("2/30 NET 30").discount_deadline(date(2026, 1, 5)) == date(2026, 2, 4)
