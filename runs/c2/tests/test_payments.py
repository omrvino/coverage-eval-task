"""SPEC section 4: payments."""

import pytest

from helpers import (
    DUE, JAN_5, D, balances, days, events, issue_all, issued, make_invoice, snapshot, with_credit,
)
from tally import Ledger, PaymentError, aging, statement

DISCOUNT_TERMS = "2/10 NET 30"
LAST_DAY = JAN_5 + days(10)


# -- R4.1 ------------------------------------------------------------------


def three_by_due_date():
    """Due order is B, C, A: not the order added, dated or numbered."""
    return (
        make_invoice("A", "10.00", on=JAN_5, terms="NET 60"),
        make_invoice("B", "20.00", on=JAN_5 + days(7), terms="NET 7"),
        make_invoice("C", "30.00", on=JAN_5 + days(1), terms="NET 30"),
    )


@pytest.mark.parametrize("amount, expected", [
    ("5.00", {"A": "10.00", "B": "15.00", "C": "30.00"}),
    ("20.00", {"A": "10.00", "B": "0.00", "C": "30.00"}),
    ("45.00", {"A": "10.00", "B": "0.00", "C": "5.00"}),
    ("59.00", {"A": "1.00", "B": "0.00", "C": "0.00"}),
])
def test_r4_1_earliest_due_date_first(amount, expected):
    ledger = issued(*three_by_due_date())
    ledger.receive("P1", "acme", amount, JAN_5 + days(8))
    assert balances(ledger) == {k: D(v) for k, v in expected.items()}


def test_r4_1_equal_due_dates_go_in_number_order():
    ledger = issued(*(make_invoice(n, "10.00") for n in ("INV-3", "INV-1", "INV-2")))
    ledger.receive("P1", "acme", "15.00", JAN_5)
    assert balances(ledger) == {"INV-1": 0, "INV-2": D("5.00"), "INV-3": D("10.00")}


def test_r4_1_number_order_only_breaks_ties():
    ledger = issued(
        make_invoice("INV-1", "10.00", terms="NET 31"),
        make_invoice("INV-2", "10.00", terms="NET 30"),
    )
    ledger.receive("P1", "acme", "10.00", JAN_5)
    assert balances(ledger) == {"INV-1": D("10.00"), "INV-2": 0}


NUMERIC_ORDERS = [
    ["INV-2", "INV-10"],
    ["INV-9", "INV-10", "INV-100"],
    ["2026-9-4", "2026-10-1"],
    ["2", "10"],
    ["A-7-9", "A-7-11", "B-1"],
]
R4_1 = pytest.mark.xfail(strict=True, reason="R4.1: invoice numbers are compared as plain text")


@R4_1
@pytest.mark.parametrize("numbers", NUMERIC_ORDERS, ids=" ".join)
def test_r4_1_digit_runs_compare_as_numbers(numbers):
    ledger = issued(*(make_invoice(n, "10.00") for n in reversed(numbers)))
    ledger.receive("P1", "acme", "10.00", JAN_5)
    assert balances(ledger) == {n: D("0.00" if n == numbers[0] else "10.00") for n in numbers}


def test_r4_1_only_the_customers_own_invoices():
    ledger = issued(
        make_invoice("INV-1", customer="other", terms="NET 5"),
        make_invoice("INV-2", customer="acme"),
    )
    ledger.receive("P1", "acme", "150.00", JAN_5)
    assert balances(ledger) == {"INV-1": D("100.00"), "INV-2": 0}
    assert (ledger.credit("acme"), ledger.credit("other")) == (D("50.00"), 0)


def test_r4_1_the_payment_says_where_the_money_went():
    ledger = issued(make_invoice("INV-1", "10.00"), make_invoice("INV-2", "10.00"))
    payment = ledger.receive("P1", "acme", "25.00", JAN_5)
    assert (payment.id, payment.customer, payment.amount, payment.date, payment.credit) == (
        "P1", "acme", D("25.00"), JAN_5, D("5.00"))
    assert [(a.invoice, a.principal, a.fees, a.discount) for a in payment.allocations] == [
        ("INV-1", D("10.00"), 0, 0), ("INV-2", D("10.00"), 0, 0)]


# -- R4.2 ------------------------------------------------------------------


@pytest.mark.parametrize("amount, fees, principal", [
    ("4.00", "11.00", "1000.00"),
    ("15.00", "0.00", "1000.00"),
    ("15.01", "0.00", "999.99"),
    ("115.00", "0.00", "900.00"),
    ("1015.00", "0.00", "0.00"),
])
def test_r4_2_fees_before_principal(amount, fees, principal):
    ledger = issued(make_invoice(price="1000.00"))
    ledger.assess_late_fees(DUE + days(10))
    ledger.receive("P1", "acme", amount, DUE + days(10))
    invoice = ledger.invoices["INV-1"]
    assert (invoice.fees_due, invoice.principal_due) == (D(fees), D(principal))


def test_r4_2_is_per_invoice():
    ledger = issued(
        make_invoice("INV-1", "1000.00"), make_invoice("INV-2", "1000.00", terms="NET 31")
    )
    ledger.assess_late_fees(DUE + days(10))
    ledger.receive("P1", "acme", "515.00", DUE + days(10))
    first, second = ledger.invoices["INV-1"], ledger.invoices["INV-2"]
    assert (first.fees_due, first.principal_due) == (0, D("500.00"))
    assert (second.fees_due, second.principal_due) == (D("15.00"), D("1000.00"))


# -- R4.3 ------------------------------------------------------------------


def discounted(**options):
    """Net 1000.00, total 1100.00, discount 20.00."""
    return make_invoice(price="1000.00", tax_rate="10", terms=DISCOUNT_TERMS, **options)


def test_r4_3_discount_is_on_the_net_before_tax():
    ledger = issued(discounted())
    ledger.receive("P1", "acme", "1080.00", LAST_DAY)
    assert ledger.invoices["INV-1"].status == "paid"
    assert ledger.credit("acme") == 0
    assert events(ledger, "payment") == [(LAST_DAY, "payment", D("-1080.00"))]
    assert events(ledger, "discount") == [(LAST_DAY, "discount", D("-20.00"))]


def test_r4_3_discount_is_rounded_to_the_cent():
    ledger = issued(make_invoice(price="33.33", terms=DISCOUNT_TERMS))  # 0.6666
    ledger.receive("P1", "acme", "32.66", LAST_DAY)
    assert ledger.invoices["INV-1"].status == "paid"
    assert events(ledger, "discount") == [(LAST_DAY, "discount", D("-0.67"))]


def test_r4_3_too_little_money_earns_nothing():
    ledger = issued(discounted())
    ledger.receive("P1", "acme", "1079.99", LAST_DAY)
    assert ledger.invoices["INV-1"].balance == D("20.01")
    assert events(ledger, "discount") == []


def test_r4_3_paying_the_full_balance_leaves_the_discount_as_credit():
    ledger = issued(discounted())
    ledger.receive("P1", "acme", "1100.00", LAST_DAY)
    assert ledger.invoices["INV-1"].status == "paid"
    assert ledger.credit("acme") == D("20.00")


def test_r4_3_a_day_late_earns_nothing():
    ledger = issued(discounted())
    ledger.receive("P1", "acme", "1080.00", LAST_DAY + days(1))
    assert ledger.invoices["INV-1"].balance == D("20.00")
    assert events(ledger, "discount") == []


def test_r4_3_an_earlier_payment_rules_it_out():
    ledger = issued(discounted())
    ledger.receive("P1", "acme", "0.01", JAN_5)
    ledger.receive("P2", "acme", "1099.98", LAST_DAY)
    assert ledger.invoices["INV-1"].balance == D("0.01")
    assert events(ledger, "discount") == []


def test_r4_3_a_payment_on_another_invoice_does_not_rule_it_out():
    ledger = issued(make_invoice("INV-0", "50.00", terms="NET 5"), discounted())
    ledger.receive("P1", "acme", "50.00", JAN_5)
    ledger.receive("P2", "acme", "1080.00", LAST_DAY)
    assert balances(ledger) == {"INV-0": 0, "INV-1": 0}


@pytest.mark.parametrize("amount, left", [("1960.00", "0.00"), ("1959.99", "20.01")])
def test_r4_3_counts_only_the_money_that_reaches_the_invoice(amount, left):
    ledger = issued(
        make_invoice("INV-1", "1000.00", terms=DISCOUNT_TERMS),
        make_invoice("INV-2", "1000.00", terms=DISCOUNT_TERMS),
    )
    ledger.receive("P1", "acme", amount, LAST_DAY)
    assert balances(ledger) == {"INV-1": 0, "INV-2": D(left)}


def late_but_backdated():
    """Due Jan 15 with a 15.00 late fee; payments dated up to Jan 15 can earn 20.00."""
    ledger = issued(make_invoice(price="1000.00", terms="2/10 NET 10"))
    ledger.assess_late_fees(LAST_DAY + days(6))
    return ledger


@pytest.mark.parametrize("amount, left", [("995.00", "0.00"), ("994.99", "20.01")])
def test_r4_3_the_balance_to_cover_includes_late_fees(amount, left):
    ledger = late_but_backdated()
    ledger.receive("P1", "acme", amount, LAST_DAY)
    assert balances(ledger) == {"INV-1": D(left)}


@pytest.mark.xfail(strict=True, reason="R4.3: an earlier payment that met only late fees is missed")
def test_r4_3_an_earlier_payment_of_late_fees_rules_it_out():
    ledger = late_but_backdated()
    ledger.receive("P1", "acme", "15.00", LAST_DAY - days(1))
    ledger.receive("P2", "acme", "980.00", LAST_DAY)
    assert events(ledger, "discount") == []
    assert balances(ledger) == {"INV-1": D("20.00")}


# -- R4.4 ------------------------------------------------------------------


def test_r4_4_money_left_over_becomes_credit():
    ledger = issued(make_invoice())
    ledger.receive("P1", "acme", "130.00", JAN_5)
    assert ledger.credit("acme") == D("30.00")
    ledger.receive("P2", "acme", "12.50", JAN_5)  # nothing open
    assert ledger.credit("acme") == D("42.50")


def test_r4_4_no_credit_until_there_is_money_left_over():
    ledger = issued(make_invoice())
    assert ledger.credit("acme") == 0
    ledger.receive("P1", "acme", "100.00", JAN_5)
    assert ledger.credit("acme") == 0


def test_r4_4_customer_without_invoices():
    ledger = Ledger()
    ledger.receive("P1", "new", "75.00", JAN_5)
    assert ledger.credit("new") == D("75.00")


# -- R4.5, R4.6 ------------------------------------------------------------


@pytest.mark.parametrize("amount", ["40.00", "40", 40, D("40.0")], ids=repr)
def test_r4_5_repeating_a_payment_changes_nothing(amount):
    ledger = issued(make_invoice())
    ledger.receive("P1", "acme", "40.00", JAN_5)
    before = snapshot(ledger)
    again = ledger.receive("P1", "acme", amount, JAN_5 + days(3))
    assert snapshot(ledger) == before
    assert (again.id, again.customer, again.amount, again.date) == ("P1", "acme", D("40.00"), JAN_5)


@pytest.mark.parametrize("customer, amount", [
    ("acme", "40.01"), ("acme", "39.99"), ("other", "40.00"), ("other", "41.00"),
])
def test_r4_5_reusing_an_id_for_something_else(customer, amount):
    ledger = issued(make_invoice())
    ledger.receive("P1", "acme", "40.00", JAN_5)
    before = snapshot(ledger)
    with pytest.raises(PaymentError):
        ledger.receive("P1", customer, amount, JAN_5)
    assert snapshot(ledger) == before
    assert ledger.credit("other") == 0


@pytest.mark.parametrize("amount", ["0", "0.00", 0, "-0.01", "-100.00"], ids=repr)
def test_r4_6_amount_must_be_positive(amount):
    ledger = issued(make_invoice())
    before = snapshot(ledger)
    with pytest.raises(PaymentError):
        ledger.receive("P1", "acme", amount, JAN_5)
    assert snapshot(ledger) == before


def test_r4_6_one_cent_is_enough():
    ledger = issued(make_invoice())
    ledger.receive("P1", "acme", "0.01", JAN_5)
    assert balances(ledger) == {"INV-1": D("99.99")}


# -- R4.7 ------------------------------------------------------------------


def make_draft(ledger):
    ledger.add(make_invoice("X", terms="NET 1"))


def make_void(ledger):
    make_draft(ledger)
    ledger.issue("X")
    ledger.void("X", JAN_5)


def make_paid(ledger):
    make_draft(ledger)
    ledger.issue("X")
    ledger.receive("EARLIER", "acme", "100.00", JAN_5)


def make_disputed(ledger):
    make_draft(ledger)
    ledger.issue("X")
    ledger.dispute("X")


@pytest.mark.parametrize("prepare", [make_draft, make_void, make_paid, make_disputed])
@pytest.mark.parametrize("use", ["payment", "credit"])
def test_r4_7_these_receive_nothing(prepare, use):
    ledger = Ledger()
    prepare(ledger)
    before = snapshot(ledger)["invoices"]["X"]
    ledger.receive("P1", "acme", "30.00", JAN_5)
    if use == "credit":
        ledger.apply_credit("acme", JAN_5)
    assert snapshot(ledger)["invoices"]["X"] == before
    assert ledger.credit("acme") == D("30.00")


def test_r4_7_money_skips_to_the_next_open_invoice():
    ledger = Ledger()
    make_disputed(ledger)
    issue_all(ledger, make_invoice("INV-2"))
    ledger.receive("P1", "acme", "100.00", JAN_5)
    assert balances(ledger) == {"X": D("100.00"), "INV-2": 0}


def test_r4_7_resolved_invoice_can_be_paid_again():
    ledger = Ledger()
    make_disputed(ledger)
    ledger.resolve("X")
    ledger.receive("P1", "acme", "100.00", JAN_5)
    assert ledger.invoices["X"].status == "paid"


# -- R4.8 ------------------------------------------------------------------


def test_r4_8_restores_principal_over_several_invoices():
    ledger = issued(make_invoice("INV-1"), make_invoice("INV-2"))
    ledger.receive("P1", "acme", "150.00", JAN_5)
    ledger.reverse("P1", JAN_5 + days(4))
    assert balances(ledger) == {"INV-1": D("100.00"), "INV-2": D("100.00")}
    assert ledger.invoices["INV-1"].status == "open"
    assert events(ledger, "reversal") == [(JAN_5 + days(4), "reversal", D("150.00"))]


def test_r4_8_restores_late_fees():
    ledger = issued(make_invoice(price="1000.00"))
    ledger.assess_late_fees(DUE + days(10))
    ledger.receive("P1", "acme", "500.00", DUE + days(10))
    ledger.reverse("P1", DUE + days(11))
    invoice = ledger.invoices["INV-1"]
    assert (invoice.fees_due, invoice.principal_due) == (D("15.00"), D("1000.00"))


def test_r4_8_takes_back_the_credit():
    ledger = issued(make_invoice())
    ledger.receive("P0", "acme", "110.00", JAN_5)
    ledger.receive("P1", "acme", "25.00", JAN_5)
    ledger.reverse("P1", JAN_5)
    assert ledger.credit("acme") == D("10.00")
    assert balances(ledger) == {"INV-1": 0}


def test_r4_8_undoes_only_the_payment_named():
    ledger = issued(make_invoice())
    ledger.receive("P1", "acme", "30.00", JAN_5)
    ledger.receive("P2", "acme", "20.00", JAN_5)
    ledger.receive("P3", "other", "5.00", JAN_5)
    ledger.reverse("P1", JAN_5)
    assert balances(ledger) == {"INV-1": D("80.00")}
    assert ledger.credit("other") == D("5.00")


def test_r4_8_event_includes_the_discount():
    ledger = issued(discounted())
    ledger.receive("P1", "acme", "1080.00", LAST_DAY)
    ledger.reverse("P1", LAST_DAY + days(5))
    assert events(ledger, "reversal") == [(LAST_DAY + days(5), "reversal", D("1100.00"))]
    assert statement(ledger, "acme", JAN_5, DUE).closing == D("1100.00")


def test_r4_8_event_covers_the_whole_payment_with_discount_and_credit():
    ledger = issued(discounted())
    ledger.receive("P1", "acme", "1130.00", LAST_DAY)
    ledger.reverse("P1", LAST_DAY)
    assert events(ledger, "reversal") == [(LAST_DAY, "reversal", D("1150.00"))]
    assert ledger.credit("acme") == 0


R4_8 = pytest.mark.xfail(strict=True, reason="R4.8: the discount survives a reversal")


@R4_8
def test_r4_8_takes_back_the_discount():
    ledger = issued(discounted())
    ledger.receive("P1", "acme", "1080.00", LAST_DAY)
    ledger.reverse("P1", LAST_DAY + days(5))
    assert balances(ledger) == {"INV-1": D("1100.00")}
    assert sum(aging(ledger, "acme", DUE).values()) == D("1100.00")


@R4_8
def test_r4_8_discount_can_be_earned_again_but_not_twice():
    ledger = issued(discounted())
    ledger.receive("P1", "acme", "1080.00", JAN_5)
    ledger.reverse("P1", JAN_5 + days(1))
    ledger.receive("P2", "acme", "1080.00", LAST_DAY)
    assert balances(ledger) == {"INV-1": 0}
    assert ledger.credit("acme") == 0


def test_r4_8_a_reversed_payment_no_longer_rules_out_the_discount():
    ledger = issued(discounted())
    ledger.receive("P1", "acme", "10.00", JAN_5)
    ledger.reverse("P1", JAN_5 + days(1))
    ledger.receive("P2", "acme", "1080.00", LAST_DAY)
    assert balances(ledger) == {"INV-1": 0}
    assert events(ledger, "discount") == [(LAST_DAY, "discount", D("-20.00"))]


def test_r4_8_unknown_payment():
    ledger = issued(make_invoice())
    before = snapshot(ledger)
    with pytest.raises(PaymentError):
        ledger.reverse("NOPE", JAN_5)
    assert snapshot(ledger) == before


@pytest.mark.parametrize("amount", ["40.00", "130.00"])
def test_r4_8_already_reversed(amount):
    ledger = issued(make_invoice())
    ledger.receive("P0", "other", "500.00", JAN_5)
    ledger.receive("P1", "acme", amount, JAN_5)
    ledger.reverse("P1", JAN_5)
    before = snapshot(ledger)
    with pytest.raises(PaymentError):
        ledger.reverse("P1", JAN_5)
    assert snapshot(ledger) == before


@pytest.mark.parametrize("amount", ["40.00", "50.00"])
def test_r4_8_reversed_id_cannot_be_received_again(amount):
    ledger = issued(make_invoice())
    ledger.receive("P1", "acme", "40.00", JAN_5)
    ledger.reverse("P1", JAN_5)
    before = snapshot(ledger)
    with pytest.raises(PaymentError):
        ledger.receive("P1", "acme", amount, JAN_5)
    assert snapshot(ledger) == before


# -- R4.9 ------------------------------------------------------------------


@pytest.mark.parametrize("price", ["20.00", "50.00", "80.00"], ids=["part", "exact", "all"])
def test_r4_9_not_once_its_credit_was_used(price):
    ledger = with_credit("50.00", make_invoice(price=price))
    ledger.apply_credit("acme", JAN_5)
    before = snapshot(ledger)
    with pytest.raises(PaymentError):
        ledger.reverse("CR", JAN_5 + days(1))
    assert snapshot(ledger) == before


def test_r4_9_also_protects_what_the_payment_did_to_invoices():
    ledger = issued(make_invoice("INV-1", "100.00"))
    ledger.receive("P1", "acme", "150.00", JAN_5)
    issue_all(ledger, make_invoice("INV-2", "10.00"))
    ledger.apply_credit("acme", JAN_5)
    before = snapshot(ledger)
    with pytest.raises(PaymentError):
        ledger.reverse("P1", JAN_5 + days(1))
    assert snapshot(ledger) == before


def test_r4_9_unused_credit_does_not_block_a_reversal():
    ledger = with_credit("50.00", make_invoice())
    ledger.reverse("CR", JAN_5)
    assert ledger.credit("acme") == 0


def test_r4_9_payment_that_left_no_credit_can_be_reversed():
    ledger = with_credit("50.00", make_invoice())
    ledger.receive("P1", "acme", "30.00", JAN_5)
    ledger.apply_credit("acme", JAN_5)
    ledger.reverse("P1", JAN_5)
    assert balances(ledger) == {"INV-1": D("50.00")}


@pytest.mark.xfail(strict=True, reason="R4.9: credit from a later payment hides that it was used")
def test_r4_9_later_credit_does_not_make_up_for_used_credit():
    ledger = with_credit("50.00", make_invoice(price="50.00"))
    ledger.apply_credit("acme", JAN_5)  # uses all of CR's credit, the only credit there is
    ledger.receive("P2", "acme", "50.00", JAN_5 + days(1))
    before = snapshot(ledger)
    with pytest.raises(PaymentError):
        ledger.reverse("CR", JAN_5 + days(2))
    assert snapshot(ledger) == before


# -- R4.10 -----------------------------------------------------------------


def test_r4_10_same_order_as_a_payment():
    ledger = with_credit("45.00", *three_by_due_date())
    ledger.apply_credit("acme", JAN_5 + days(8))
    assert balances(ledger) == {"A": D("10.00"), "B": 0, "C": D("5.00")}
    assert ledger.credit("acme") == 0


def test_r4_10_number_order_breaks_ties():
    ledger = with_credit("15.00", make_invoice("INV-2", "10.00"), make_invoice("INV-1", "10.00"))
    ledger.apply_credit("acme", JAN_5)
    assert balances(ledger) == {"INV-1": 0, "INV-2": D("5.00")}


@R4_1
@pytest.mark.parametrize("numbers", NUMERIC_ORDERS, ids=" ".join)
def test_r4_10_digit_runs_compare_as_numbers(numbers):
    ledger = with_credit("10.00", *(make_invoice(n, "10.00") for n in reversed(numbers)))
    ledger.apply_credit("acme", JAN_5)
    assert balances(ledger) == {n: D("0.00" if n == numbers[0] else "10.00") for n in numbers}


def test_r4_10_fees_before_principal():
    ledger = with_credit("40.00", make_invoice(price="1000.00"))
    ledger.assess_late_fees(DUE + days(10))
    ledger.apply_credit("acme", DUE + days(10))
    invoice = ledger.invoices["INV-1"]
    assert (invoice.fees_due, invoice.principal_due) == (0, D("975.00"))


def test_r4_10_never_earns_a_discount():
    ledger = with_credit("1080.00", discounted())
    ledger.apply_credit("acme", JAN_5)
    assert balances(ledger) == {"INV-1": D("20.00")}


def test_r4_10_keeps_what_is_left():
    ledger = with_credit("1100.01", discounted())
    ledger.apply_credit("acme", JAN_5)
    assert balances(ledger) == {"INV-1": 0}
    assert ledger.credit("acme") == D("0.01")


def test_r4_10_logs_no_event():
    ledger = with_credit("50.00", make_invoice(terms=DISCOUNT_TERMS))
    before = events(ledger)
    ledger.apply_credit("acme", JAN_5)
    assert events(ledger) == before
    assert balances(ledger) == {"INV-1": D("50.00")}


def test_r4_10_without_credit_nothing_happens():
    ledger = issued(make_invoice())
    before = snapshot(ledger)
    ledger.apply_credit("acme", JAN_5)
    assert snapshot(ledger) == before


def test_r4_10_uses_only_the_named_customers_credit():
    ledger = with_credit("50.00", make_invoice("INV-1"), make_invoice("INV-2", customer="other"))
    ledger.apply_credit("other", JAN_5)
    assert balances(ledger) == {"INV-1": D("100.00"), "INV-2": D("100.00")}
    assert ledger.credit("acme") == D("50.00")
