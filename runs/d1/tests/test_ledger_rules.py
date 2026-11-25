from datetime import date
from decimal import Decimal

import pytest

from tally import Event, Invoice, InvoiceError, Ledger, Line, PaymentError
from tally.ledger import _number_key

D = Decimal


def invoice(number="INV-1", price="100.00", terms="NET 30", day=date(2026, 1, 5),
            customer="acme", tax_rate=0):
    return Invoice(number, customer, day, terms, [Line("work", 1, price)], tax_rate=tax_rate)


def ledger_with(*invoices, holidays=()):
    ledger = Ledger(holidays)
    for item in invoices:
        ledger.add(item)
        ledger.issue(item.number)
    return ledger


# -- invoices in the ledger ---------------------------------------------------


def test_duplicate_invoice_number_is_refused():
    ledger = Ledger()
    ledger.add(invoice())
    with pytest.raises(InvoiceError):
        ledger.add(invoice())


def test_unknown_invoice_number_is_refused():
    ledger = Ledger()
    with pytest.raises(InvoiceError):
        ledger.issue("nope")
    with pytest.raises(InvoiceError):
        ledger.void("nope", date(2026, 1, 6))
    with pytest.raises(InvoiceError):
        ledger.dispute("nope")
    with pytest.raises(InvoiceError):
        ledger.resolve("nope")


def test_ledger_holidays_move_due_dates():
    ledger = ledger_with(invoice(), holidays=[date(2026, 2, 4)])
    assert ledger.invoices["INV-1"].due == date(2026, 2, 5)


def test_only_an_open_invoice_can_be_disputed():
    ledger = Ledger()
    ledger.add(invoice())
    with pytest.raises(InvoiceError):
        ledger.dispute("INV-1")


def test_dispute_and_resolve():
    ledger = ledger_with(invoice())
    ledger.dispute("INV-1")
    assert ledger.invoices["INV-1"].disputed is True
    ledger.resolve("INV-1")
    assert ledger.invoices["INV-1"].disputed is False


# -- payments -----------------------------------------------------------------


def test_payment_goes_to_the_earliest_due_date_first():
    late = invoice("INV-1", "100.00", day=date(2026, 1, 5), terms="NET 30")  # due Feb 4
    early = invoice("INV-2", "100.00", day=date(2026, 1, 1), terms="NET 20")  # due Jan 21
    ledger = ledger_with(late, early)
    ledger.receive("P1", "acme", "100.00", date(2026, 1, 25))
    assert ledger.invoices["INV-2"].status == "paid"
    assert ledger.invoices["INV-1"].status == "open"


def test_equal_due_dates_are_paid_in_invoice_number_order():
    ledger = ledger_with(invoice("INV-1", "100.00"), invoice("INV-2", "100.00"))
    ledger.receive("P1", "acme", "100.00", date(2026, 1, 20))
    assert ledger.invoices["INV-1"].status == "paid"
    assert ledger.invoices["INV-2"].status == "open"


@pytest.mark.xfail(strict=True, reason="R4.1: digit runs compare as numbers, so INV-2 comes before INV-10")
def test_equal_due_dates_read_digit_runs_as_numbers():
    ledger = ledger_with(invoice("INV-10", "100.00"), invoice("INV-2", "100.00"))
    ledger.receive("P1", "acme", "100.00", date(2026, 1, 20))
    assert ledger.invoices["INV-2"].status == "paid"
    assert ledger.invoices["INV-10"].status == "open"


def test_number_key_sorts_digit_runs_numerically():
    assert _number_key("INV-2") < _number_key("INV-10")


def test_partial_payment_leaves_the_balance_open():
    ledger = ledger_with(invoice())
    ledger.receive("P1", "acme", "30.00", date(2026, 1, 20))
    assert ledger.invoices["INV-1"].status == "open"
    assert ledger.invoices["INV-1"].balance == D("70.00")


def test_overpayment_becomes_credit():
    ledger = ledger_with(invoice("INV-1", "100.00"))
    payment = ledger.receive("P1", "acme", "150.00", date(2026, 1, 20))
    assert ledger.invoices["INV-1"].status == "paid"
    assert payment.credit == D("50.00")
    assert ledger.credit("acme") == D("50.00")


def test_payment_with_nothing_owed_is_all_credit():
    ledger = Ledger()
    payment = ledger.receive("P1", "acme", "40", date(2026, 1, 20))
    assert payment.credit == D("40.00")
    assert ledger.credit("acme") == D("40.00")


@pytest.mark.parametrize("amount", ["0", "-5.00"])
def test_payment_must_be_positive(amount):
    ledger = ledger_with(invoice())
    with pytest.raises(PaymentError):
        ledger.receive("P1", "acme", amount, date(2026, 1, 20))


def test_repeating_a_payment_changes_nothing_and_returns_the_original():
    ledger = ledger_with(invoice())
    first = ledger.receive("P1", "acme", "40.00", date(2026, 1, 20))
    again = ledger.receive("P1", "acme", "40.00", date(2026, 1, 20))
    assert again is first
    assert ledger.invoices["INV-1"].paid == D("40.00")
    assert [event.kind for event in ledger.events].count("payment") == 1


@pytest.mark.parametrize("customer, amount", [("beta", "40.00"), ("acme", "41.00")])
def test_reusing_a_payment_id_for_another_customer_or_amount_is_refused(customer, amount):
    ledger = ledger_with(invoice())
    ledger.receive("P1", "acme", "40.00", date(2026, 1, 20))
    with pytest.raises(PaymentError):
        ledger.receive("P1", customer, amount, date(2026, 1, 21))


@pytest.mark.parametrize("state", ["draft", "void", "disputed", "paid"])
def test_only_open_invoices_take_payments(state):
    ledger = Ledger()
    item = ledger.add(invoice())
    if state != "draft":
        ledger.issue("INV-1")
    if state == "void":
        ledger.void("INV-1", date(2026, 1, 6))
    if state == "disputed":
        ledger.dispute("INV-1")
    if state == "paid":
        ledger.receive("P0", "acme", "100.00", date(2026, 1, 6))
    ledger.receive("P1", "acme", "50.00", date(2026, 1, 20))
    assert ledger.credit("acme") == D("50.00")
    assert item.paid == (D("100.00") if state == "paid" else D("0"))


# -- early-payment discount ---------------------------------------------------


def test_early_discount_is_granted_when_a_payment_settles_the_invoice_by_the_deadline():
    ledger = ledger_with(invoice("INV-1", "100.00", terms="2/10 NET 30"))
    ledger.receive("P1", "acme", "98.00", date(2026, 1, 15))
    item = ledger.invoices["INV-1"]
    assert item.status == "paid"
    assert item.discount_taken == D("2.00")
    assert [(e.kind, e.amount) for e in ledger.events[1:]] == [
        ("payment", D("-98.00")),
        ("discount", D("-2.00")),
    ]


def test_early_discount_is_not_granted_after_the_deadline():
    ledger = ledger_with(invoice("INV-1", "100.00", terms="2/10 NET 30"))
    ledger.receive("P1", "acme", "98.00", date(2026, 1, 16))
    item = ledger.invoices["INV-1"]
    assert item.discount_taken == D("0.00")
    assert item.status == "open"
    assert item.balance == D("2.00")


def test_early_discount_needs_the_money_to_cover_the_balance_less_the_discount():
    ledger = ledger_with(invoice("INV-1", "100.00", terms="2/10 NET 30"))
    ledger.receive("P1", "acme", "50.00", date(2026, 1, 10))
    item = ledger.invoices["INV-1"]
    assert item.discount_taken == D("0.00")
    assert item.balance == D("50.00")


def test_early_discount_is_not_granted_once_an_earlier_payment_exists():
    ledger = ledger_with(invoice("INV-1", "100.00", terms="2/10 NET 30"))
    ledger.receive("P1", "acme", "50.00", date(2026, 1, 10))
    ledger.receive("P2", "acme", "48.00", date(2026, 1, 12))
    item = ledger.invoices["INV-1"]
    assert item.discount_taken == D("0.00")
    assert item.balance == D("2.00")


def test_early_discount_is_on_net_so_tax_is_still_owed():
    ledger = ledger_with(invoice("INV-1", "100.00", terms="2/10 NET 30", tax_rate=10))
    ledger.receive("P1", "acme", "108.00", date(2026, 1, 15))
    item = ledger.invoices["INV-1"]
    assert item.status == "paid"
    assert item.discount_taken == D("2.00")


def test_early_discount_is_not_granted_when_tax_is_not_covered():
    ledger = ledger_with(invoice("INV-1", "100.00", terms="2/10 NET 30", tax_rate=10))
    ledger.receive("P1", "acme", "107.00", date(2026, 1, 15))
    item = ledger.invoices["INV-1"]
    assert item.discount_taken == D("0.00")
    assert item.balance == D("3.00")


# -- apply_credit -------------------------------------------------------------


def test_apply_credit_pays_open_invoices_and_logs_no_event():
    ledger = Ledger()
    ledger.receive("P0", "acme", "50.00", date(2026, 1, 6))
    ledger.add(invoice("INV-1", "30.00"))
    ledger.issue("INV-1")
    events_before = len(ledger.events)
    allocations = ledger.apply_credit("acme", date(2026, 1, 10))
    assert [(a.invoice, a.principal) for a in allocations] == [("INV-1", D("30.00"))]
    assert ledger.credit("acme") == D("20.00")
    assert ledger.invoices["INV-1"].status == "paid"
    assert len(ledger.events) == events_before


def test_apply_credit_never_earns_the_early_discount():
    ledger = Ledger()
    ledger.receive("P0", "acme", "98.00", date(2026, 1, 6))
    ledger.add(invoice("INV-1", "100.00", terms="2/10 NET 30"))
    ledger.issue("INV-1")
    allocations = ledger.apply_credit("acme", date(2026, 1, 10))
    item = ledger.invoices["INV-1"]
    assert allocations[0].discount == D("0.00")
    assert item.discount_taken == D("0.00")
    assert item.balance == D("2.00")
    assert ledger.credit("acme") == D("0.00")


def test_apply_credit_with_no_credit_does_nothing():
    assert Ledger().apply_credit("acme", date(2026, 1, 10)) == []


# -- reversals ----------------------------------------------------------------


def test_reversal_restores_principal_and_the_credit_it_left():
    ledger = ledger_with(invoice("INV-1", "100.00"))
    ledger.receive("P1", "acme", "150.00", date(2026, 1, 20))
    ledger.reverse("P1", date(2026, 1, 21))
    item = ledger.invoices["INV-1"]
    assert item.status == "open"
    assert item.balance == D("100.00")
    assert ledger.credit("acme") == D("0.00")
    assert ledger.events[-1] == Event(date(2026, 1, 21), "acme", "reversal", "P1", D("150.00"))


def test_reversal_restores_late_fees_that_were_paid():
    ledger = ledger_with(invoice("INV-1", "1000.00"))
    ledger.assess_late_fees(date(2026, 2, 20))
    ledger.receive("P1", "acme", "1015.00", date(2026, 2, 21))
    ledger.reverse("P1", date(2026, 2, 22))
    item = ledger.invoices["INV-1"]
    assert item.fees_paid == D("0.00")
    assert item.paid == D("0.00")
    assert item.balance == D("1015.00")
    assert ledger.events[-1].amount == D("1015.00")


def test_reversal_of_a_discounted_payment_logs_the_amount_restored_with_the_discount():
    ledger = ledger_with(invoice("INV-1", "100.00", terms="2/10 NET 30"))
    ledger.receive("P1", "acme", "98.00", date(2026, 1, 15))
    ledger.reverse("P1", date(2026, 1, 16))
    assert ledger.events[-1] == Event(date(2026, 1, 16), "acme", "reversal", "P1", D("100.00"))


@pytest.mark.xfail(strict=True, reason="R4.8: reversing a payment must also undo the discount it earned")
def test_reversal_of_a_discounted_payment_restores_the_full_balance():
    ledger = ledger_with(invoice("INV-1", "100.00", terms="2/10 NET 30"))
    ledger.receive("P1", "acme", "98.00", date(2026, 1, 15))
    ledger.reverse("P1", date(2026, 1, 16))
    item = ledger.invoices["INV-1"]
    assert item.discount_taken == D("0.00")
    assert item.balance == D("100.00")


def test_payment_cannot_be_reversed_after_its_credit_is_used():
    ledger = ledger_with(invoice("INV-1", "100.00"))
    ledger.receive("P1", "acme", "150.00", date(2026, 1, 20))
    ledger.add(invoice("INV-2", "30.00"))
    ledger.issue("INV-2")
    ledger.apply_credit("acme", date(2026, 1, 21))
    with pytest.raises(PaymentError):
        ledger.reverse("P1", date(2026, 1, 22))
    assert ledger.credit("acme") == D("20.00")
    assert ledger.payments["P1"].reversed is False
    assert ledger.invoices["INV-1"].paid == D("100.00")


def test_reversal_refuses_unknown_and_repeated_payments_and_the_id_stays_dead():
    ledger = ledger_with(invoice())
    with pytest.raises(PaymentError):
        ledger.reverse("nope", date(2026, 1, 21))
    ledger.receive("P1", "acme", "40.00", date(2026, 1, 20))
    ledger.reverse("P1", date(2026, 1, 21))
    with pytest.raises(PaymentError):
        ledger.reverse("P1", date(2026, 1, 22))
    with pytest.raises(PaymentError):
        ledger.receive("P1", "acme", "40.00", date(2026, 1, 23))


# -- voids --------------------------------------------------------------------


def test_void_writes_off_the_balance_including_late_fees_as_one_event():
    ledger = ledger_with(invoice("INV-1", "100.00"))
    ledger.assess_late_fees(date(2026, 2, 10))  # six days late: one fee of 5.00
    ledger.void("INV-1", date(2026, 2, 11))
    assert ledger.events[-1] == Event(date(2026, 2, 11), "acme", "void", "INV-1", D("-105.00"))
    assert ledger.invoices["INV-1"].status == "void"


def test_void_is_refused_after_a_payment():
    ledger = ledger_with(invoice("INV-1", "100.00"))
    ledger.receive("P1", "acme", "10.00", date(2026, 1, 20))
    with pytest.raises(InvoiceError):
        ledger.void("INV-1", date(2026, 1, 21))
