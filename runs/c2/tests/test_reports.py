"""SPEC sections 6 and 7: aging and statements."""

import pytest

from helpers import DUE, JAN_5, D, days, issue_all, issued, make_invoice, with_credit
from tally import Ledger, aging, statement

BUCKETS = ("current", "1-30", "31-60", "61-90", "91+", "disputed")


def report(*amounts):
    """The expected aging, buckets in the order above; those not given are zero."""
    padded = [*amounts, *["0.00"] * (len(BUCKETS) - len(amounts))]
    return {name: D(amount) for name, amount in zip(BUCKETS, padded)}


def only(bucket, amount):
    return {name: D(amount if name == bucket else "0.00") for name in BUCKETS}


# -- R6.1 ------------------------------------------------------------------


@pytest.mark.parametrize("days_late, bucket", [
    (-20, "current"), (0, "current"), (1, "1-30"), (30, "1-30"), (31, "31-60"), (60, "31-60"),
    (61, "61-90"), (90, "61-90"), (91, "91+"), (400, "91+"),
])
def test_r6_1_buckets(days_late, bucket):
    ledger = issued(make_invoice())
    assert aging(ledger, "acme", DUE + days(days_late)) == only(bucket, "100.00")


TODAY = DUE + days(100)


def one_per_bucket():
    """On TODAY these are 100, 84, 49, 25 and 0 days past due."""
    return [
        make_invoice("E", "10.00", terms="NET 30"),
        make_invoice("D", "20.00", terms="NET 46"),
        make_invoice("C", "30.00", terms="NET 81"),
        make_invoice("B", "40.00", terms="NET 105"),
        make_invoice("A", "50.00", terms="NET 130"),
    ]


def test_r6_1_invoices_are_spread_and_added_up():
    ledger = issued(*one_per_bucket(), make_invoice("A2", "5.00", terms="NET 140"))
    assert aging(ledger, "acme", TODAY) == report("55.00", "40.00", "30.00", "20.00", "10.00")


def test_r6_1_balance_after_payments_and_fees():
    ledger = issued(make_invoice(price="1000.00"))
    ledger.receive("P1", "acme", "400.00", JAN_5)
    ledger.assess_late_fees(DUE + days(10))
    assert aging(ledger, "acme", DUE + days(10)) == only("1-30", "609.00")


def test_r6_1_only_the_named_customer():
    ledger = issued(make_invoice("INV-1"), make_invoice("INV-2", "70.00", customer="other"))
    ledger.receive("P1", "third", "9.00", JAN_5)
    assert aging(ledger, "acme", JAN_5) == only("current", "100.00")
    assert aging(ledger, "other", JAN_5) == only("current", "70.00")
    assert aging(ledger, "nobody", JAN_5) == report()


# -- R6.2 ------------------------------------------------------------------


def test_r6_2_disputed_goes_nowhere_else():
    ledger = issued(make_invoice("INV-1", "1000.00"), make_invoice("INV-2", "25.00"))
    ledger.assess_late_fees(DUE + days(10))  # 15.00, and 2.50 because of the cap
    ledger.dispute("INV-1")
    assert aging(ledger, "acme", DUE + days(70)) == report(0, 0, 0, "27.50", 0, "1015.00")
    ledger.resolve("INV-1")
    assert aging(ledger, "acme", DUE + days(70)) == only("61-90", "1042.50")


def test_r6_2_draft_void_and_paid_are_left_out():
    ledger = issued(make_invoice("PAID"), make_invoice("VOID"), make_invoice("Z", "5.00"))
    ledger.receive("P1", "acme", "100.00", JAN_5)
    ledger.void("VOID", JAN_5)
    ledger.add(make_invoice("DRAFT"))
    assert aging(ledger, "acme", DUE + days(1)) == only("1-30", "5.00")


def test_r6_2_void_after_dispute_is_left_out():
    ledger = issued(make_invoice())
    ledger.dispute("INV-1")
    ledger.void("INV-1", JAN_5)
    assert aging(ledger, "acme", JAN_5) == report()


# -- R6.3 ------------------------------------------------------------------


@pytest.mark.parametrize("credit, left", [("30.00", "70.00"), ("100.00", "0.00")])
@pytest.mark.parametrize("days_late, bucket", [
    (0, "current"), (10, "1-30"), (40, "31-60"), (70, "61-90"), (100, "91+"),
])
def test_r6_3_credit_reduces_the_only_bucket(days_late, bucket, credit, left):
    ledger = with_credit(credit, make_invoice())
    assert aging(ledger, "acme", DUE + days(days_late)) == only(bucket, left)


@pytest.mark.parametrize("credit, current", [
    ("150.00", "0.00"), ("150.01", "-0.01"), ("200.00", "-50.00"),
])
def test_r6_3_leftover_credit_is_negative_current(credit, current):
    ledger = with_credit(credit, *one_per_bucket())
    assert aging(ledger, "acme", TODAY) == only("current", current)


def test_r6_3_credit_without_invoices():
    assert aging(with_credit("40.00"), "acme", JAN_5) == only("current", "-40.00")


def test_r6_3_credit_never_reduces_disputed():
    ledger = with_credit("60.00", make_invoice("INV-1"), make_invoice("INV-2", "50.00"))
    ledger.dispute("INV-1")
    assert aging(ledger, "acme", DUE + days(5)) == report("-10.00", 0, 0, 0, 0, "100.00")


def test_r6_3_other_customers_credit_is_not_used():
    ledger = with_credit("60.00", make_invoice(customer="other"))
    assert aging(ledger, "other", JAN_5) == only("current", "100.00")


def test_r6_3_reporting_does_not_use_the_credit_up():
    ledger = with_credit("60.00", make_invoice())
    assert aging(ledger, "acme", JAN_5) == only("current", "40.00")
    assert aging(ledger, "acme", JAN_5) == only("current", "40.00")
    assert ledger.credit("acme") == D("60.00")
    assert ledger.invoices["INV-1"].balance == D("100.00")


@pytest.mark.xfail(strict=True, reason="R6.3: credit reduces the newest bucket first")
@pytest.mark.parametrize("credit, expected", [
    ("4.00", report("50.00", "40.00", "30.00", "20.00", "6.00")),
    ("25.00", report("50.00", "40.00", "30.00", "5.00")),
    ("59.00", report("50.00", "40.00", "1.00")),
    ("99.00", report("50.00", "1.00")),
    ("149.00", report("1.00")),
], ids=["91+", "61-90", "31-60", "1-30", "current"])
def test_r6_3_credit_reduces_the_oldest_bucket_first(credit, expected):
    ledger = with_credit(credit, *one_per_bucket())
    assert aging(ledger, "acme", TODAY) == expected


# -- R7.1 ------------------------------------------------------------------


def lines(result):
    return [(x.date, x.kind, x.amount, x.balance) for x in result.lines]


@pytest.mark.parametrize("start, end, opening, amounts", [
    (0, 9, 0, [1, 2, 4, 8]),
    (1, 8, 0, [1, 2, 4, 8]),  # both ends are included
    (2, 4, 1, [2, 4]),
    (3, 3, 3, []),
    (4, 4, 3, [4]),
    (5, 7, 7, []),
    (9, 20, 15, []),
    (-9, 0, 0, []),
])
def test_r7_1_period_and_opening_balance(start, end, opening, amounts):
    ledger = issued(*(
        make_invoice(f"INV-{i}", f"{i}.00", on=JAN_5 + days(i)) for i in (1, 2, 4, 8)
    ))
    result = statement(ledger, "acme", JAN_5 + days(start), JAN_5 + days(end))
    assert result.customer == "acme"
    assert result.opening == opening
    assert [x.amount for x in result.lines] == amounts
    assert result.closing == opening + sum(amounts)


def test_r7_1_empty_account():
    result = statement(Ledger(), "acme", JAN_5, DUE)
    assert (result.opening, result.closing, result.lines) == (0, 0, [])


# -- R7.2, R7.3, R7.4 ------------------------------------------------------


def test_r7_2_lines_are_in_date_order():
    ledger = issued(
        make_invoice("INV-1", "8.00", on=JAN_5 + days(8)),
        make_invoice("INV-2", "1.00", on=JAN_5 + days(1)),
    )
    ledger.receive("P1", "acme", "3.00", JAN_5 + days(4))
    assert lines(statement(ledger, "acme", JAN_5, DUE)) == [
        (JAN_5 + days(1), "invoice", D("1.00"), D("1.00")),
        (JAN_5 + days(4), "payment", D("-3.00"), D("-2.00")),
        (JAN_5 + days(8), "invoice", D("8.00"), D("6.00")),
    ]


def test_r7_2_order_within_a_day():
    """Everything lands on one day, logged in the opposite order where possible."""
    day = JAN_5 + days(60)
    ledger = issued(
        make_invoice("OLD", "1000.00"),
        make_invoice("VOID", "7.00", on=day, terms="NET 90"),
    )
    ledger.void("VOID", day)
    ledger.receive("BAD", "acme", "50.00", day)
    ledger.reverse("BAD", day)
    ledger.assess_late_fees(day)
    ledger.receive("P1", "acme", "1015.00", day)
    issue_all(ledger, make_invoice("NEW", "200.00", on=day, terms="2/10 NET 30"))
    ledger.receive("P2", "acme", "196.00", day)
    result = statement(ledger, "acme", day, day)
    assert result.opening == D("1000.00")
    assert [x.kind for x in result.lines] == [
        "invoice", "invoice", "fee", "payment", "payment", "payment", "discount", "reversal",
        "void",
    ]
    assert sorted((x.kind, x.amount) for x in result.lines) == [
        ("discount", D("-4.00")), ("fee", D("15.00")),
        ("invoice", D("7.00")), ("invoice", D("200.00")),
        ("payment", D("-1015.00")), ("payment", D("-196.00")), ("payment", D("-50.00")),
        ("reversal", D("50.00")), ("void", D("-7.00")),
    ]
    assert result.closing == 0


def test_r7_2_two_discounted_payments_on_one_day():
    ledger = issued(make_invoice("A", "100.00", terms="2/10 NET 30"))
    ledger.receive("P1", "acme", "98.00", JAN_5)
    issue_all(ledger, make_invoice("B", "50.00", terms="2/10 NET 30"))
    ledger.receive("P2", "acme", "49.00", JAN_5)
    kinds = [x.kind for x in statement(ledger, "acme", JAN_5, JAN_5).lines]
    assert kinds == ["invoice", "invoice", "payment", "payment", "discount", "discount"]


def test_r7_2_reversal_before_void_and_after_discount():
    ledger = issued(
        make_invoice("A", "100.00", terms="2/10 NET 30"), make_invoice("B", "40.00", terms="NET 90")
    )
    ledger.void("B", JAN_5)
    ledger.receive("P1", "acme", "98.00", JAN_5)
    ledger.reverse("P1", JAN_5)
    assert lines(statement(ledger, "acme", JAN_5, JAN_5))[2:] == [
        (JAN_5, "payment", D("-98.00"), D("42.00")),
        (JAN_5, "discount", D("-2.00"), D("40.00")),
        (JAN_5, "reversal", D("100.00"), D("140.00")),
        (JAN_5, "void", D("-40.00"), D("100.00")),
    ]


def test_r7_3_running_balance_starts_from_the_opening_balance():
    ledger = issued(make_invoice(price="1000.00"))
    ledger.receive("P1", "acme", "300.00", JAN_5 + days(2))
    ledger.assess_late_fees(DUE + days(10))
    ledger.receive("P2", "acme", "800.00", DUE + days(12))
    result = statement(ledger, "acme", JAN_5 + days(1), DUE + days(12))
    assert result.opening == D("1000.00")
    assert lines(result) == [
        (JAN_5 + days(2), "payment", D("-300.00"), D("700.00")),
        (DUE + days(10), "fee", D("10.50"), D("710.50")),
        (DUE + days(12), "payment", D("-800.00"), D("-89.50")),
    ]
    assert result.closing == D("-89.50")


def test_r7_3_lines_refer_to_the_invoice_or_payment():
    ledger = issued(make_invoice("INV-7"))
    ledger.receive("P-9", "acme", "100.00", JAN_5)
    assert [x.ref for x in statement(ledger, "acme", JAN_5, JAN_5).lines] == ["INV-7", "P-9"]


def test_r7_4_signs():
    ledger = issued(
        make_invoice("A", "100.00", terms="2/10 NET 30"),
        make_invoice("B", "1000.00", terms="NET 31"),
    )
    ledger.receive("P1", "acme", "98.00", JAN_5)
    ledger.receive("P2", "acme", "10.00", JAN_5)
    ledger.reverse("P2", JAN_5)
    ledger.assess_late_fees(DUE + days(10))
    ledger.void("B", DUE + days(10))
    result = statement(ledger, "acme", JAN_5, DUE + days(10))
    signs = {(x.kind, x.amount > 0) for x in result.lines}
    assert signs == {
        ("invoice", True), ("fee", True), ("reversal", True),
        ("payment", False), ("discount", False), ("void", False),
    }
    assert result.closing == 0


def test_r7_4_only_the_named_customer():
    ledger = issued(
        make_invoice("INV-1", "100.00"),
        make_invoice("INV-2", "70.00", customer="other"),
        make_invoice("INV-3", "30.00", customer="other", on=JAN_5 + days(3)),
    )
    ledger.receive("P1", "other", "20.00", JAN_5 + days(3))
    mine = statement(ledger, "acme", JAN_5 + days(1), DUE)
    assert (mine.opening, mine.lines, mine.closing) == (D("100.00"), [], D("100.00"))
    theirs = statement(ledger, "other", JAN_5 + days(1), DUE)
    assert theirs.opening == D("70.00")
    assert [x.amount for x in theirs.lines] == [D("30.00"), D("-20.00")]
    assert theirs.closing == D("80.00")


def test_drafts_do_not_appear_on_statements():
    ledger = Ledger()
    ledger.add(make_invoice())
    assert statement(ledger, "acme", JAN_5, DUE).lines == []


def test_statement_and_aging_agree_on_what_is_owed():
    ledger = with_credit(
        "80.00",
        make_invoice("A", "1000.00", tax_rate="10", terms="2/10 NET 30"),
        make_invoice("B", "500.00", terms="NET 10"),
        make_invoice("C", "60.00", terms="NET 45"),
        make_invoice("D", "45.00", terms="NET 60"),
    )
    end = DUE + days(50)

    def check(owed):
        assert statement(ledger, "acme", JAN_5, end).closing == D(owed)
        assert sum(aging(ledger, "acme", end).values()) == D(owed)

    check("1625.00")
    ledger.apply_credit("acme", JAN_5)
    check("1625.00")
    ledger.receive("P1", "acme", "1500.00", JAN_5 + days(8))  # pays B, then A less 20.00
    check("105.00")
    ledger.dispute("D")
    ledger.assess_late_fees(DUE + days(45))  # 5.00 on C
    check("110.00")
    ledger.receive("P2", "acme", "20.00", DUE + days(46))
    check("90.00")
    ledger.reverse("P2", DUE + days(47))
    check("110.00")
    ledger.void("D", DUE + days(48))
    check("65.00")
