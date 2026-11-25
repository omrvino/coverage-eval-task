from datetime import date, timedelta
from decimal import Decimal

import pytest

from tally import Invoice, InvoiceError, Ledger, Line

D = Decimal
JAN5 = date(2026, 1, 5)


def make(number="INV-1", *, price="100.00", terms="NET 30", lines=None, day=JAN5):
    if lines is None:
        lines = [Line("work", 1, price)]
    return Invoice(number, "acme", day, terms, lines)


def issued(*invoices):
    ledger = Ledger()
    for item in invoices:
        ledger.add(item)
        ledger.issue(item.number)
    return ledger


def ledger_in_state(state):
    ledger = Ledger()
    ledger.add(make())
    if state in ("open", "void", "paid"):
        ledger.issue("INV-1")
    if state == "void":
        ledger.void("INV-1", date(2026, 1, 6))
    if state == "paid":
        ledger.receive("P1", "acme", "100.00", date(2026, 1, 6))
    return ledger


ACTIONS = {
    "issue": lambda ledger, number: ledger.issue(number),
    "void": lambda ledger, number: ledger.void(number, JAN5),
    "dispute": lambda ledger, number: ledger.dispute(number),
    "resolve": lambda ledger, number: ledger.resolve(number),
}


def test_status_moves_from_draft_to_open_to_paid():
    ledger = Ledger()
    inv = ledger.add(make())
    assert inv.status == "draft"
    ledger.issue("INV-1")
    assert inv.status == "open"
    ledger.receive("P1", "acme", "100.00", date(2026, 1, 20))
    assert inv.status == "paid"


def test_issuing_sets_the_due_date_from_the_terms():
    ledger = issued(make(terms="EOM"))
    # Jan 31 2026 is a Saturday, so the due date moves to Monday Feb 2.
    assert ledger.invoices["INV-1"].due == date(2026, 2, 2)


def test_duplicate_invoice_number_is_refused_and_the_first_is_kept():
    ledger = Ledger()
    ledger.add(make(price="100.00"))
    with pytest.raises(InvoiceError):
        ledger.add(make(price="5.00"))
    assert ledger.invoices["INV-1"].total == D("100.00")


@pytest.mark.parametrize("action", sorted(ACTIONS))
def test_unknown_invoice_number_is_refused(action):
    with pytest.raises(InvoiceError):
        ACTIONS[action](Ledger(), "NOPE")


def test_issue_needs_at_least_one_line():
    ledger = Ledger()
    ledger.add(make(lines=[]))
    with pytest.raises(InvoiceError):
        ledger.issue("INV-1")
    assert ledger.invoices["INV-1"].status == "draft"


@pytest.mark.parametrize("price", ["-5.00", "-0.01"])
def test_issue_refuses_a_negative_total(price):
    ledger = Ledger()
    ledger.add(make(lines=[Line("credit", 1, price)]))
    with pytest.raises(InvoiceError):
        ledger.issue("INV-1")
    assert ledger.invoices["INV-1"].status == "draft"


def test_zero_total_invoice_issues_and_is_paid_at_once():
    ledger = Ledger()
    ledger.add(make(price="0.00"))
    ledger.issue("INV-1")
    assert ledger.invoices["INV-1"].status == "paid"


def test_credit_line_offsets_charges_while_total_stays_zero_or_more():
    ledger = issued(make(lines=[Line("work", 1, "100.00"), Line("credit", 1, "-40.00")]))
    assert ledger.invoices["INV-1"].total == D("60.00")


def test_issuing_twice_is_refused():
    ledger = issued(make())
    with pytest.raises(InvoiceError):
        ledger.issue("INV-1")


def test_a_voided_invoice_cannot_be_issued():
    ledger = issued(make())
    ledger.void("INV-1", date(2026, 1, 6))
    with pytest.raises(InvoiceError):
        ledger.issue("INV-1")


def test_draft_invoice_cannot_be_voided():
    ledger = Ledger()
    ledger.add(make())
    with pytest.raises(InvoiceError):
        ledger.void("INV-1", JAN5)


def test_invoice_cannot_be_voided_twice():
    ledger = issued(make())
    ledger.void("INV-1", date(2026, 1, 6))
    with pytest.raises(InvoiceError):
        ledger.void("INV-1", date(2026, 1, 7))


def test_invoice_with_a_payment_cannot_be_voided():
    ledger = issued(make())
    ledger.receive("P1", "acme", "10.00", date(2026, 1, 10))
    with pytest.raises(InvoiceError):
        ledger.void("INV-1", date(2026, 1, 11))
    assert ledger.invoices["INV-1"].status == "open"


def test_invoice_with_a_late_fee_paid_cannot_be_voided():
    ledger = issued(make())
    due = ledger.invoices["INV-1"].due
    ledger.assess_late_fees(due + timedelta(days=6))
    ledger.receive("P1", "acme", "5.00", due + timedelta(days=6))
    with pytest.raises(InvoiceError):
        ledger.void("INV-1", due + timedelta(days=7))


def test_void_writes_off_the_whole_balance_including_late_fees_as_one_event():
    ledger = issued(make())
    due = ledger.invoices["INV-1"].due
    ledger.assess_late_fees(due + timedelta(days=6))
    ledger.void("INV-1", date(2026, 2, 12))
    voids = [event for event in ledger.events if event.kind == "void"]
    assert len(voids) == 1
    assert voids[0].amount == D("-105.00")
    assert voids[0].date == date(2026, 2, 12)
    assert ledger.invoices["INV-1"].status == "void"


@pytest.mark.parametrize("state", ["draft", "void", "paid"])
def test_only_open_invoices_can_be_disputed(state):
    ledger = ledger_in_state(state)
    with pytest.raises(InvoiceError):
        ledger.dispute("INV-1")
    assert ledger.invoices["INV-1"].disputed is False


def test_open_invoice_can_be_disputed_and_resolved():
    ledger = ledger_in_state("open")
    ledger.dispute("INV-1")
    assert ledger.invoices["INV-1"].disputed is True
    assert ledger.invoices["INV-1"].status == "open"
    ledger.resolve("INV-1")
    assert ledger.invoices["INV-1"].disputed is False
