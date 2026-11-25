"""SPEC section 4: payments, credit and reversals."""

from datetime import date
from decimal import Decimal as D

import pytest

from helpers import JAN_5, allocations, balances, events, invoice, issue, ledger_with, state
from tally import Ledger, PaymentError

JAN_15 = date(2026, 1, 15)  # last discount day for 2/10 from JAN_5
JAN_16 = date(2026, 1, 16)
JAN_20 = date(2026, 1, 20)
LATE = date(2026, 2, 20)  # 16 days after the 4 February due date


# -- order --------------------------------------------------------------------


def test_payment_is_recorded():
    ledger = ledger_with(invoice())
    payment = ledger.receive("P1", "acme", "40.00", JAN_20)
    assert (payment.id, payment.customer, payment.amount, payment.date) == (
        "P1", "acme", D("40.00"), JAN_20,
    )
    assert (payment.credit, payment.reversed) == (D("0.00"), False)
    assert allocations(payment.allocations) == [("INV-1", D("40.00"), D("0.00"), D("0.00"))]
    assert ledger.payments["P1"].amount == D("40.00")
    assert events(ledger, "payment") == [(JAN_20, "acme", "payment", "P1", D("-40.00"))]


def test_payment_goes_to_the_earliest_due_date_first():
    # Neither the number nor the invoice date nor the adding order decides.
    ledger = ledger_with(
        invoice("INV-1", terms="NET 60", day=date(2026, 1, 2)),
        invoice("INV-3", terms="NET 10", day=JAN_5),
        invoice("INV-2", terms="NET 30", day=JAN_5),
    )
    payment = ledger.receive("P1", "acme", "150.00", JAN_20)
    assert [a.invoice for a in payment.allocations] == ["INV-3", "INV-2"]
    assert balances(ledger) == {"INV-1": D("100.00"), "INV-3": D("0.00"), "INV-2": D("50.00")}


def test_equal_due_dates_go_in_number_order():
    ledger = ledger_with(invoice("INV-3"), invoice("INV-1"), invoice("INV-2"))
    ledger.receive("P1", "acme", "150.00", JAN_20)
    assert balances(ledger) == {"INV-1": D("0.00"), "INV-2": D("50.00"), "INV-3": D("100.00")}


def test_due_dates_are_compared_after_moving_for_weekends():
    # Saturday 10 and Monday 12 January are both due on the 12th.
    ledger = ledger_with(invoice("INV-2", terms="NET 5"), invoice("INV-1", terms="NET 7"))
    ledger.receive("P1", "acme", "100.00", JAN_5)
    assert balances(ledger) == {"INV-1": D("0.00"), "INV-2": D("100.00")}


@pytest.mark.xfail(strict=True, reason="R4.1: equal due dates go in plain text order, INV-10 before INV-2")
def test_digit_runs_in_numbers_are_compared_as_numbers():
    ledger = ledger_with(invoice("INV-10"), invoice("INV-2"))
    ledger.receive("P1", "acme", "100.00", JAN_20)
    assert balances(ledger) == {"INV-2": D("0.00"), "INV-10": D("100.00")}


@pytest.mark.xfail(strict=True, reason="R4.1: equal due dates go in plain text order, INV-10 before INV-2")
def test_every_digit_run_counts():
    ledger = ledger_with(invoice("A10-9"), invoice("A9-10"), invoice("A9-9"))
    payment = ledger.receive("P1", "acme", "300.00", JAN_20)
    assert [a.invoice for a in payment.allocations] == ["A9-9", "A9-10", "A10-9"]


def test_other_customers_invoices_are_not_touched():
    ledger = ledger_with(invoice("INV-1", customer="other"), invoice("INV-2"))
    ledger.receive("P1", "acme", "150.00", JAN_20)
    assert balances(ledger) == {"INV-1": D("100.00"), "INV-2": D("0.00")}
    assert ledger.credit("acme") == D("50.00")
    assert ledger.credit("other") == D("0.00")


# -- fees before principal ----------------------------------------------------


def test_late_fees_are_paid_before_principal():
    ledger = ledger_with(invoice(price="1000.00"))
    ledger.assess_late_fees(LATE)
    made = ledger.invoices["INV-1"]
    ledger.receive("P1", "acme", "10.00", LATE)
    assert (made.fees_due, made.principal_due) == (D("5.00"), D("1000.00"))
    second = ledger.receive("P2", "acme", "25.00", LATE)
    assert (made.fees_due, made.principal_due) == (D("0.00"), D("980.00"))
    assert allocations(second.allocations) == [("INV-1", D("20.00"), D("5.00"), D("0.00"))]


def test_fees_first_is_per_invoice():
    # The older invoice's principal is paid before the newer invoice's fee.
    ledger = ledger_with(
        invoice("INV-1", "1000.00"), invoice("INV-2", "1000.00", day=date(2026, 1, 6))
    )
    ledger.assess_late_fees(LATE)
    ledger.receive("P1", "acme", "1020.00", LATE)
    assert balances(ledger) == {"INV-1": D("0.00"), "INV-2": D("1010.00")}
    assert ledger.invoices["INV-2"].principal_due == D("1000.00")


# -- early-payment discount ---------------------------------------------------


def discounted(price="100.00", terms="2/10 NET 30", **extra):
    return ledger_with(invoice(price=price, terms=terms, **extra))


@pytest.mark.parametrize("day", [JAN_5, date(2026, 1, 14), JAN_15])
def test_discount_is_granted_up_to_the_deadline(day):
    ledger = discounted()
    payment = ledger.receive("P1", "acme", "98.00", day)
    made = ledger.invoices["INV-1"]
    assert (made.status, made.balance, made.discount_taken) == ("paid", D("0.00"), D("2.00"))
    assert allocations(payment.allocations) == [("INV-1", D("98.00"), D("0.00"), D("2.00"))]
    assert ledger.credit("acme") == D("0.00")
    assert events(ledger, "payment", "discount") == [
        (day, "acme", "payment", "P1", D("-98.00")),
        (day, "acme", "discount", "INV-1", D("-2.00")),
    ]


def test_no_discount_after_the_deadline():
    ledger = discounted()
    ledger.receive("P1", "acme", "98.00", JAN_16)
    made = ledger.invoices["INV-1"]
    assert (made.balance, made.discount_taken) == (D("2.00"), D("0.00"))
    assert events(ledger, "discount") == []


def test_no_discount_without_discount_terms():
    ledger = discounted(terms="NET 30")
    ledger.receive("P1", "acme", "98.00", JAN_5)
    assert balances(ledger) == {"INV-1": D("2.00")}


def test_no_discount_when_the_money_is_a_cent_short():
    ledger = discounted()
    ledger.receive("P1", "acme", "97.99", JAN_5)
    made = ledger.invoices["INV-1"]
    assert (made.balance, made.discount_taken) == (D("2.01"), D("0.00"))
    assert events(ledger, "discount") == []


def test_no_discount_after_an_earlier_payment():
    ledger = discounted()
    ledger.receive("P1", "acme", "1.00", JAN_5)
    ledger.receive("P2", "acme", "97.00", date(2026, 1, 6))
    made = ledger.invoices["INV-1"]
    assert (made.balance, made.discount_taken) == (D("2.00"), D("0.00"))
    ledger.receive("P3", "acme", "2.00", date(2026, 1, 6))
    assert (made.status, made.discount_taken) == ("paid", D("0.00"))


@pytest.mark.xfail(
    strict=True, reason="R4.3: an earlier payment that only paid late fees does not block the discount"
)
def test_no_discount_after_an_earlier_payment_that_went_to_late_fees():
    # Payments dated inside the window, recorded after a late fee was assessed.
    ledger = discounted(price="1000.00", terms="2/10 NET 10")
    ledger.assess_late_fees(date(2026, 1, 21))
    ledger.receive("P1", "acme", "10.00", date(2026, 1, 12))
    ledger.receive("P2", "acme", "985.00", date(2026, 1, 13))
    made = ledger.invoices["INV-1"]
    assert (made.balance, made.discount_taken) == (D("20.00"), D("0.00"))


def test_discount_needs_the_late_fees_covered_too():
    short = discounted(price="1000.00", terms="2/10 NET 10")
    short.assess_late_fees(date(2026, 1, 21))
    short.receive("P1", "acme", "980.00", JAN_15)
    assert short.invoices["INV-1"].discount_taken == D("0.00")
    assert balances(short) == {"INV-1": D("35.00")}

    enough = discounted(price="1000.00", terms="2/10 NET 10")
    enough.assess_late_fees(date(2026, 1, 21))
    payment = enough.receive("P1", "acme", "995.00", JAN_15)
    assert allocations(payment.allocations) == [("INV-1", D("980.00"), D("15.00"), D("20.00"))]
    assert enough.invoices["INV-1"].status == "paid"


def test_discount_is_on_the_net_before_tax():
    ledger = discounted(tax_rate="10")
    ledger.receive("P1", "acme", "108.00", JAN_15)
    made = ledger.invoices["INV-1"]
    assert (made.status, made.discount_taken) == ("paid", D("2.00"))

    short = discounted(tax_rate="10")
    short.receive("P1", "acme", "107.80", JAN_15)  # enough only if tax were discounted
    assert balances(short) == {"INV-1": D("2.20")}


@pytest.mark.parametrize(
    "price, terms, discount",
    [
        ("33.33", "2/10 NET 30", "0.67"),  # 0.6666
        ("33.17", "2/10 NET 30", "0.66"),  # 0.6634
        ("100.00", "1.5/10 NET 30", "1.50"),
    ],
)
def test_discount_is_rounded_to_the_cent(price, terms, discount):
    ledger = discounted(price, terms)
    ledger.receive("P1", "acme", D(price) - D(discount), JAN_15)
    made = ledger.invoices["INV-1"]
    assert (made.status, made.discount_taken) == ("paid", D(discount))


def test_discount_on_overpayment_leaves_the_rest_as_credit():
    ledger = discounted()
    payment = ledger.receive("P1", "acme", "100.00", JAN_15)
    assert ledger.invoices["INV-1"].discount_taken == D("2.00")
    assert payment.credit == ledger.credit("acme") == D("2.00")


def test_discount_looks_at_the_money_reaching_each_invoice():
    def two():
        return ledger_with(
            invoice("INV-1", "100.00", "2/10 NET 30"),
            invoice("INV-2", "200.00", "2/10 NET 30", day=date(2026, 1, 6)),
        )

    both = two()
    both.receive("P1", "acme", "294.00", JAN_15)
    assert balances(both) == {"INV-1": D("0.00"), "INV-2": D("0.00")}
    assert [e[3:] for e in events(both, "discount")] == [
        ("INV-1", D("-2.00")), ("INV-2", D("-4.00")),
    ]

    first_only = two()
    first_only.receive("P1", "acme", "293.99", JAN_15)
    assert balances(first_only) == {"INV-1": D("0.00"), "INV-2": D("4.01")}
    assert [e[3:] for e in events(first_only, "discount")] == [("INV-1", D("-2.00"))]


# -- credit -------------------------------------------------------------------


def test_money_left_over_becomes_credit():
    ledger = ledger_with(invoice())
    payment = ledger.receive("P1", "acme", "130.00", JAN_20)
    assert payment.credit == ledger.credit("acme") == D("30.00")
    ledger.receive("P2", "acme", "5.00", JAN_20)
    assert ledger.credit("acme") == D("35.00")


def test_payment_without_invoices_is_all_credit():
    ledger = Ledger()
    assert ledger.credit("acme") == D("0.00")
    payment = ledger.receive("P1", "acme", 25, JAN_20)
    assert (payment.credit, list(payment.allocations)) == (D("25.00"), [])
    assert ledger.credit("acme") == D("25.00")
    assert events(ledger) == [(JAN_20, "acme", "payment", "P1", D("-25.00"))]


# -- payment ids and amounts --------------------------------------------------


@pytest.mark.parametrize("again", ["130.00", "130", 130, D("130.0")])
def test_repeating_a_payment_changes_nothing(again):
    ledger = ledger_with(invoice())
    ledger.receive("P1", "acme", "130.00", JAN_20)
    issue(ledger, "INV-2")
    before = state(ledger)
    repeated = ledger.receive("P1", "acme", again, date(2026, 1, 25))
    assert state(ledger) == before
    assert (repeated.id, repeated.amount, repeated.date, repeated.credit) == (
        "P1", D("130.00"), JAN_20, D("30.00"),
    )
    assert allocations(repeated.allocations) == [("INV-1", D("100.00"), D("0.00"), D("0.00"))]


@pytest.mark.parametrize(
    "customer, amount", [("acme", "130.01"), ("other", "130.00"), ("other", "1.00")]
)
def test_reusing_a_payment_id_for_something_else_is_refused(customer, amount):
    ledger = ledger_with(invoice())
    ledger.receive("P1", "acme", "130.00", JAN_20)
    before = state(ledger)
    with pytest.raises(PaymentError):
        ledger.receive("P1", customer, amount, JAN_20)
    assert state(ledger) == before


@pytest.mark.parametrize("amount", ["0", 0, "0.00", "-0.01", -50, "0.004"])
def test_payment_must_be_more_than_zero(amount):
    ledger = ledger_with(invoice())
    before = state(ledger)
    with pytest.raises(PaymentError):
        ledger.receive("P1", "acme", amount, JAN_20)
    assert state(ledger) == before


def test_one_cent_is_a_payment():
    ledger = ledger_with(invoice())
    ledger.receive("P1", "acme", "0.01", JAN_20)
    assert balances(ledger) == {"INV-1": D("99.99")}


# -- what receives nothing ----------------------------------------------------


def test_draft_receives_nothing():
    ledger = Ledger()
    ledger.add(invoice())
    ledger.receive("P1", "acme", "100.00", JAN_20)
    assert balances(ledger) == {"INV-1": D("100.00")}
    assert ledger.credit("acme") == D("100.00")


def test_void_invoice_receives_nothing():
    ledger = ledger_with(invoice())
    ledger.void("INV-1", JAN_5)
    payment = ledger.receive("P1", "acme", "100.00", JAN_20)
    assert list(payment.allocations) == []
    assert ledger.credit("acme") == D("100.00")


def test_paid_invoice_receives_nothing():
    ledger = ledger_with(invoice())
    ledger.receive("P1", "acme", "100.00", JAN_20)
    payment = ledger.receive("P2", "acme", "100.00", JAN_20)
    assert list(payment.allocations) == []
    assert ledger.credit("acme") == D("100.00")


def test_disputed_invoice_receives_nothing_until_resolved():
    ledger = ledger_with(invoice("INV-1"), invoice("INV-2"))
    ledger.dispute("INV-1")
    ledger.receive("P1", "acme", "150.00", JAN_20)
    assert balances(ledger) == {"INV-1": D("100.00"), "INV-2": D("0.00")}
    assert ledger.credit("acme") == D("50.00")
    ledger.resolve("INV-1")
    ledger.receive("P2", "acme", "10.00", JAN_20)
    assert balances(ledger) == {"INV-1": D("90.00"), "INV-2": D("0.00")}


# -- reversal -----------------------------------------------------------------


def test_reverse_restores_principal_and_credit():
    ledger = ledger_with(invoice("INV-1"), invoice("INV-2"))
    ledger.receive("P1", "acme", "230.00", JAN_20)
    ledger.reverse("P1", date(2026, 1, 25))
    assert balances(ledger) == {"INV-1": D("100.00"), "INV-2": D("100.00")}
    assert {one.status for one in ledger.invoices.values()} == {"open"}
    assert ledger.credit("acme") == D("0.00")
    assert ledger.payments["P1"].reversed is True
    assert events(ledger, "reversal") == [
        (date(2026, 1, 25), "acme", "reversal", "P1", D("230.00")),
    ]


def test_reverse_restores_late_fees_paid():
    ledger = ledger_with(invoice(price="1000.00"))
    ledger.assess_late_fees(LATE)
    ledger.receive("P1", "acme", "215.00", LATE)
    ledger.reverse("P1", LATE)
    made = ledger.invoices["INV-1"]
    assert (made.fees_due, made.principal_due) == (D("15.00"), D("1000.00"))
    assert events(ledger, "reversal") == [(LATE, "acme", "reversal", "P1", D("215.00"))]


def test_reverse_undoes_only_the_named_payment():
    ledger = ledger_with(invoice())
    ledger.receive("P1", "acme", "30.00", JAN_20)
    ledger.receive("P2", "acme", "20.00", JAN_20)
    ledger.reverse("P1", JAN_20)
    assert balances(ledger) == {"INV-1": D("80.00")}
    assert ledger.payments["P2"].reversed is False


def test_reverse_event_includes_discounts():
    ledger = ledger_with(
        invoice("INV-1", "100.00", "2/10 NET 30"), invoice("INV-2", "200.00", "2/10 NET 30")
    )
    ledger.receive("P1", "acme", "300.00", JAN_15)  # 6.00 discount, 6.00 credit
    ledger.reverse("P1", JAN_20)
    assert events(ledger, "reversal") == [(JAN_20, "acme", "reversal", "P1", D("306.00"))]
    assert ledger.credit("acme") == D("0.00")
    assert sum(e.amount for e in ledger.events) == D("300.00")


@pytest.mark.xfail(strict=True, reason="R4.8: reverse leaves the discount on the invoice")
def test_reverse_takes_back_the_discount():
    ledger = discounted()
    ledger.receive("P1", "acme", "98.00", JAN_15)
    ledger.reverse("P1", JAN_20)
    made = ledger.invoices["INV-1"]
    assert (made.balance, made.discount_taken) == (D("100.00"), D("0.00"))


@pytest.mark.xfail(strict=True, reason="R4.8: reverse leaves the discount on the invoice")
def test_discount_can_be_earned_again_after_a_reversal():
    ledger = discounted()
    ledger.receive("P1", "acme", "98.00", JAN_5)
    ledger.reverse("P1", date(2026, 1, 8))
    ledger.receive("P2", "acme", "98.00", JAN_15)
    made = ledger.invoices["INV-1"]
    assert (made.status, made.discount_taken) == ("paid", D("2.00"))
    assert ledger.credit("acme") == D("0.00")


def test_reversed_payment_no_longer_blocks_voiding():
    ledger = ledger_with(invoice())
    ledger.receive("P1", "acme", "40.00", JAN_20)
    ledger.reverse("P1", JAN_20)
    ledger.void("INV-1", JAN_20)
    assert events(ledger, "void") == [(JAN_20, "acme", "void", "INV-1", D("-100.00"))]


def test_reverse_unknown_payment_is_refused():
    ledger = ledger_with(invoice())
    before = state(ledger)
    with pytest.raises(PaymentError):
        ledger.reverse("P9", JAN_20)
    assert state(ledger) == before


def test_reverse_twice_is_refused():
    ledger = ledger_with(invoice())
    ledger.receive("P1", "acme", "40.00", JAN_20)
    ledger.reverse("P1", JAN_20)
    before = state(ledger)
    with pytest.raises(PaymentError):
        ledger.reverse("P1", JAN_20)
    assert state(ledger) == before


@pytest.mark.parametrize(
    "customer, amount", [("acme", "40.00"), ("acme", "41.00"), ("other", "40.00")]
)
def test_reversed_id_cannot_be_received_again(customer, amount):
    ledger = ledger_with(invoice())
    ledger.receive("P1", "acme", "40.00", JAN_20)
    ledger.reverse("P1", JAN_20)
    before = state(ledger)
    with pytest.raises(PaymentError):
        ledger.receive("P1", customer, amount, JAN_20)
    assert state(ledger) == before


@pytest.mark.parametrize("later_price", ["30.00", "0.01"], ids=["all used", "a cent used"])
def test_payment_whose_credit_was_used_cannot_be_reversed(later_price):
    ledger = ledger_with(invoice())
    ledger.receive("P1", "acme", "130.00", JAN_20)
    issue(ledger, "INV-2", later_price)
    ledger.apply_credit("acme", JAN_20)
    before = state(ledger)
    with pytest.raises(PaymentError):
        ledger.reverse("P1", JAN_20)
    assert state(ledger) == before


def test_payment_without_credit_can_be_reversed_after_other_credit_was_used():
    ledger = ledger_with(invoice())
    ledger.receive("P1", "acme", "100.00", JAN_20)
    ledger.receive("P2", "acme", "30.00", JAN_20)
    issue(ledger, "INV-2", "30.00")
    ledger.apply_credit("acme", JAN_20)
    ledger.reverse("P1", JAN_20)
    assert balances(ledger) == {"INV-1": D("100.00"), "INV-2": D("0.00")}


def test_reverse_takes_back_only_the_credit_that_payment_left():
    ledger = Ledger()
    ledger.receive("P1", "acme", "30.00", JAN_20)
    ledger.receive("P2", "acme", "12.00", JAN_20)
    ledger.receive("P3", "other", "7.00", JAN_20)
    ledger.reverse("P1", JAN_20)
    assert ledger.credit("acme") == D("12.00")
    assert ledger.credit("other") == D("7.00")


# -- applying credit ----------------------------------------------------------


def with_credit(amount, *invoices):
    """A ledger where the customer had credit before the invoices were issued."""
    ledger = Ledger()
    ledger.receive("C1", "acme", amount, date(2026, 1, 2))
    for one in invoices:
        ledger.add(one)
        ledger.issue(one.number)
    return ledger


def test_apply_credit_pays_in_payment_order():
    ledger = with_credit(
        "250.00",
        invoice("INV-1", terms="NET 60"),
        invoice("INV-3"),
        invoice("INV-2"),
        invoice("INV-4", terms="NET 10"),
    )
    used = ledger.apply_credit("acme", JAN_20)
    assert allocations(used) == [
        ("INV-4", D("100.00"), D("0.00"), D("0.00")),
        ("INV-2", D("100.00"), D("0.00"), D("0.00")),
        ("INV-3", D("50.00"), D("0.00"), D("0.00")),
    ]
    assert balances(ledger) == {
        "INV-1": D("100.00"), "INV-2": D("0.00"), "INV-3": D("50.00"), "INV-4": D("0.00"),
    }
    assert ledger.credit("acme") == D("0.00")


@pytest.mark.xfail(strict=True, reason="R4.1: equal due dates go in plain text order, INV-10 before INV-2")
def test_apply_credit_compares_digit_runs_as_numbers():
    ledger = with_credit("100.00", invoice("INV-10"), invoice("INV-2"))
    ledger.apply_credit("acme", JAN_20)
    assert balances(ledger) == {"INV-2": D("0.00"), "INV-10": D("100.00")}


def test_apply_credit_keeps_what_is_left():
    ledger = with_credit("130.00", invoice())
    ledger.apply_credit("acme", JAN_20)
    assert ledger.credit("acme") == D("30.00")
    assert ledger.invoices["INV-1"].status == "paid"


def test_apply_credit_pays_late_fees_before_principal():
    ledger = with_credit("20.00", invoice(price="1000.00"))
    ledger.assess_late_fees(LATE)
    ledger.apply_credit("acme", LATE)
    made = ledger.invoices["INV-1"]
    assert (made.fees_due, made.principal_due) == (D("0.00"), D("995.00"))


@pytest.mark.parametrize("amount, balance", [("98.00", "2.00"), ("100.00", "0.00")])
def test_apply_credit_never_earns_a_discount(amount, balance):
    ledger = with_credit(amount, invoice(terms="2/10 NET 30"))
    ledger.apply_credit("acme", JAN_5)
    made = ledger.invoices["INV-1"]
    assert (made.balance, made.discount_taken) == (D(balance), D("0.00"))
    assert ledger.credit("acme") == D("0.00")


def test_apply_credit_logs_no_event():
    ledger = with_credit("50.00", invoice())
    before = events(ledger)
    ledger.apply_credit("acme", JAN_20)
    assert balances(ledger) == {"INV-1": D("50.00")}
    assert events(ledger) == before


def test_apply_credit_skips_disputed_draft_and_void_invoices():
    ledger = with_credit("500.00", invoice("INV-1"), invoice("INV-2"))
    ledger.add(invoice("INV-3"))
    ledger.dispute("INV-1")
    ledger.void("INV-2", JAN_5)
    assert list(ledger.apply_credit("acme", JAN_20)) == []
    assert ledger.credit("acme") == D("500.00")


def test_apply_credit_without_credit_does_nothing():
    ledger = ledger_with(invoice())
    before = state(ledger)
    assert list(ledger.apply_credit("acme", JAN_20)) == []
    assert state(ledger) == before


def test_apply_credit_uses_only_the_named_customers_credit():
    ledger = with_credit("50.00", invoice("INV-1", customer="other"), invoice("INV-2"))
    ledger.apply_credit("other", JAN_20)
    assert balances(ledger) == {"INV-1": D("100.00"), "INV-2": D("100.00")}
    ledger.apply_credit("acme", JAN_20)
    assert balances(ledger) == {"INV-1": D("100.00"), "INV-2": D("50.00")}
