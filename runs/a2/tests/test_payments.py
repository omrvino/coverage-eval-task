from datetime import date, timedelta
from decimal import Decimal as D

import pytest

from tally import Invoice, Ledger, Line, PaymentError

DAY = date(2026, 1, 5)  # NET 30 invoices from here are due Feb 4


def invoice(number="INV-1", price="100.00", terms="NET 30", day=DAY, customer="acme", tax_rate=0):
    return Invoice(number, customer, day, terms, [Line("work", 1, price)], tax_rate=tax_rate)


def ledger_with(*invoices):
    ledger = Ledger()
    for item in invoices:
        ledger.add(item)
        ledger.issue(item.number)
    return ledger


def kind(ledger, name):
    return [e for e in ledger.events if e.kind == name]


# R4.1
def test_payment_goes_to_earliest_due_date_first():
    early = invoice("INV-B", day=date(2026, 1, 20), terms="NET 10")  # due Jan 30
    late = invoice("INV-A")  # due Feb 4
    ledger = ledger_with(late, early)
    ledger.receive("P1", "acme", "100", date(2026, 1, 25))
    assert ledger.invoices["INV-B"].status == "paid"
    assert ledger.invoices["INV-A"].status == "open"


def test_equal_due_dates_go_in_invoice_number_order():
    ledger = ledger_with(invoice("INV-2"), invoice("INV-1"))
    ledger.receive("P1", "acme", "100", date(2026, 1, 20))
    assert ledger.invoices["INV-1"].status == "paid"
    assert ledger.invoices["INV-2"].status == "open"


@pytest.mark.xfail(strict=True, reason="equal due dates sort invoice numbers as text, so INV-10 is paid before INV-2; spec R4.1 says digit runs compare as numbers")
def test_digit_runs_in_invoice_numbers_compare_as_numbers():
    ledger = ledger_with(invoice("INV-10"), invoice("INV-2"))
    ledger.receive("P1", "acme", "100", date(2026, 1, 20))
    assert ledger.invoices["INV-2"].status == "paid"
    assert ledger.invoices["INV-10"].status == "open"


# R4.2
def test_late_fees_are_paid_before_principal():
    ledger = ledger_with(invoice(price="1000.00"))
    due = ledger.invoices["INV-1"].due
    ledger.assess_late_fees(due + timedelta(days=6))  # 15.00 fee
    ledger.receive("P1", "acme", "15.00", due + timedelta(days=7))
    assert ledger.invoices["INV-1"].balance == D("1000.00")
    ledger.receive("P2", "acme", "1.00", due + timedelta(days=8))
    assert ledger.invoices["INV-1"].balance == D("999.00")


# R4.3
def discount_ledger(tax_rate=0):
    return ledger_with(invoice(terms="2/10 NET 30", tax_rate=tax_rate))  # net 100.00, deadline Jan 15


@pytest.mark.parametrize("paid_on", [DAY, date(2026, 1, 15)])
def test_discount_is_granted_on_or_before_the_deadline(paid_on):
    ledger = discount_ledger(tax_rate="10")  # total 110.00
    ledger.receive("P1", "acme", "108", paid_on)
    assert ledger.invoices["INV-1"].status == "paid"
    assert [e.amount for e in kind(ledger, "discount")] == [D("-2.00")]
    assert ledger.credit("acme") == 0


def test_discount_is_percent_of_net_not_of_total():
    ledger = discount_ledger(tax_rate="10")
    ledger.receive("P1", "acme", "108", date(2026, 1, 10))
    assert [e.amount for e in kind(ledger, "discount")] == [D("-2.00")]


def test_no_discount_after_the_deadline():
    ledger = discount_ledger(tax_rate="10")
    ledger.receive("P1", "acme", "108", date(2026, 1, 16))
    assert kind(ledger, "discount") == []
    assert ledger.invoices["INV-1"].balance == D("2.00")


def test_no_discount_when_money_falls_short_of_balance_less_discount():
    ledger = discount_ledger(tax_rate="10")
    ledger.receive("P1", "acme", "107.99", date(2026, 1, 10))
    assert kind(ledger, "discount") == []
    assert ledger.invoices["INV-1"].balance == D("2.01")
    assert ledger.invoices["INV-1"].status == "open"


def test_no_discount_when_an_earlier_payment_is_on_the_invoice():
    ledger = discount_ledger(tax_rate="10")
    ledger.receive("P1", "acme", "50", DAY)
    ledger.receive("P2", "acme", "60", DAY)
    assert kind(ledger, "discount") == []
    assert ledger.invoices["INV-1"].status == "paid"


def test_net_only_terms_never_give_a_discount():
    ledger = ledger_with(invoice())
    ledger.receive("P1", "acme", "100", DAY)
    assert kind(ledger, "discount") == []


def test_discount_still_granted_on_a_weekend_deadline_day():
    # Jan 8 + 10 days is Sunday Jan 18; a payment that day is inside the window
    ledger = ledger_with(invoice(day=date(2026, 1, 8), terms="2/10 NET 30"))
    ledger.receive("P1", "acme", "98", date(2026, 1, 18))
    assert [e.amount for e in kind(ledger, "discount")] == [D("-2.00")]


@pytest.mark.xfail(strict=True, reason="early-payment deadline on a weekend rolls to Monday Jan 19; spec R2.4 says it does not move")
def test_payment_on_the_monday_after_a_weekend_deadline_gets_no_discount():
    ledger = ledger_with(invoice(day=date(2026, 1, 8), terms="2/10 NET 30"))
    ledger.receive("P1", "acme", "98", date(2026, 1, 19))
    assert kind(ledger, "discount") == []
    assert ledger.invoices["INV-1"].balance == D("2.00")


# R4.4
def test_money_left_over_becomes_credit():
    ledger = ledger_with(invoice())
    ledger.receive("P1", "acme", "150", date(2026, 1, 20))
    assert ledger.invoices["INV-1"].status == "paid"
    assert ledger.credit("acme") == D("50.00")


def test_payment_with_nothing_open_is_all_credit():
    ledger = Ledger()
    ledger.receive("P1", "acme", "60", DAY)
    assert ledger.credit("acme") == D("60.00")


# R4.5
def test_repeated_payment_id_returns_the_original_and_changes_nothing():
    ledger = ledger_with(invoice())
    first = ledger.receive("P1", "acme", "100", DAY)
    events = len(ledger.events)
    again = ledger.receive("P1", "acme", "100", date(2026, 1, 20))
    assert again == first
    assert len(ledger.events) == events


@pytest.mark.parametrize("customer, amount", [("other", "100"), ("acme", "99")])
def test_repeated_payment_id_with_other_customer_or_amount_raises(customer, amount):
    ledger = ledger_with(invoice())
    ledger.receive("P1", "acme", "100", DAY)
    with pytest.raises(PaymentError):
        ledger.receive("P1", customer, amount, DAY)


# R4.6
@pytest.mark.parametrize("amount", ["0", "-5"])
def test_payment_must_be_more_than_zero(amount):
    ledger = ledger_with(invoice())
    with pytest.raises(PaymentError):
        ledger.receive("P1", "acme", amount, DAY)
    assert kind(ledger, "payment") == []
    assert ledger.credit("acme") == 0


# R4.7
def make_draft(ledger):
    ledger.add(invoice())


def make_issued(ledger):
    ledger.add(invoice())
    ledger.issue("INV-1")


def make_void(ledger):
    make_issued(ledger)
    ledger.void("INV-1", DAY)


def make_paid(ledger):
    make_issued(ledger)
    ledger.receive("PX", "acme", "100", DAY)


def make_disputed(ledger):
    make_issued(ledger)
    ledger.dispute("INV-1")


@pytest.mark.parametrize("setup", [make_draft, make_void, make_paid, make_disputed],
                         ids=["draft", "void", "paid", "disputed"])
def test_draft_void_paid_and_disputed_invoices_receive_nothing(setup):
    ledger = Ledger()
    setup(ledger)
    before = ledger.invoices["INV-1"].balance
    ledger.receive("P9", "acme", "40", date(2026, 1, 20))
    assert ledger.invoices["INV-1"].balance == before
    assert ledger.credit("acme") == D("40.00")


# R4.8
def test_reverse_restores_principal_and_the_credit_left():
    ledger = ledger_with(invoice())
    ledger.receive("P1", "acme", "150", DAY)
    ledger.reverse("P1", date(2026, 1, 6))
    assert ledger.invoices["INV-1"].status == "open"
    assert ledger.invoices["INV-1"].balance == D("100.00")
    assert ledger.credit("acme") == 0


def test_reverse_restores_late_fees_paid():
    ledger = ledger_with(invoice(price="1000.00"))
    due = ledger.invoices["INV-1"].due
    ledger.assess_late_fees(due + timedelta(days=6))
    ledger.receive("P1", "acme", "1015", due + timedelta(days=7))
    assert ledger.invoices["INV-1"].status == "paid"
    ledger.reverse("P1", due + timedelta(days=8))
    assert ledger.invoices["INV-1"].balance == D("1015.00")


def test_reverse_logs_one_reversal_event_for_the_amount_restored():
    ledger = ledger_with(invoice())
    ledger.receive("P1", "acme", "100", DAY)
    ledger.reverse("P1", date(2026, 1, 6))
    reversals = kind(ledger, "reversal")
    assert len(reversals) == 1
    assert reversals[0].amount == D("100.00")
    assert reversals[0].date == date(2026, 1, 6)


@pytest.mark.xfail(strict=True, reason="reverse() does not restore the early-payment discount, so the invoice is still short by it; spec R4.8 says the discount is undone")
def test_reverse_restores_the_early_payment_discount_to_the_invoice():
    ledger = ledger_with(invoice(terms="2/10 NET 30"))
    ledger.receive("P1", "acme", "98", date(2026, 1, 10))
    ledger.reverse("P1", date(2026, 1, 11))
    assert ledger.invoices["INV-1"].balance == D("100.00")
    assert ledger.invoices["INV-1"].status == "open"


def test_reverse_unknown_or_already_reversed_payment_raises():
    ledger = ledger_with(invoice())
    with pytest.raises(PaymentError):
        ledger.reverse("NOPE", DAY)
    ledger.receive("P1", "acme", "100", DAY)
    ledger.reverse("P1", DAY)
    with pytest.raises(PaymentError):
        ledger.reverse("P1", DAY)


def test_reversed_payment_id_cannot_be_received_again():
    ledger = ledger_with(invoice())
    ledger.receive("P1", "acme", "100", DAY)
    ledger.reverse("P1", DAY)
    with pytest.raises(PaymentError):
        ledger.receive("P1", "acme", "100", DAY)


# R4.9
def test_payment_cannot_be_reversed_once_its_credit_is_used():
    ledger = ledger_with(invoice())
    ledger.receive("P1", "acme", "150", DAY)  # leaves 50 credit
    ledger.add(invoice("INV-2", price="60", day=date(2026, 1, 22)))
    ledger.issue("INV-2")
    ledger.apply_credit("acme", date(2026, 1, 22))  # uses the 50
    with pytest.raises(PaymentError):
        ledger.reverse("P1", date(2026, 1, 23))
    assert ledger.invoices["INV-1"].status == "paid"
    assert ledger.invoices["INV-2"].balance == D("10.00")
    assert ledger.credit("acme") == 0


# R4.10
def test_apply_credit_uses_earliest_due_first():
    ledger = ledger_with(invoice("INV-0"))
    ledger.receive("P0", "acme", "150", DAY)  # credit 50
    ledger.add(invoice("INV-A", day=DAY))  # due Feb 4
    ledger.issue("INV-A")
    ledger.add(invoice("INV-B", day=date(2026, 1, 20), terms="NET 10"))  # due Jan 30
    ledger.issue("INV-B")
    ledger.apply_credit("acme", date(2026, 1, 25))
    assert ledger.invoices["INV-B"].balance == D("50.00")
    assert ledger.invoices["INV-A"].balance == D("100.00")
    assert ledger.credit("acme") == 0


def test_apply_credit_never_earns_an_early_payment_discount_and_logs_nothing():
    ledger = ledger_with(invoice("INV-0"))
    ledger.receive("P0", "acme", "200", DAY)  # credit 100
    ledger.add(invoice("INV-2", terms="2/10 NET 30"))
    ledger.issue("INV-2")
    events = len(ledger.events)
    ledger.apply_credit("acme", date(2026, 1, 6))
    assert kind(ledger, "discount") == []
    assert len(ledger.events) == events
    assert ledger.invoices["INV-2"].status == "paid"
    assert ledger.invoices["INV-2"].balance == D("0.00")


def test_apply_credit_leaves_unused_credit_in_place():
    ledger = ledger_with(invoice("INV-0"))
    ledger.receive("P0", "acme", "150", DAY)  # credit 50
    ledger.add(invoice("INV-2", price="30"))
    ledger.issue("INV-2")
    ledger.apply_credit("acme", DAY)
    assert ledger.invoices["INV-2"].status == "paid"
    assert ledger.credit("acme") == D("20.00")
