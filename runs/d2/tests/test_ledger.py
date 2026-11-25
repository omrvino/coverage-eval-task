from datetime import date
from decimal import Decimal

import pytest

from tally import Invoice, InvoiceError, Ledger, Line, PaymentError, aging, parse_terms
from tally.ledger import _number_key

D = Decimal


def make_invoice(number="INV-1", terms="NET 30", price="100.00", day=date(2026, 1, 5), customer="acme"):
    return Invoice(number, customer, day, terms, [Line("work", 1, price)])


def issued(*invoices):
    ledger = Ledger()
    for invoice in invoices:
        ledger.add(invoice)
        ledger.issue(invoice.number)
    return ledger


def test_net_30_due_date():
    assert parse_terms("NET 30").due_date(date(2026, 1, 5)) == date(2026, 2, 4)


def test_issue_sets_due_date():
    ledger = issued(make_invoice())
    assert ledger.invoices["INV-1"].due == date(2026, 2, 4)
    assert ledger.invoices["INV-1"].status == "open"


def test_payment_closes_invoice():
    ledger = issued(make_invoice())
    ledger.receive("P1", "acme", "100.00", date(2026, 1, 20))
    assert ledger.invoices["INV-1"].status == "paid"


def test_payment_must_be_positive():
    ledger = issued(make_invoice())
    with pytest.raises(PaymentError):
        ledger.receive("P1", "acme", "0", date(2026, 1, 20))


def test_late_fee():
    ledger = issued(make_invoice(price="1000.00"))
    ledger.assess_late_fees(date(2026, 2, 20))
    assert ledger.invoices["INV-1"].fees == Decimal("15.00")


def test_aging_runs():
    ledger = issued(make_invoice())
    assert aging(ledger, "acme", date(2026, 1, 10)) is not None


# -- invoices ----------------------------------------------------------------


def test_duplicate_invoice_number_is_refused():
    ledger = Ledger()
    ledger.add(make_invoice())
    with pytest.raises(InvoiceError):
        ledger.add(make_invoice())


def test_unknown_invoice_is_refused():
    ledger = Ledger()
    with pytest.raises(InvoiceError):
        ledger.issue("INV-9")
    with pytest.raises(InvoiceError):
        ledger.void("INV-9", date(2026, 1, 6))
    with pytest.raises(InvoiceError):
        ledger.dispute("INV-9")


def test_ledger_holidays_move_due_dates():
    ledger = Ledger(holidays=[date(2026, 2, 4)])
    ledger.add(make_invoice())
    ledger.issue("INV-1")
    assert ledger.invoices["INV-1"].due == date(2026, 2, 5)


def test_void_writes_off_the_whole_balance():
    ledger = issued(make_invoice())
    ledger.void("INV-1", date(2026, 1, 10))
    assert ledger.invoices["INV-1"].status == "void"
    assert ledger.events[-1].kind == "void"
    assert ledger.events[-1].amount == D("-100.00")


def test_void_refused_once_a_payment_is_applied():
    ledger = issued(make_invoice())
    ledger.receive("P1", "acme", "10.00", date(2026, 1, 10))
    with pytest.raises(InvoiceError):
        ledger.void("INV-1", date(2026, 1, 11))


def test_dispute_only_open_invoices_and_resolve_clears_it():
    ledger = Ledger()
    ledger.add(make_invoice())
    with pytest.raises(InvoiceError):
        ledger.dispute("INV-1")
    ledger.issue("INV-1")
    ledger.dispute("INV-1")
    assert ledger.invoices["INV-1"].disputed
    ledger.resolve("INV-1")
    assert not ledger.invoices["INV-1"].disputed


# -- payments ----------------------------------------------------------------


def test_repeated_payment_id_changes_nothing():
    ledger = issued(make_invoice(price="200.00"))
    first = ledger.receive("P1", "acme", "50.00", date(2026, 1, 10))
    again = ledger.receive("P1", "acme", "50.00", date(2026, 1, 11))
    assert again is first
    assert ledger.invoices["INV-1"].paid == D("50.00")
    assert len(ledger.events) == 2  # the invoice and the one payment


def test_reused_payment_id_with_other_details_is_refused():
    ledger = issued(make_invoice(price="200.00"))
    ledger.receive("P1", "acme", "50.00", date(2026, 1, 10))
    with pytest.raises(PaymentError):
        ledger.receive("P1", "acme", "60.00", date(2026, 1, 10))
    with pytest.raises(PaymentError):
        ledger.receive("P1", "bolt", "50.00", date(2026, 1, 10))


def test_payment_spreads_over_invoices_earliest_due_first():
    ledger = issued(
        make_invoice("INV-1", day=date(2026, 1, 5)),
        make_invoice("INV-2", day=date(2026, 1, 3)),
    )
    ledger.receive("P1", "acme", "150.00", date(2026, 1, 20))
    assert ledger.invoices["INV-2"].status == "paid"
    assert ledger.invoices["INV-1"].paid == D("50.00")


def test_payment_stops_when_nothing_is_left_to_spread():
    ledger = issued(
        make_invoice("INV-1", day=date(2026, 1, 5)),
        make_invoice("INV-2", day=date(2026, 1, 3)),
    )
    ledger.receive("P1", "acme", "100.00", date(2026, 1, 20))
    assert ledger.invoices["INV-2"].status == "paid"
    assert ledger.invoices["INV-1"].paid == D("0.00")
    assert ledger.credit("acme") == D("0.00")


def test_early_payment_discount_is_granted_and_logged():
    ledger = issued(make_invoice("INV-1", terms="2/10 NET 30", day=date(2026, 2, 1), customer="bolt"))
    payment = ledger.receive("B1", "bolt", "98.00", date(2026, 2, 5))
    invoice = ledger.invoices["INV-1"]
    assert invoice.status == "paid"
    assert invoice.discount_taken == D("2.00")
    assert payment.allocations[0].discount == D("2.00")
    assert [event.kind for event in ledger.events] == ["invoice", "payment", "discount"]


def test_partial_early_payment_gets_no_discount():
    ledger = issued(make_invoice("INV-1", terms="2/10 NET 30", day=date(2026, 2, 1), customer="bolt"))
    ledger.receive("B1", "bolt", "50.00", date(2026, 2, 5))
    assert ledger.invoices["INV-1"].discount_taken == D("0.00")
    assert [event.kind for event in ledger.events] == ["invoice", "payment"]


def test_payment_after_the_discount_deadline_gets_no_discount():
    ledger = issued(make_invoice("INV-1", terms="2/10 NET 30", day=date(2026, 2, 1), customer="bolt"))
    ledger.receive("B1", "bolt", "98.00", date(2026, 2, 12))
    invoice = ledger.invoices["INV-1"]
    assert invoice.discount_taken == D("0.00")
    assert invoice.status == "open"


def test_overpayment_becomes_credit_and_apply_credit_uses_it():
    ledger = issued(make_invoice("INV-1", price="100.00"))
    ledger.receive("P1", "acme", "250.00", date(2026, 1, 10))
    assert ledger.credit("acme") == D("150.00")

    ledger.add(make_invoice("INV-2", price="100.00", day=date(2026, 1, 12)))
    ledger.issue("INV-2")
    events_before = len(ledger.events)
    allocations = ledger.apply_credit("acme", date(2026, 1, 20))

    assert [a.invoice for a in allocations] == ["INV-2"]
    assert ledger.invoices["INV-2"].status == "paid"
    assert ledger.credit("acme") == D("50.00")
    assert len(ledger.events) == events_before


# -- reversals ---------------------------------------------------------------


def test_reverse_undoes_the_payment_on_the_invoice():
    ledger = issued(make_invoice("INV-1", price="100.00", terms="2/10 NET 30", day=date(2026, 2, 1), customer="bolt"))
    ledger.receive("B1", "bolt", "98.00", date(2026, 2, 5))
    ledger.reverse("B1", date(2026, 2, 6))
    assert ledger.invoices["INV-1"].paid == D("0.00")
    assert ledger.invoices["INV-1"].status == "open"
    assert ledger.payments["B1"].reversed
    assert ledger.events[-1].kind == "reversal"
    assert ledger.events[-1].amount == D("100.00")


def test_reverse_unknown_or_already_reversed_payment_is_refused():
    ledger = issued(make_invoice())
    with pytest.raises(PaymentError):
        ledger.reverse("P404", date(2026, 1, 10))
    ledger.receive("P1", "acme", "10.00", date(2026, 1, 10))
    ledger.reverse("P1", date(2026, 1, 11))
    with pytest.raises(PaymentError):
        ledger.reverse("P1", date(2026, 1, 12))


def test_reversed_payment_id_cannot_be_received_again():
    ledger = issued(make_invoice())
    ledger.receive("P1", "acme", "10.00", date(2026, 1, 10))
    ledger.reverse("P1", date(2026, 1, 11))
    with pytest.raises(PaymentError):
        ledger.receive("P1", "acme", "10.00", date(2026, 1, 12))


def test_reverse_refused_once_the_credit_it_left_is_used():
    ledger = issued(make_invoice("INV-1", price="100.00"))
    ledger.receive("P1", "acme", "250.00", date(2026, 1, 10))
    ledger.add(make_invoice("INV-2", price="100.00", day=date(2026, 1, 12)))
    ledger.issue("INV-2")
    ledger.apply_credit("acme", date(2026, 1, 20))
    with pytest.raises(PaymentError):
        ledger.reverse("P1", date(2026, 1, 21))
    assert not ledger.payments["P1"].reversed
    assert ledger.credit("acme") == D("50.00")


# -- late fees ---------------------------------------------------------------


def test_no_late_fee_within_the_grace_days():
    ledger = issued(make_invoice(price="1000.00"))
    assert ledger.assess_late_fees(date(2026, 2, 8)) == {}  # four days late
    assert ledger.invoices["INV-1"].fees == D("0.00")


def test_late_fee_for_a_started_period_is_repeat_safe():
    ledger = issued(make_invoice(price="1000.00"))
    assert ledger.assess_late_fees(date(2026, 2, 20)) == {"INV-1": D("15.00")}
    assert ledger.assess_late_fees(date(2026, 2, 20)) == {}
    assert ledger.invoices["INV-1"].fees == D("15.00")


def test_each_new_period_is_charged_once():
    ledger = issued(make_invoice(price="1000.00"))
    ledger.assess_late_fees(date(2026, 2, 20))
    assert ledger.assess_late_fees(date(2026, 3, 10)) == {"INV-1": D("15.00")}
    assert ledger.invoices["INV-1"].fees == D("30.00")


def test_late_fee_has_a_minimum_per_period():
    ledger = issued(make_invoice(price="100.00"))
    assert ledger.assess_late_fees(date(2026, 2, 20)) == {"INV-1": D("5.00")}


def test_late_fees_stop_at_ten_percent_of_the_total():
    ledger = issued(make_invoice(price="100.00"))
    assert ledger.assess_late_fees(date(2026, 4, 20)) == {"INV-1": D("10.00")}
    assert ledger.assess_late_fees(date(2026, 5, 20)) == {}
    assert ledger.invoices["INV-1"].fees == D("10.00")


def test_late_fee_on_a_disputed_invoice_is_waived_for_that_period():
    ledger = issued(make_invoice(price="1000.00"))
    ledger.dispute("INV-1")
    assert ledger.assess_late_fees(date(2026, 2, 20)) == {}
    ledger.resolve("INV-1")
    assert ledger.assess_late_fees(date(2026, 2, 20)) == {}
    assert ledger.assess_late_fees(date(2026, 3, 10)) == {"INV-1": D("15.00")}


def test_number_key_reads_digit_runs_as_numbers():
    assert _number_key("INV-2") < _number_key("INV-10")
