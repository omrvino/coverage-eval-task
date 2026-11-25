from datetime import date, timedelta
from decimal import Decimal

import pytest

from tally import Invoice, Ledger, Line, PaymentError

D = Decimal
DISCOUNT = "2/10 NET 30"

XFAIL_NUMBER_ORDER = pytest.mark.xfail(
    strict=True,
    reason="R4.1: equal due dates sort as text, so INV-10 is paid before INV-2; the spec compares digit runs as numbers",
)
XFAIL_DEADLINE_WEEKEND = pytest.mark.xfail(
    strict=True,
    reason="R2.4: a discount deadline on a weekend is rolled forward, so a Monday payment still gets the discount",
)
XFAIL_REVERSE_DISCOUNT = pytest.mark.xfail(
    strict=True,
    reason="R4.8: reverse() restores the principal but not the discount, so the balance stays short by the discount",
)


def invoice(number="INV-1", *, day=date(2026, 1, 5), terms="NET 30", price="100.00", tax_rate="0", customer="acme"):
    return Invoice(number, customer, day, terms, [Line("work", 1, price)], tax_rate=tax_rate)


def ledger_with(*invoices):
    ledger = Ledger()
    for item in invoices:
        ledger.add(item)
        ledger.issue(item.number)
    return ledger


def test_payment_closes_the_invoice_and_logs_one_payment_event():
    ledger = ledger_with(invoice())
    ledger.receive("P1", "acme", "100.00", date(2026, 1, 20))
    assert ledger.invoices["INV-1"].status == "paid"
    assert [event.kind for event in ledger.events] == ["invoice", "payment"]
    assert ledger.events[-1].amount == D("-100.00")


def test_payment_goes_to_the_earliest_due_date_first():
    ledger = ledger_with(invoice("INV-1", day=date(2026, 1, 20)), invoice("INV-2", day=date(2026, 1, 5)))
    # INV-2 is due Feb 4, INV-1 is due Feb 19.
    ledger.receive("P1", "acme", "150.00", date(2026, 1, 25))
    assert ledger.invoices["INV-2"].status == "paid"
    assert ledger.invoices["INV-1"].paid == D("50.00")


def test_equal_due_dates_go_in_invoice_number_order():
    ledger = ledger_with(invoice("INV-B"), invoice("INV-A"))
    ledger.receive("P1", "acme", "100.00", date(2026, 1, 25))
    assert ledger.invoices["INV-A"].status == "paid"
    assert ledger.invoices["INV-B"].status == "open"


@XFAIL_NUMBER_ORDER
def test_digit_runs_in_invoice_numbers_compare_as_numbers():
    ledger = ledger_with(invoice("INV-10"), invoice("INV-2"))
    ledger.receive("P1", "acme", "100.00", date(2026, 1, 25))
    assert ledger.invoices["INV-2"].status == "paid"
    assert ledger.invoices["INV-10"].status == "open"


def test_late_fees_are_paid_before_principal():
    ledger = ledger_with(invoice())
    ledger.assess_late_fees(date(2026, 2, 10))
    inv = ledger.invoices["INV-1"]
    assert inv.fees == D("5.00")
    ledger.receive("P1", "acme", "5.00", date(2026, 2, 10))
    assert inv.fees_due == 0
    assert inv.principal_due == D("100.00")
    ledger.receive("P2", "acme", "50.00", date(2026, 2, 10))
    assert inv.principal_due == D("50.00")


def test_early_discount_applies_on_the_deadline_day():
    ledger = ledger_with(invoice(terms=DISCOUNT))
    payment = ledger.receive("P1", "acme", "98.00", date(2026, 1, 15))
    inv = ledger.invoices["INV-1"]
    assert inv.status == "paid"
    assert inv.discount_taken == D("2.00")
    assert payment.allocations[0].discount == D("2.00")
    assert (ledger.events[-1].kind, ledger.events[-1].amount) == ("discount", D("-2.00"))


def test_no_early_discount_after_the_deadline_day():
    ledger = ledger_with(invoice(terms=DISCOUNT))
    ledger.receive("P1", "acme", "98.00", date(2026, 1, 16))
    inv = ledger.invoices["INV-1"]
    assert inv.status == "open"
    assert inv.discount_taken == 0
    assert inv.principal_due == D("2.00")


def test_early_discount_needs_the_money_to_cover_the_balance_less_the_discount():
    ledger = ledger_with(invoice(terms=DISCOUNT))
    ledger.receive("P1", "acme", "97.99", date(2026, 1, 10))
    inv = ledger.invoices["INV-1"]
    assert inv.discount_taken == 0
    assert inv.principal_due == D("2.01")


def test_early_discount_is_not_given_when_an_earlier_payment_exists():
    ledger = ledger_with(invoice(terms=DISCOUNT))
    ledger.receive("P1", "acme", "50.00", date(2026, 1, 6))
    ledger.receive("P2", "acme", "50.00", date(2026, 1, 7))
    inv = ledger.invoices["INV-1"]
    assert inv.status == "paid"
    assert inv.discount_taken == 0
    assert [event.kind for event in ledger.events] == ["invoice", "payment", "payment"]


def test_early_discount_is_a_percentage_of_the_net_before_tax():
    ledger = ledger_with(invoice(terms=DISCOUNT, tax_rate="10"))  # net 100.00, total 110.00
    ledger.receive("P1", "acme", "108.00", date(2026, 1, 10))
    inv = ledger.invoices["INV-1"]
    assert inv.status == "paid"
    assert inv.discount_taken == D("2.00")


def test_early_discount_is_rounded_to_the_cent():
    ledger = ledger_with(invoice(terms=DISCOUNT, price="33.33"))  # 2% is 0.6666
    ledger.receive("P1", "acme", "32.66", date(2026, 1, 10))
    inv = ledger.invoices["INV-1"]
    assert inv.status == "paid"
    assert inv.discount_taken == D("0.67")


@XFAIL_DEADLINE_WEEKEND
def test_discount_deadline_on_a_weekend_does_not_move():
    # Invoice Jan 7: the deadline is Saturday Jan 17. Paying on Monday Jan 19 is too late.
    ledger = ledger_with(invoice(day=date(2026, 1, 7), terms=DISCOUNT))
    ledger.receive("P1", "acme", "98.00", date(2026, 1, 19))
    inv = ledger.invoices["INV-1"]
    assert inv.status == "open"
    assert inv.discount_taken == 0


def test_discount_on_a_weekend_deadline_is_granted_on_that_day():
    ledger = ledger_with(invoice(day=date(2026, 1, 7), terms=DISCOUNT))
    ledger.receive("P1", "acme", "98.00", date(2026, 1, 17))
    assert ledger.invoices["INV-1"].discount_taken == D("2.00")


def test_overpayment_becomes_the_customers_credit():
    ledger = ledger_with(invoice())
    ledger.receive("P1", "acme", "150.00", date(2026, 1, 20))
    assert ledger.invoices["INV-1"].status == "paid"
    assert ledger.credit("acme") == D("50.00")


def test_payment_with_nothing_owed_becomes_all_credit():
    ledger = Ledger()
    ledger.receive("P1", "acme", "40.00", date(2026, 1, 20))
    assert ledger.credit("acme") == D("40.00")
    assert ledger.credit("nobody") == 0


def test_repeating_a_payment_id_with_the_same_details_changes_nothing():
    ledger = ledger_with(invoice())
    first = ledger.receive("P1", "acme", "60.00", date(2026, 1, 20))
    events = len(ledger.events)
    again = ledger.receive("P1", "acme", "60.00", date(2026, 1, 21))
    assert again == first
    assert len(ledger.events) == events
    assert ledger.invoices["INV-1"].paid == D("60.00")
    assert ledger.credit("acme") == 0


@pytest.mark.parametrize("customer, amount", [("acme", "61.00"), ("beta", "60.00")])
def test_reused_payment_id_with_other_details_is_refused(customer, amount):
    ledger = ledger_with(invoice())
    ledger.receive("P1", "acme", "60.00", date(2026, 1, 20))
    with pytest.raises(PaymentError):
        ledger.receive("P1", customer, amount, date(2026, 1, 21))
    assert ledger.invoices["INV-1"].paid == D("60.00")
    assert len(ledger.events) == 2


@pytest.mark.parametrize("amount", ["0", "0.00", "-5.00"])
def test_payment_must_be_more_than_zero(amount):
    ledger = ledger_with(invoice())
    with pytest.raises(PaymentError):
        ledger.receive("P1", "acme", amount, date(2026, 1, 20))
    assert len(ledger.events) == 1


def test_draft_void_paid_and_disputed_invoices_receive_nothing():
    ledger = Ledger()
    ledger.add(invoice("INV-P", day=date(2025, 12, 1)))
    ledger.issue("INV-P")
    ledger.receive("P0", "acme", "100.00", date(2025, 12, 2))  # pays INV-P in full
    ledger.add(invoice("INV-D"))  # draft, never issued
    ledger.add(invoice("INV-V"))
    ledger.issue("INV-V")
    ledger.void("INV-V", date(2026, 1, 6))
    ledger.add(invoice("INV-X"))
    ledger.issue("INV-X")
    ledger.dispute("INV-X")

    ledger.receive("P1", "acme", "25.00", date(2026, 1, 7))

    assert ledger.invoices["INV-D"].status == "draft"
    assert ledger.invoices["INV-V"].status == "void"
    assert ledger.invoices["INV-P"].status == "paid"
    assert ledger.invoices["INV-X"].paid == 0
    assert ledger.credit("acme") == D("25.00")


def test_reverse_restores_the_principal_and_logs_one_reversal_event():
    ledger = ledger_with(invoice())
    ledger.receive("P1", "acme", "60.00", date(2026, 1, 20))
    ledger.reverse("P1", date(2026, 1, 22))
    inv = ledger.invoices["INV-1"]
    assert inv.principal_due == D("100.00")
    assert inv.status == "open"
    reversals = [event for event in ledger.events if event.kind == "reversal"]
    assert [(e.date, e.ref, e.amount) for e in reversals] == [(date(2026, 1, 22), "P1", D("60.00"))]
    assert ledger.credit("acme") == 0


def test_reverse_restores_late_fees_that_were_paid():
    ledger = ledger_with(invoice())
    ledger.assess_late_fees(date(2026, 2, 10))  # fee 5.00
    ledger.receive("P1", "acme", "55.00", date(2026, 2, 10))  # 5.00 fee, 50.00 principal
    ledger.reverse("P1", date(2026, 2, 11))
    inv = ledger.invoices["INV-1"]
    assert inv.fees_due == D("5.00")
    assert inv.principal_due == D("100.00")


def test_reverse_gives_back_the_credit_the_payment_left():
    ledger = ledger_with(invoice())
    ledger.receive("P1", "acme", "150.00", date(2026, 1, 20))
    ledger.reverse("P1", date(2026, 1, 21))
    assert ledger.credit("acme") == 0
    assert ledger.invoices["INV-1"].status == "open"
    reversal = [event for event in ledger.events if event.kind == "reversal"][0]
    assert reversal.amount == D("150.00")


def test_reversal_event_includes_the_discount_the_payment_earned():
    ledger = ledger_with(invoice(terms=DISCOUNT))
    ledger.receive("P1", "acme", "98.00", date(2026, 1, 10))
    ledger.reverse("P1", date(2026, 1, 11))
    reversal = [event for event in ledger.events if event.kind == "reversal"][0]
    assert reversal.amount == D("100.00")  # 98.00 paid plus 2.00 discount


@XFAIL_REVERSE_DISCOUNT
def test_reverse_undoes_the_early_payment_discount():
    ledger = ledger_with(invoice(terms=DISCOUNT))
    ledger.receive("P1", "acme", "98.00", date(2026, 1, 10))
    ledger.reverse("P1", date(2026, 1, 11))
    inv = ledger.invoices["INV-1"]
    assert inv.status == "open"
    assert inv.balance == D("100.00")
    reversal = [event for event in ledger.events if event.kind == "reversal"][0]
    assert reversal.amount == D("100.00")


def test_reversed_payment_cannot_be_reversed_again_or_received_again():
    ledger = ledger_with(invoice())
    ledger.receive("P1", "acme", "60.00", date(2026, 1, 20))
    ledger.reverse("P1", date(2026, 1, 21))
    events = len(ledger.events)
    with pytest.raises(PaymentError):
        ledger.reverse("P1", date(2026, 1, 22))
    with pytest.raises(PaymentError):
        ledger.receive("P1", "acme", "60.00", date(2026, 1, 22))
    with pytest.raises(PaymentError):
        ledger.reverse("NOPE", date(2026, 1, 22))
    assert len(ledger.events) == events
    assert ledger.invoices["INV-1"].status == "open"


def test_payment_cannot_be_reversed_once_its_credit_has_been_used():
    ledger = ledger_with(invoice("INV-1"))
    ledger.receive("P1", "acme", "150.00", date(2026, 1, 20))  # leaves 50.00 credit
    ledger.add(invoice("INV-2", day=date(2026, 1, 21)))
    ledger.issue("INV-2")
    ledger.apply_credit("acme", date(2026, 1, 22))  # uses the 50.00
    events = len(ledger.events)
    with pytest.raises(PaymentError):
        ledger.reverse("P1", date(2026, 1, 23))
    assert ledger.invoices["INV-1"].status == "paid"
    assert ledger.invoices["INV-2"].paid == D("50.00")
    assert len(ledger.events) == events


def test_apply_credit_pays_the_earliest_due_invoice_first():
    ledger = ledger_with(invoice("INV-1"))
    ledger.receive("P1", "acme", "150.00", date(2026, 1, 20))  # leaves 50.00 credit
    ledger.add(invoice("INV-B", day=date(2026, 1, 21), price="30.00"))  # due Feb 20
    ledger.issue("INV-B")
    ledger.add(invoice("INV-A", day=date(2026, 1, 25), price="30.00"))  # due Feb 24
    ledger.issue("INV-A")

    allocations = ledger.apply_credit("acme", date(2026, 1, 26))

    assert [allocation.invoice for allocation in allocations] == ["INV-B", "INV-A"]
    assert ledger.invoices["INV-B"].status == "paid"
    assert ledger.invoices["INV-A"].paid == D("20.00")
    assert ledger.credit("acme") == 0


def test_apply_credit_never_earns_the_early_payment_discount_and_logs_nothing():
    ledger = ledger_with(invoice("INV-1"))
    ledger.receive("P1", "acme", "150.00", date(2026, 1, 20))  # leaves 50.00 credit
    ledger.add(invoice("INV-2", day=date(2026, 1, 21), price="50.00", terms=DISCOUNT))
    ledger.issue("INV-2")
    events = len(ledger.events)

    ledger.apply_credit("acme", date(2026, 1, 22))  # inside the discount window

    inv = ledger.invoices["INV-2"]
    assert inv.status == "paid"
    assert inv.discount_taken == 0
    assert inv.paid == D("50.00")
    assert len(ledger.events) == events
