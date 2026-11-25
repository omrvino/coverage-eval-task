from datetime import date, timedelta
from decimal import Decimal

import pytest

from tally import Ledger, PaymentError

from helpers import D0, issued, kinds, make_invoice

D = Decimal
DISCOUNT_TERMS = "2/10 NET 30"
# make_invoice(due=D0) is dated Mon 2026-02-02, so the 2/10 deadline is Thu 2026-02-12.
DEADLINE = date(2026, 2, 12)


def snapshot(ledger):
    """Everything a failed or repeated call must leave alone."""
    return (
        [(i.number, i.status, i.balance, i.fees_due, i.disputed) for i in ledger.invoices.values()],
        dict(ledger.credits),
        list(ledger.events),
        sorted(ledger.payments),
    )


# -- R4.1 ------------------------------------------------------------------

def test_payment_goes_to_the_earliest_due_date_first():
    later = make_invoice("INV-1", due=D0 + timedelta(days=7))
    earlier = make_invoice("INV-2", due=D0)
    ledger = issued(later, earlier)
    ledger.receive("P1", "acme", "100.00", D0)
    assert earlier.status == "paid"
    assert later.balance == D("100.00")


def test_payment_spreads_over_several_invoices_in_order():
    a = make_invoice("A", due=D0)
    b = make_invoice("B", due=D0 + timedelta(days=1), price="50.00")
    c = make_invoice("C", due=D0 + timedelta(days=2))
    ledger = issued(c, b, a)
    payment = ledger.receive("P1", "acme", "130.00", D0)
    assert a.balance == D("0.00")
    assert b.balance == D("20.00")
    assert c.balance == D("100.00")
    assert [x.invoice for x in payment.allocations] == ["A", "B"]
    assert [x.principal for x in payment.allocations] == [D("100.00"), D("30.00")]
    assert payment.credit == D("0.00")


def test_equal_due_dates_go_in_invoice_number_order():
    first = make_invoice("INV-1")
    second = make_invoice("INV-3")
    third = make_invoice("INV-5")
    ledger = issued(third, first, second)
    ledger.receive("P1", "acme", "200.00", D0)
    assert first.status == "paid"
    assert second.status == "paid"
    assert third.status == "open"


@pytest.mark.xfail(strict=True, reason="invoice numbers are compared as plain text, not with digit runs as numbers")
def test_equal_due_dates_compare_digit_runs_as_numbers():
    ten = make_invoice("INV-10")
    two = make_invoice("INV-2")
    ledger = issued(ten, two)
    ledger.receive("P1", "acme", "100.00", D0)
    assert two.status == "paid"
    assert ten.status == "open"


def test_payment_only_touches_the_named_customer():
    mine = make_invoice("INV-1", customer="acme")
    theirs = make_invoice("INV-2", customer="other", due=D0 - timedelta(days=7))
    ledger = issued(mine, theirs)
    ledger.receive("P1", "acme", "100.00", D0)
    assert mine.status == "paid"
    assert theirs.balance == D("100.00")


# -- R4.2 ------------------------------------------------------------------

def test_late_fees_are_paid_before_principal():
    inv = make_invoice(price="1000.00")
    ledger = issued(inv)
    ledger.assess_late_fees(D0 + timedelta(days=16))
    payment = ledger.receive("P1", "acme", "100.00", D0 + timedelta(days=16))
    assert payment.allocations[0].fees == D("15.00")
    assert payment.allocations[0].principal == D("85.00")
    assert inv.fees_due == D("0.00")
    assert inv.principal_due == D("915.00")


def test_a_payment_smaller_than_the_fees_pays_only_fees():
    inv = make_invoice(price="1000.00")
    ledger = issued(inv)
    ledger.assess_late_fees(D0 + timedelta(days=16))
    payment = ledger.receive("P1", "acme", "10.00", D0 + timedelta(days=16))
    assert payment.allocations[0].fees == D("10.00")
    assert payment.allocations[0].principal == D("0.00")
    assert inv.fees_due == D("5.00")
    assert inv.principal_due == D("1000.00")


# -- R4.3 ------------------------------------------------------------------

def test_early_payment_discount_on_the_deadline_day():
    inv = make_invoice(terms=DISCOUNT_TERMS)
    ledger = issued(inv)
    payment = ledger.receive("P1", "acme", "98.00", DEADLINE)
    assert inv.status == "paid"
    assert payment.allocations[0].discount == D("2.00")
    assert payment.credit == D("0.00")
    assert ledger.credit("acme") == D("0.00")


def test_no_discount_after_the_deadline():
    inv = make_invoice(terms=DISCOUNT_TERMS)
    ledger = issued(inv)
    payment = ledger.receive("P1", "acme", "98.00", DEADLINE + timedelta(days=1))
    assert payment.allocations[0].discount == D("0.00")
    assert inv.balance == D("2.00")
    assert inv.status == "open"


def test_discount_is_a_percent_of_the_net_before_tax():
    inv = make_invoice(terms=DISCOUNT_TERMS, tax_rate=10)       # net 100, tax 10, total 110
    ledger = issued(inv)
    payment = ledger.receive("P1", "acme", "108.00", DEADLINE)
    assert payment.allocations[0].discount == D("2.00")
    assert inv.status == "paid"


def test_discount_is_rounded_to_the_cent():
    inv = make_invoice(terms=DISCOUNT_TERMS, price="33.33")     # 2% of 33.33 = 0.6666
    ledger = issued(inv)
    payment = ledger.receive("P1", "acme", "32.66", DEADLINE)
    assert payment.allocations[0].discount == D("0.67")
    assert inv.status == "paid"


def test_no_discount_when_the_payment_does_not_cover_the_balance_less_discount():
    inv = make_invoice(terms=DISCOUNT_TERMS)
    ledger = issued(inv)
    payment = ledger.receive("P1", "acme", "97.99", DEADLINE)
    assert payment.allocations[0].discount == D("0.00")
    assert payment.allocations[0].principal == D("97.99")
    assert inv.balance == D("2.01")


def test_discount_needs_the_money_reaching_that_invoice_not_the_whole_payment():
    first = make_invoice("INV-1", terms=DISCOUNT_TERMS, due=D0)
    second = make_invoice("INV-2", terms=DISCOUNT_TERMS, due=D0 + timedelta(days=1))
    ledger = issued(first, second)
    payment = ledger.receive("P1", "acme", "150.00", DEADLINE)
    assert first.status == "paid"
    assert payment.allocations[0].discount == D("2.00")
    # 150 - 98 = 52 reaches the second invoice, which needs 98 for a discount
    assert payment.allocations[1].discount == D("0.00")
    assert second.balance == D("48.00")


def test_discount_on_two_invoices_in_one_payment():
    first = make_invoice("INV-1", terms=DISCOUNT_TERMS, due=D0)
    second = make_invoice("INV-2", terms=DISCOUNT_TERMS, due=D0 + timedelta(days=1))
    ledger = issued(first, second)
    payment = ledger.receive("P1", "acme", "196.00", DEADLINE)
    assert [a.discount for a in payment.allocations] == [D("2.00"), D("2.00")]
    assert first.status == second.status == "paid"
    assert [e.amount for e in kinds(ledger, "discount")] == [D("-2.00"), D("-2.00")]


def test_no_discount_when_the_invoice_already_has_a_payment():
    inv = make_invoice(terms=DISCOUNT_TERMS)
    ledger = issued(inv)
    ledger.receive("P1", "acme", "10.00", DEADLINE - timedelta(days=5))
    payment = ledger.receive("P2", "acme", "90.00", DEADLINE)
    assert payment.allocations[0].discount == D("0.00")
    assert inv.status == "paid"
    assert payment.credit == D("0.00")


def test_discount_is_logged_as_its_own_event():
    ledger = issued(make_invoice(terms=DISCOUNT_TERMS))
    ledger.receive("P1", "acme", "98.00", DEADLINE)
    assert [(e.kind, e.ref, e.amount, e.date) for e in ledger.events[1:]] == [
        ("payment", "P1", D("-98.00"), DEADLINE),
        ("discount", "INV-1", D("-2.00"), DEADLINE),
    ]


def test_terms_without_a_discount_never_give_one():
    inv = make_invoice()
    ledger = issued(inv)
    payment = ledger.receive("P1", "acme", "98.00", D0 - timedelta(days=25))
    assert payment.allocations[0].discount == D("0.00")
    assert inv.balance == D("2.00")


def test_discount_deadline_is_a_calendar_day_even_on_a_weekend_date():
    # dated Wed 2026-02-11: the 10-day deadline is Sat 2026-02-21
    inv = make_invoice(terms=DISCOUNT_TERMS, due=date(2026, 3, 13))
    ledger = issued(inv)
    payment = ledger.receive("P1", "acme", "98.00", date(2026, 2, 21))
    assert payment.allocations[0].discount == D("2.00")


@pytest.mark.xfail(strict=True, reason="discount deadline is rolled past weekends")
def test_no_discount_on_the_working_day_after_a_weekend_deadline():
    inv = make_invoice(terms=DISCOUNT_TERMS, due=date(2026, 3, 13))
    ledger = issued(inv)
    payment = ledger.receive("P1", "acme", "98.00", date(2026, 2, 23))   # Monday
    assert payment.allocations[0].discount == D("0.00")
    assert inv.balance == D("2.00")


@pytest.mark.xfail(strict=True, reason="discount deadline is rolled past holidays")
def test_no_discount_on_the_working_day_after_a_holiday_deadline():
    inv = make_invoice(terms=DISCOUNT_TERMS)
    ledger = issued(inv, holidays=[DEADLINE])
    payment = ledger.receive("P1", "acme", "98.00", DEADLINE + timedelta(days=1))
    assert payment.allocations[0].discount == D("0.00")


# -- R4.4 ------------------------------------------------------------------

def test_leftover_money_becomes_credit():
    inv = make_invoice()
    ledger = issued(inv)
    payment = ledger.receive("P1", "acme", "130.50", D0)
    assert inv.status == "paid"
    assert payment.credit == D("30.50")
    assert ledger.credit("acme") == D("30.50")
    assert ledger.credit("other") == D("0.00")


def test_payment_with_nothing_to_pay_is_all_credit():
    ledger = Ledger()
    payment = ledger.receive("P1", "acme", "20.00", D0)
    assert payment.allocations == []
    assert payment.credit == D("20.00")
    ledger.receive("P2", "acme", "5.25", D0)
    assert ledger.credit("acme") == D("25.25")


def test_payment_fields_and_event():
    ledger = Ledger()
    payment = ledger.receive("P1", "acme", "20", D0)
    assert (payment.id, payment.customer, payment.amount, payment.date) == (
        "P1", "acme", D("20.00"), D0)
    assert not payment.reversed
    assert [(e.kind, e.ref, e.amount, e.customer) for e in ledger.events] == [
        ("payment", "P1", D("-20.00"), "acme")]


def test_payment_amount_is_rounded_like_money():
    ledger = Ledger()
    assert ledger.receive("P1", "acme", "10.004", D0).amount == D("10.00")
    with pytest.raises(PaymentError):
        ledger.receive("P2", "acme", "0.004", D0)
    with pytest.raises(TypeError):
        ledger.receive("P3", "acme", 1.5, D0)


# -- R4.5 / R4.6 -----------------------------------------------------------

def test_repeating_a_payment_changes_nothing_and_returns_the_original():
    ledger = issued(make_invoice())
    first = ledger.receive("P1", "acme", "60.00", D0)
    before = snapshot(ledger)
    again = ledger.receive("P1", "acme", "60", D0 + timedelta(days=3))
    assert again == first
    assert snapshot(ledger) == before
    assert len(kinds(ledger, "payment")) == 1


@pytest.mark.parametrize("customer, amount", [("other", "60.00"), ("acme", "60.01"), ("acme", "6.00")])
def test_same_payment_id_with_something_different_is_an_error(customer, amount):
    ledger = issued(make_invoice())
    ledger.receive("P1", "acme", "60.00", D0)
    before = snapshot(ledger)
    with pytest.raises(PaymentError):
        ledger.receive("P1", customer, amount, D0)
    assert snapshot(ledger) == before


@pytest.mark.parametrize("amount", ["0", "0.00", "-5", "-0.01", 0, -3])
def test_payment_amount_must_be_more_than_zero(amount):
    ledger = issued(make_invoice())
    with pytest.raises(PaymentError):
        ledger.receive("P1", "acme", amount, D0)
    assert ledger.events[1:] == []
    assert ledger.payments == {}


# -- R4.7 ------------------------------------------------------------------

def test_draft_void_paid_and_disputed_invoices_receive_nothing():
    paid = make_invoice("PAID", due=D0 - timedelta(days=21))
    ledger = issued(paid)
    ledger.receive("PP", "acme", "100.00", D0 - timedelta(days=40))
    assert paid.status == "paid"
    draft = make_invoice("DRAFT", due=D0 - timedelta(days=28))
    void = make_invoice("VOID", due=D0 - timedelta(days=14))
    disputed = make_invoice("DISP", due=D0 - timedelta(days=7))
    live = make_invoice("LIVE", due=D0)
    ledger.add(draft)
    for inv in (void, disputed, live):
        ledger.add(inv)
        ledger.issue(inv.number)
    ledger.void("VOID", D0)
    ledger.dispute("DISP")
    payment = ledger.receive("P1", "acme", "300.00", D0)
    assert [a.invoice for a in payment.allocations] == ["LIVE"]
    assert payment.credit == D("200.00")
    assert ledger.credit("acme") == D("200.00")
    assert draft.status == "draft" and draft.balance == D("100.00")
    assert void.status == "void"
    assert disputed.balance == D("100.00")
    assert paid.balance == D("0.00") and paid.status == "paid"


def test_a_resolved_dispute_can_be_paid_again():
    inv = make_invoice()
    ledger = issued(inv)
    ledger.dispute("INV-1")
    ledger.resolve("INV-1")
    ledger.receive("P1", "acme", "100.00", D0)
    assert inv.status == "paid"


# -- R4.8 ------------------------------------------------------------------

def test_reverse_restores_principal_and_logs_one_event():
    inv = make_invoice()
    ledger = issued(inv)
    ledger.receive("P1", "acme", "100.00", D0)
    ledger.reverse("P1", D0 + timedelta(days=2))
    assert inv.status == "open"
    assert inv.balance == D("100.00")
    reversals = kinds(ledger, "reversal")
    assert [(e.amount, e.date, e.ref, e.customer) for e in reversals] == [
        (D("100.00"), D0 + timedelta(days=2), "P1", "acme")]
    assert ledger.payments["P1"].reversed


def test_reverse_restores_late_fees_that_were_paid():
    inv = make_invoice(price="1000.00")
    ledger = issued(inv)
    ledger.assess_late_fees(D0 + timedelta(days=16))
    ledger.receive("P1", "acme", "100.00", D0 + timedelta(days=16))
    ledger.reverse("P1", D0 + timedelta(days=17))
    assert inv.fees_due == D("15.00")
    assert inv.principal_due == D("1000.00")
    assert inv.balance == D("1015.00")
    assert kinds(ledger, "reversal")[0].amount == D("100.00")


def test_reverse_takes_back_the_credit_it_left():
    ledger = issued(make_invoice())
    ledger.receive("P1", "acme", "130.00", D0)
    assert ledger.credit("acme") == D("30.00")
    ledger.reverse("P1", D0)
    assert ledger.credit("acme") == D("0.00")
    assert kinds(ledger, "reversal")[0].amount == D("130.00")


def test_reverse_of_a_payment_that_was_all_credit():
    ledger = Ledger()
    ledger.receive("P1", "acme", "50.00", D0)
    ledger.reverse("P1", D0)
    assert ledger.credit("acme") == D("0.00")


@pytest.mark.xfail(strict=True, reason="reversing a payment does not give back the discount it earned")
def test_reverse_gives_back_the_discount_the_payment_earned():
    inv = make_invoice(terms=DISCOUNT_TERMS)
    ledger = issued(inv)
    ledger.receive("P1", "acme", "98.00", DEADLINE)
    ledger.reverse("P1", DEADLINE + timedelta(days=1))
    assert inv.status == "open"
    assert inv.balance == D("100.00")


def test_reversal_event_includes_the_discount():
    ledger = issued(make_invoice(terms=DISCOUNT_TERMS))
    ledger.receive("P1", "acme", "98.00", DEADLINE)
    ledger.reverse("P1", DEADLINE)
    reversals = kinds(ledger, "reversal")
    assert len(reversals) == 1
    assert reversals[0].amount == D("100.00")


def test_a_reversed_payment_can_be_applied_again_by_a_new_payment():
    inv = make_invoice()
    ledger = issued(inv)
    ledger.receive("P1", "acme", "100.00", D0)
    ledger.reverse("P1", D0)
    ledger.receive("P2", "acme", "100.00", D0)
    assert inv.status == "paid"


def test_reverse_unknown_or_already_reversed_payment_is_an_error():
    ledger = issued(make_invoice())
    with pytest.raises(PaymentError):
        ledger.reverse("NOPE", D0)
    ledger.receive("P1", "acme", "100.00", D0)
    ledger.reverse("P1", D0)
    before = snapshot(ledger)
    with pytest.raises(PaymentError):
        ledger.reverse("P1", D0)
    assert snapshot(ledger) == before


def test_a_reversed_payment_id_cannot_be_received_again():
    ledger = issued(make_invoice())
    ledger.receive("P1", "acme", "100.00", D0)
    ledger.reverse("P1", D0)
    before = snapshot(ledger)
    with pytest.raises(PaymentError):
        ledger.receive("P1", "acme", "100.00", D0)
    assert snapshot(ledger) == before


# -- R4.9 ------------------------------------------------------------------

def test_cannot_reverse_once_its_credit_has_been_used():
    ledger = Ledger()
    ledger.receive("P1", "acme", "100.00", D0)               # all credit
    ledger.add(make_invoice("INV-1", due=D0 + timedelta(days=7)))
    ledger.issue("INV-1")
    ledger.apply_credit("acme", D0)
    before = snapshot(ledger)
    with pytest.raises(PaymentError):
        ledger.reverse("P1", D0)
    assert snapshot(ledger) == before
    assert not ledger.payments["P1"].reversed


def test_cannot_reverse_when_only_part_of_the_credit_is_left():
    ledger = Ledger()
    ledger.receive("P1", "acme", "100.00", D0)
    ledger.add(make_invoice("INV-1", price="30.00"))
    ledger.issue("INV-1")
    ledger.apply_credit("acme", D0)
    assert ledger.credit("acme") == D("70.00")
    with pytest.raises(PaymentError):
        ledger.reverse("P1", D0)
    assert ledger.credit("acme") == D("70.00")
    assert ledger.invoices["INV-1"].status == "paid"


def test_payment_that_left_no_credit_can_be_reversed_after_credit_was_used_elsewhere():
    ledger = issued(make_invoice("INV-1", price="100.00"))
    ledger.receive("P1", "acme", "100.00", D0)
    ledger.receive("P2", "acme", "40.00", D0)                 # credit
    ledger.add(make_invoice("INV-2", price="40.00", due=D0 + timedelta(days=7)))
    ledger.issue("INV-2")
    ledger.apply_credit("acme", D0)
    ledger.reverse("P1", D0)
    assert ledger.invoices["INV-1"].balance == D("100.00")


# -- R4.10 -----------------------------------------------------------------

def test_apply_credit_uses_credit_in_payment_order_and_logs_no_event():
    ledger = Ledger()
    ledger.receive("P1", "acme", "130.00", D0)
    later = make_invoice("INV-1", due=D0 + timedelta(days=7))
    earlier = make_invoice("INV-2", due=D0)
    for inv in (later, earlier):
        ledger.add(inv)
        ledger.issue(inv.number)
    events_before = len(ledger.events)
    ledger.apply_credit("acme", D0)
    assert earlier.status == "paid"
    assert later.balance == D("70.00")
    assert ledger.credit("acme") == D("0.00")
    assert len(ledger.events) == events_before


def test_apply_credit_pays_late_fees_first():
    ledger = Ledger()
    ledger.receive("P1", "acme", "30.00", D0 - timedelta(days=60))
    inv = make_invoice(price="1000.00")
    ledger.add(inv)
    ledger.issue("INV-1")
    ledger.assess_late_fees(D0 + timedelta(days=16))
    ledger.apply_credit("acme", D0 + timedelta(days=16))
    assert inv.fees_due == D("0.00")
    assert inv.principal_due == D("985.00")


def test_apply_credit_never_earns_an_early_discount():
    ledger = Ledger()
    ledger.receive("P1", "acme", "98.00", DEADLINE)
    inv = make_invoice(terms=DISCOUNT_TERMS)
    ledger.add(inv)
    ledger.issue("INV-1")
    allocations = ledger.apply_credit("acme", DEADLINE)
    assert [a.discount for a in allocations] == [D("0.00")]
    assert inv.balance == D("2.00")
    assert ledger.credit("acme") == D("0.00")
    assert kinds(ledger, "discount") == []


def test_apply_credit_skips_disputed_and_leaves_the_rest_as_credit():
    ledger = Ledger()
    ledger.receive("P1", "acme", "500.00", D0)
    inv = make_invoice(price="100.00")
    disputed = make_invoice("INV-2", price="100.00", due=D0 - timedelta(days=5))
    ledger.add(inv)
    ledger.add(disputed)
    ledger.issue("INV-1")
    ledger.issue("INV-2")
    ledger.dispute("INV-2")
    ledger.apply_credit("acme", D0)
    assert inv.status == "paid"
    assert disputed.balance == D("100.00")
    assert ledger.credit("acme") == D("400.00")


def test_apply_credit_with_no_credit_or_no_invoices_changes_nothing():
    ledger = issued(make_invoice())
    assert ledger.apply_credit("acme", D0) == []
    assert ledger.invoices["INV-1"].balance == D("100.00")
    assert Ledger().apply_credit("nobody", D0) == []
    ledger.receive("P1", "acme", "100.00", D0)
    ledger.receive("P2", "acme", "10.00", D0)
    assert ledger.apply_credit("acme", D0) == []
    assert ledger.credit("acme") == D("10.00")
