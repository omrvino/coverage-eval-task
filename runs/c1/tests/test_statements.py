"""SPEC section 7: statements."""

from datetime import date
from decimal import Decimal as D
from itertools import permutations

from helpers import invoice, issue, ledger_with
from tally import Event, Ledger, aging, statement

JAN_1, JAN_31 = date(2026, 1, 1), date(2026, 1, 31)


def lines(report):
    return [(n.date, n.kind, n.ref, n.amount, n.balance) for n in report.lines]


# -- period -------------------------------------------------------------------


def test_empty_account():
    report = statement(Ledger(), "acme", JAN_1, JAN_31)
    assert (report.customer, report.opening, report.closing, list(report.lines)) == (
        "acme", D("0.00"), D("0.00"), [],
    )


def around_january():
    """An invoice on each edge of January and just outside it."""
    ledger = Ledger()
    issue(ledger, "INV-1", "1.00", day=date(2025, 12, 31))
    issue(ledger, "INV-2", "20.00", day=JAN_1)
    issue(ledger, "INV-3", "300.00", day=JAN_31)
    issue(ledger, "INV-4", "4000.00", day=date(2026, 2, 1))
    return ledger


def test_period_includes_both_its_first_and_last_day():
    report = statement(around_january(), "acme", JAN_1, JAN_31)
    assert lines(report) == [
        (JAN_1, "invoice", "INV-2", D("20.00"), D("21.00")),
        (JAN_31, "invoice", "INV-3", D("300.00"), D("321.00")),
    ]
    assert (report.opening, report.closing) == (D("1.00"), D("321.00"))


def test_one_day_period():
    report = statement(around_january(), "acme", JAN_31, JAN_31)
    assert (report.opening, report.closing) == (D("21.00"), D("321.00"))
    assert [n.ref for n in report.lines] == ["INV-3"]


def test_without_lines_the_closing_balance_is_the_opening_balance():
    report = statement(around_january(), "acme", date(2026, 1, 2), date(2026, 1, 30))
    assert (report.opening, report.closing, list(report.lines)) == (D("21.00"), D("21.00"), [])


def test_neighbouring_periods_join_up():
    ledger = around_january()
    january = statement(ledger, "acme", JAN_1, JAN_31)
    february = statement(ledger, "acme", date(2026, 2, 1), date(2026, 2, 28))
    assert january.closing == february.opening


def test_opening_balance_counts_every_kind_of_earlier_activity():
    ledger = ledger_with(
        invoice("INV-1", "100.00", "2/10 NET 10"),
        invoice("INV-2", "50.00"),
        invoice("INV-3", "7.00"),
    )
    ledger.receive("P1", "acme", "98.00", date(2026, 1, 6))  # with a 2.00 discount
    ledger.receive("P2", "acme", "10.00", date(2026, 1, 7))
    ledger.reverse("P2", date(2026, 1, 8))
    ledger.void("INV-3", date(2026, 1, 9))
    ledger.assess_late_fees(date(2026, 2, 20))  # 5.00 on INV-2
    report = statement(ledger, "acme", date(2026, 3, 1), date(2026, 3, 31))
    assert (report.opening, report.closing, list(report.lines)) == (D("55.00"), D("55.00"), [])


# -- lines --------------------------------------------------------------------


def test_lines_are_in_date_order():
    ledger = Ledger()
    issue(ledger, "INV-2", "20.00", day=date(2026, 1, 20))
    issue(ledger, "INV-1", "10.00", day=date(2026, 1, 10))
    ledger.receive("P1", "acme", "5.00", date(2026, 1, 15))
    assert lines(statement(ledger, "acme", JAN_1, JAN_31)) == [
        (date(2026, 1, 10), "invoice", "INV-1", D("10.00"), D("10.00")),
        (date(2026, 1, 15), "payment", "P1", D("-5.00"), D("5.00")),
        (date(2026, 1, 20), "invoice", "INV-2", D("20.00"), D("25.00")),
    ]


def test_date_comes_before_kind():
    ledger = ledger_with(invoice("INV-1"))
    ledger.void("INV-1", date(2026, 1, 6))
    issue(ledger, "INV-2", day=date(2026, 1, 7))
    report = statement(ledger, "acme", JAN_1, JAN_31)
    assert [n.kind for n in report.lines] == ["invoice", "void", "invoice"]


def test_every_kind_on_one_day_with_signs_and_running_balance():
    # Recorded out of order on purpose. 11 May is 6 days after the 5 May due date.
    day = date(2026, 5, 11)
    ledger = Ledger()
    issue(ledger, "OLD", "1000.00", "NET 10", day=date(2026, 4, 25))
    issue(ledger, "GONE", "9.00", "NET 60", day=date(2026, 4, 25))
    ledger.receive("P1", "acme", "40.00", date(2026, 4, 27))
    ledger.void("GONE", day)
    ledger.reverse("P1", day)
    ledger.assess_late_fees(day)
    issue(ledger, "NEW", "100.00", "2/10 NET 30", day=day)
    ledger.receive("P2", "acme", "1113.00", day)  # 1000.00 + 15.00 + 98.00
    report = statement(ledger, "acme", day, day)
    assert report.opening == D("969.00")
    assert lines(report) == [
        (day, "invoice", "NEW", D("100.00"), D("1069.00")),
        (day, "fee", "OLD", D("15.00"), D("1084.00")),
        (day, "payment", "P2", D("-1113.00"), D("-29.00")),
        (day, "discount", "NEW", D("-2.00"), D("-31.00")),
        (day, "reversal", "P1", D("40.00"), D("9.00")),
        (day, "void", "GONE", D("-9.00"), D("0.00")),
    ]
    assert report.closing == D("0.00")


def test_same_day_order_does_not_depend_on_the_order_recorded():
    kinds = ["invoice", "fee", "payment", "discount", "reversal", "void"]
    for recorded in permutations(kinds):
        ledger = Ledger()
        ledger.events.extend(Event(JAN_1, "acme", kind, kind, D("1.00")) for kind in recorded)
        report = statement(ledger, "acme", JAN_1, JAN_1)
        assert [n.kind for n in report.lines] == kinds


def test_only_the_named_customers_activity_appears():
    ledger = ledger_with(
        invoice("INV-1", "100.00"),
        invoice("INV-2", "50.00", customer="other"),
        invoice("INV-3", "70.00", customer="other", day=date(2025, 12, 1)),
    )
    ledger.receive("P1", "other", "30.00", date(2026, 1, 8))
    report = statement(ledger, "acme", JAN_1, JAN_31)
    assert (report.opening, report.closing) == (D("0.00"), D("100.00"))
    assert [n.ref for n in report.lines] == ["INV-1"]
    other = statement(ledger, "other", JAN_1, JAN_31)
    assert (other.opening, other.closing) == (D("70.00"), D("90.00"))


def test_closing_balance_agrees_with_aging():
    ledger = ledger_with(invoice("INV-1", "1000.00"), invoice("INV-2", "200.00", "2/10 NET 60"))
    ledger.receive("P1", "acme", "300.00", date(2026, 1, 8))
    ledger.assess_late_fees(date(2026, 2, 20))  # 1.5% of 700.00
    ledger.receive("P2", "acme", "500.00", date(2026, 2, 21))
    ledger.reverse("P1", date(2026, 2, 22))
    report = statement(ledger, "acme", JAN_1, date(2026, 12, 31))
    assert report.closing == D("710.50")
    assert report.closing == sum(aging(ledger, "acme", date(2026, 2, 22)).values())
