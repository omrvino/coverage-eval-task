"""SPEC section 3: invoices."""

import pytest

from helpers import DUE, JAN_5, D, days, events, issued, make_invoice, snapshot, with_credit
from tally import InvoiceError, Ledger, Line, aging, statement


def line(price, quantity=1, discount=0, taxable=True):
    return Line("item", quantity, price, discount, taxable)


# -- R3.1 ------------------------------------------------------------------


@pytest.mark.parametrize("quantity, price, discount, expected", [
    (1, "100.00", 0, "100.00"),
    (3, "19.99", 0, "59.97"),
    (3, "19.99", 10, "53.97"),  # 53.973
    ("1.25", "9.99", 0, "12.49"),  # 12.4875
    (2, "50.00", "12.5", "87.50"),
    (2, "50.00", 100, "0.00"),
    (2, "-50.00", 10, "-90.00"),
    ("1.5549", "1.00", 3, "1.51"),  # 1.508253: rounded once, after the discount
])
def test_r3_1_line_net(quantity, price, discount, expected):
    assert line(price, quantity, discount).net == D(expected)


def test_r3_1_each_line_is_rounded_before_adding_up():
    third = [line("1.00", "0.334"), line("1.00", "0.334")]
    assert make_invoice(lines=third).net == D("0.66")


def test_r3_1_lines_have_no_discount_and_are_taxable_by_default():
    invoice = make_invoice(lines=[Line("item", 1, "10.00")], tax_rate="10")
    assert (invoice.net, invoice.tax) == (D("10.00"), D("1.00"))


# -- R3.2, R3.3 ------------------------------------------------------------


@pytest.mark.parametrize("rate, prices, expected", [
    ("8.25", ["100.00"], "8.25"),
    ("8.25", ["10.49"], "0.87"),  # 0.865425
    ("10", ["200.00", "-50.00"], "15.00"),  # a credit line reduces the base
    ("10", ["10.00", "20.00"], "3.00"),
    ("0", ["100.00"], "0.00"),
])
def test_r3_2_tax_on_taxable_lines(rate, prices, expected):
    invoice = make_invoice(lines=[line(p) for p in prices], tax_rate=rate)
    assert invoice.tax == D(expected)
    assert invoice.total == sum(map(D, prices)) + D(expected)


def test_r3_2_non_taxable_lines_are_left_out():
    lines = [line("100.00"), line("50.00", taxable=False)]
    invoice = make_invoice(lines=lines, tax_rate="10")
    assert (invoice.net, invoice.tax, invoice.total) == (D("150.00"), D("10.00"), D("160.00"))


def test_r3_2_only_non_taxable_lines():
    invoice = make_invoice(lines=[line("50.00", taxable=False)], tax_rate="10")
    assert (invoice.tax, invoice.total) == (D("0.00"), D("50.00"))


def test_r3_2_tax_is_on_the_discounted_net():
    assert make_invoice(lines=[line("100.00", 2, 25)], tax_rate="10").tax == D("15.00")


def test_r3_2_tax_is_on_the_rounded_line_nets():
    lines = [line("1.00", "1.004") for _ in range(20)]  # 20.00 in nets, 20.08 unrounded
    assert make_invoice(lines=lines, tax_rate="10").tax == D("2.00")


R3_2 = pytest.mark.xfail(strict=True, reason="R3.2: tax is rounded per line")


@R3_2
@pytest.mark.parametrize("price, expected", [("1.04", "0.31"), ("1.06", "0.32")])
def test_r3_2_tax_is_rounded_once(price, expected):
    invoice = make_invoice(lines=[line(price) for _ in range(3)], tax_rate="10")
    assert invoice.tax == D(expected)
    assert invoice.total == 3 * D(price) + D(expected)


@R3_2
def test_r3_2_many_small_lines_are_still_taxed():
    lines = [line("0.04") for _ in range(100)] + [line("0.04", taxable=False)]
    assert make_invoice(lines=lines, tax_rate="10").tax == D("0.40")


def test_r3_3_exempt_invoice_has_no_tax():
    invoice = make_invoice(price="100.00", tax_rate="10", tax_exempt=True)
    assert (invoice.tax, invoice.total) == (D("0.00"), D("100.00"))


# -- R3.4 ------------------------------------------------------------------


@pytest.mark.parametrize("options", [
    {"quantity": 0}, {"quantity": -1}, {"quantity": "-0.01"}, {"quantity": "0.00"},
    {"discount": "-0.01"}, {"discount": -5}, {"discount": "100.01"}, {"discount": 150},
], ids=repr)
def test_r3_4_bad_lines(options):
    with pytest.raises(InvoiceError):
        issued(make_invoice(lines=[line("500.00"), line("1.00", **options)]))


@pytest.mark.parametrize("options, expected", [
    ({"quantity": "0.01"}, "1.00"), ({"discount": 0}, "100.00"), ({"discount": 100}, "0.00"),
    ({"discount": "99.99"}, "0.01"),
], ids=repr)
def test_r3_4_limits_that_are_still_allowed(options, expected):
    assert line("100.00", **options).net == D(expected)


def test_r3_4_unit_price_may_be_negative():
    ledger = issued(make_invoice(lines=[line("100.00"), line("-30.00")]))
    assert ledger.invoices["INV-1"].total == D("70.00")


# -- R3.5 ------------------------------------------------------------------


@pytest.mark.parametrize("lines, rate", [
    ([], 0),
    ([line("-0.01")], 0),
    ([line("10.00"), line("-10.01")], 0),
    ([line("100.00", taxable=False), line("-100.00")], 10),  # net 0, total -10
], ids=["no lines", "negative", "sums negative", "negative after tax"])
def test_r3_5_cannot_issue(lines, rate):
    ledger = Ledger()
    ledger.add(make_invoice(lines=lines, tax_rate=rate))
    with pytest.raises(InvoiceError):
        ledger.issue("INV-1")
    assert ledger.invoices["INV-1"].status == "draft"
    assert events(ledger) == []


@pytest.mark.parametrize("lines, rate, total", [
    ([line("10.00"), line("-10.00")], 0, "0.00"),
    ([line("0.01")], 0, "0.01"),
    ([line("-100.00", taxable=False), line("95.00")], 10, "4.50"),  # net -5
], ids=["zero", "one cent", "positive after tax"])
def test_r3_5_total_of_zero_or_more_can_be_issued(lines, rate, total):
    ledger = issued(make_invoice(lines=lines, tax_rate=rate))
    assert ledger.invoices["INV-1"].status != "draft"
    assert statement(ledger, "acme", JAN_5, JAN_5).closing == D(total)


def test_r3_5_issuing_twice():
    ledger = issued(make_invoice())
    before = snapshot(ledger)
    with pytest.raises(InvoiceError):
        ledger.issue("INV-1")
    assert snapshot(ledger) == before


def test_r3_5_issuing_a_paid_invoice():
    ledger = issued(make_invoice())
    ledger.receive("P1", "acme", "100.00", JAN_5)
    with pytest.raises(InvoiceError):
        ledger.issue("INV-1")


def test_r3_5_issuing_a_void_invoice():
    ledger = issued(make_invoice())
    ledger.void("INV-1", JAN_5)
    before = snapshot(ledger)
    with pytest.raises(InvoiceError):
        ledger.issue("INV-1")
    assert snapshot(ledger) == before


# -- R3.6 ------------------------------------------------------------------


def test_r3_6_status_through_the_life_of_an_invoice():
    ledger = Ledger()
    ledger.add(make_invoice())
    assert ledger.invoices["INV-1"].status == "draft"
    ledger.issue("INV-1")
    assert ledger.invoices["INV-1"].status == "open"
    ledger.receive("P1", "acme", "99.99", JAN_5)
    assert ledger.invoices["INV-1"].status == "open"
    ledger.receive("P2", "acme", "0.01", JAN_5)
    assert ledger.invoices["INV-1"].status == "paid"


def test_r3_6_void():
    ledger = issued(make_invoice())
    ledger.void("INV-1", JAN_5)
    assert ledger.invoices["INV-1"].status == "void"


def test_r3_6_zero_total_is_paid_once_issued():
    ledger = Ledger()
    ledger.add(make_invoice(price="0.00"))
    assert ledger.invoices["INV-1"].status == "draft"
    ledger.issue("INV-1")
    assert ledger.invoices["INV-1"].status == "paid"


def test_r3_6_unpaid_late_fees_keep_an_invoice_open():
    ledger = issued(make_invoice())
    ledger.assess_late_fees(DUE + days(10))
    ledger.receive("P1", "acme", "100.00", DUE + days(10))
    assert ledger.invoices["INV-1"].status == "open"
    assert ledger.invoices["INV-1"].balance == D("5.00")
    ledger.receive("P2", "acme", "5.00", DUE + days(10))
    assert ledger.invoices["INV-1"].status == "paid"


def test_r3_6_an_invoice_that_owes_only_late_fees_is_open():
    ledger = issued(make_invoice())
    ledger.assess_late_fees(DUE + days(10))
    ledger.receive("FEE", "acme", "5.00", DUE + days(10))
    ledger.receive("REST", "acme", "100.00", DUE + days(10))
    ledger.reverse("FEE", DUE + days(11))
    invoice = ledger.invoices["INV-1"]
    assert (invoice.principal_due, invoice.fees_due) == (0, D("5.00"))
    assert invoice.status == "open"


# -- R3.7 ------------------------------------------------------------------


def test_r3_7_void_writes_off_the_balance():
    ledger = issued(make_invoice(price="100.00", tax_rate="10"))
    ledger.void("INV-1", JAN_5 + days(3))
    assert events(ledger, "void") == [(JAN_5 + days(3), "void", D("-110.00"))]
    assert statement(ledger, "acme", JAN_5, DUE).closing == 0


def test_r3_7_void_writes_off_late_fees_in_the_same_event():
    ledger = issued(make_invoice())
    ledger.assess_late_fees(DUE + days(10))
    ledger.void("INV-1", DUE + days(12))
    assert events(ledger, "void") == [(DUE + days(12), "void", D("-105.00"))]
    assert statement(ledger, "acme", JAN_5, DUE + days(60)).closing == 0
    assert set(aging(ledger, "acme", DUE + days(60)).values()) == {0}


def test_r3_7_disputed_invoice_can_be_voided():
    ledger = issued(make_invoice())
    ledger.dispute("INV-1")
    ledger.void("INV-1", JAN_5)
    assert ledger.invoices["INV-1"].status == "void"


def test_r3_7_can_be_voided_once_its_payment_is_reversed():
    ledger = issued(make_invoice())
    ledger.receive("P1", "acme", "40.00", JAN_5)
    ledger.reverse("P1", JAN_5)
    ledger.void("INV-1", JAN_5)
    assert events(ledger, "void") == [(JAN_5, "void", D("-100.00"))]


def prepare_draft():
    ledger = Ledger()
    ledger.add(make_invoice())
    return ledger


def prepare_void():
    ledger = issued(make_invoice())
    ledger.void("INV-1", JAN_5)
    return ledger


def prepare_part_paid():
    ledger = issued(make_invoice())
    ledger.receive("P1", "acme", "0.01", JAN_5)
    return ledger


def prepare_paid():
    ledger = issued(make_invoice())
    ledger.receive("P1", "acme", "100.00", JAN_5)
    return ledger


def prepare_fee_paid():
    ledger = issued(make_invoice())
    ledger.assess_late_fees(DUE + days(10))
    ledger.receive("P1", "acme", "2.00", DUE + days(10))  # reaches only the late fee
    return ledger


def prepare_credit_applied():
    ledger = with_credit("30.00", make_invoice())
    ledger.apply_credit("acme", JAN_5)
    return ledger


@pytest.mark.parametrize("prepare", [
    prepare_draft, prepare_void, prepare_part_paid, prepare_paid, prepare_fee_paid,
    prepare_credit_applied,
])
def test_r3_7_cannot_be_voided(prepare):
    ledger = prepare()
    before = snapshot(ledger)
    with pytest.raises(InvoiceError):
        ledger.void("INV-1", DUE + days(20))
    assert snapshot(ledger) == before


# -- R3.8 ------------------------------------------------------------------


@pytest.mark.parametrize("prepare", [prepare_draft, prepare_void, prepare_paid])
def test_r3_8_only_open_invoices_can_be_disputed(prepare):
    ledger = prepare()
    before = snapshot(ledger)
    with pytest.raises(InvoiceError):
        ledger.dispute("INV-1")
    assert snapshot(ledger) == before


@pytest.mark.parametrize("prepare", [prepare_part_paid, prepare_fee_paid])
def test_r3_8_part_paid_invoices_are_open_and_can_be_disputed(prepare):
    ledger = prepare()
    ledger.dispute("INV-1")
    owed = ledger.invoices["INV-1"].balance
    assert aging(ledger, "acme", JAN_5)["disputed"] == owed > 0


def test_r3_8_open_invoice_can_be_disputed_and_resolved():
    ledger = issued(make_invoice())
    ledger.dispute("INV-1")
    assert ledger.invoices["INV-1"].status == "open"  # disputed is not a status
    assert aging(ledger, "acme", JAN_5)["disputed"] == D("100.00")
    ledger.resolve("INV-1")
    assert aging(ledger, "acme", JAN_5)["disputed"] == 0


def test_r3_8_duplicate_number():
    ledger = issued(make_invoice(price="100.00"))
    with pytest.raises(InvoiceError):
        ledger.add(make_invoice(price="999.00", customer="other"))
    assert ledger.invoices["INV-1"].total == D("100.00")


@pytest.mark.parametrize("act", [
    lambda ledger: ledger.issue("NOPE"),
    lambda ledger: ledger.void("NOPE", JAN_5),
    lambda ledger: ledger.dispute("NOPE"),
    lambda ledger: ledger.resolve("NOPE"),
], ids=["issue", "void", "dispute", "resolve"])
def test_r3_8_unknown_number(act):
    ledger = issued(make_invoice())
    with pytest.raises(InvoiceError):
        act(ledger)
