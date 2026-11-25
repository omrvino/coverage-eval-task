"""SPEC section 3: invoices."""

from datetime import date
from decimal import Decimal as D

import pytest

from helpers import JAN_5, events, invoice, issue, ledger_with, owing_only_a_late_fee, state
from tally import InvoiceError, Ledger, Line, TallyError

JAN_20 = date(2026, 1, 20)
LATE = date(2026, 2, 20)  # 16 days after the 4 February due date


# -- amounts ------------------------------------------------------------------


@pytest.mark.parametrize(
    "quantity, price, discount, expected",
    [
        (1, "100.00", 0, "100.00"),
        (3, "19.99", 0, "59.97"),
        ("2.5", "10.00", 0, "25.00"),
        (2, "50.00", 10, "90.00"),
        (1, "80.00", "12.5", "70.00"),
        (1, "80.00", 100, "0.00"),
        (1, "0.333", 0, "0.33"),
        (3, "0.333", 0, "1.00"),  # the price is not rounded before multiplying
        (1, "9.99", 15, "8.49"),  # 8.4915
        (3, "9.99", 15, "25.47"),  # 25.4745
        (1, "10.67", 15, "9.07"),  # 9.0695
        (1, "-40.00", 0, "-40.00"),
        (2, "-40.00", 25, "-60.00"),
    ],
)
def test_line_net(quantity, price, discount, expected):
    net = Line("work", quantity, price, discount).net
    assert net == D(expected)
    assert net.as_tuple().exponent == -2


def test_lines_are_rounded_one_by_one():
    # 3 x 0.333 = 0.999 would be 1.00 if only the sum were rounded.
    assert invoice(lines=[Line("a", 1, "0.333") for _ in range(3)]).net == D("0.99")


def test_total_is_net_plus_tax():
    made = invoice(lines=[Line("a", 1, "100.00"), Line("b", 2, "25.00")], tax_rate="10")
    assert (made.net, made.tax, made.total) == (D("150.00"), D("15.00"), D("165.00"))


def test_tax_is_rounded_to_the_cent():
    assert invoice(price="10.07", tax_rate="8.25").tax == D("0.83")  # 0.830775
    assert invoice(price="10.04", tax_rate="8.25").tax == D("0.83")  # 0.8283
    assert invoice(price="10.00", tax_rate="0").tax == D("0.00")


@pytest.mark.xfail(strict=True, reason="R3.2: tax is rounded per line instead of once on the sum")
@pytest.mark.parametrize(
    "price, tax",
    [
        ("0.33", "0.10"),  # 0.099 on the sum, 3 x 0.03 per line
        ("0.36", "0.11"),  # 0.108 on the sum, 3 x 0.04 per line
    ],
)
def test_tax_is_computed_once_on_the_sum(price, tax):
    made = invoice(lines=[Line("a", 1, price) for _ in range(3)], tax_rate="10")
    assert made.tax == D(tax)


def test_non_taxable_lines_are_left_out_of_tax():
    made = invoice(
        lines=[Line("goods", 1, "100.00"), Line("postage", 1, "50.00", taxable=False)],
        tax_rate="10",
    )
    assert (made.tax, made.total) == (D("10.00"), D("160.00"))
    assert invoice(lines=[Line("x", 1, "50", taxable=False)], tax_rate="10").tax == D("0.00")


def test_tax_is_on_the_discounted_net():
    assert invoice(lines=[Line("a", 1, "100.00", 20)], tax_rate="10").tax == D("8.00")


def test_tax_is_on_the_rounded_line_net():
    # 0.333 is billed as 0.33; 300% of that is 0.99, not 1.00.
    assert invoice(lines=[Line("a", 1, "0.333")], tax_rate="300").tax == D("0.99")


def test_taxable_credit_line_reduces_tax():
    made = invoice(lines=[Line("a", 1, "100.00"), Line("back", 1, "-20.00")], tax_rate="10")
    assert (made.tax, made.total) == (D("8.00"), D("88.00"))


def test_tax_exempt_invoice_has_no_tax():
    made = invoice(tax_rate="10", tax_exempt=True)
    assert (made.tax, made.total) == (D("0.00"), D("100.00"))


# -- line checks --------------------------------------------------------------


@pytest.mark.parametrize("quantity", [0, "0.00", -1, "-0.01"])
def test_quantity_must_be_more_than_zero(quantity):
    with pytest.raises(InvoiceError):
        Line("work", quantity, "10.00")


def test_small_quantity_is_allowed():
    assert Line("work", "0.01", "100.00").net == D("1.00")


@pytest.mark.parametrize("discount", ["-0.01", -5, "100.01", 200])
def test_line_discount_must_be_0_to_100(discount):
    with pytest.raises(InvoiceError):
        Line("work", 1, "10.00", discount)


# -- issuing ------------------------------------------------------------------


def test_issue_opens_the_invoice_and_logs_it():
    ledger = Ledger()
    made = issue(ledger, tax_rate="10")
    assert (made.status, made.due, made.balance) == ("open", date(2026, 2, 4), D("110.00"))
    assert events(ledger) == [(JAN_5, "acme", "invoice", "INV-1", D("110.00"))]


def test_issue_needs_a_line():
    ledger = Ledger()
    ledger.add(invoice(lines=[]))
    with pytest.raises(InvoiceError):
        ledger.issue("INV-1")
    assert ledger.invoices["INV-1"].status == "draft"
    assert ledger.events == []


def test_issue_refuses_a_negative_total():
    ledger = Ledger()
    ledger.add(invoice(lines=[Line("a", 1, "10.00"), Line("b", 1, "-10.01")]))
    with pytest.raises(InvoiceError):
        ledger.issue("INV-1")
    assert ledger.invoices["INV-1"].status == "draft"
    assert ledger.events == []


def test_issue_looks_at_the_total_and_not_at_the_net():
    # Net 5.00, but the taxable credit brings the total to -5.00.
    ledger = Ledger()
    lines = [Line("a", 1, "105.00", taxable=False), Line("b", 1, "-100.00")]
    ledger.add(invoice(lines=lines, tax_rate="10"))
    with pytest.raises(InvoiceError):
        ledger.issue("INV-1")


def test_issue_allows_a_zero_total():
    made = issue(Ledger(), lines=[Line("a", 1, "10.00"), Line("b", 1, "-10.00")])
    assert (made.total, made.status) == (D("0.00"), "paid")


def test_issue_allows_a_credit_line():
    assert issue(Ledger(), lines=[Line("a", 1, "10.00"), Line("b", 1, "-4.00")]).total == D("6.00")


def test_issuing_twice_is_refused():
    ledger = ledger_with(invoice())
    before = state(ledger)
    with pytest.raises(InvoiceError):
        ledger.issue("INV-1")
    assert state(ledger) == before


def test_issuing_a_paid_invoice_is_refused():
    ledger = ledger_with(invoice())
    ledger.receive("P1", "acme", "100.00", JAN_20)
    with pytest.raises(InvoiceError):
        ledger.issue("INV-1")


def test_issuing_a_void_invoice_is_refused():
    ledger = ledger_with(invoice())
    ledger.void("INV-1", JAN_20)
    before = state(ledger)
    with pytest.raises(InvoiceError):
        ledger.issue("INV-1")
    assert state(ledger) == before


# -- status -------------------------------------------------------------------


def test_status_through_an_invoice_life():
    ledger = Ledger()
    made = ledger.add(invoice())
    assert made.status == "draft"
    ledger.issue("INV-1")
    assert made.status == "open"
    ledger.receive("P1", "acme", "99.99", JAN_20)
    assert made.status == "open"
    ledger.receive("P2", "acme", "0.01", JAN_20)
    assert made.status == "paid"


def test_status_void():
    ledger = ledger_with(invoice())
    ledger.void("INV-1", JAN_20)
    assert ledger.invoices["INV-1"].status == "void"


def test_draft_with_nothing_owed_is_still_a_draft():
    assert invoice(price="0.00").status == "draft"


def test_owing_only_late_fees_is_open():
    ledger = owing_only_a_late_fee()
    made = ledger.invoices["INV-1"]
    assert (made.principal_due, made.fees_due) == (D("0.00"), D("15.00"))
    assert (made.status, made.balance) == ("open", D("15.00"))
    ledger.receive("P2", "acme", "15.00", LATE)
    assert (made.status, made.balance) == ("paid", D("0.00"))


# -- voiding ------------------------------------------------------------------


def test_void_writes_off_the_balance():
    ledger = ledger_with(invoice())
    ledger.void("INV-1", JAN_20)
    assert events(ledger, "void") == [(JAN_20, "acme", "void", "INV-1", D("-100.00"))]


def test_void_writes_off_late_fees_in_the_same_event():
    ledger = ledger_with(invoice(price="1000.00"))
    ledger.assess_late_fees(LATE)
    ledger.void("INV-1", LATE)
    assert events(ledger, "void") == [(LATE, "acme", "void", "INV-1", D("-1015.00"))]
    assert sum(e.amount for e in ledger.events) == 0


def test_void_disputed_invoice():
    ledger = ledger_with(invoice())
    ledger.dispute("INV-1")
    ledger.void("INV-1", JAN_20)
    assert ledger.invoices["INV-1"].status == "void"


def test_draft_cannot_be_voided():
    ledger = Ledger()
    ledger.add(invoice())
    with pytest.raises(InvoiceError):
        ledger.void("INV-1", JAN_20)
    assert ledger.invoices["INV-1"].status == "draft"
    assert ledger.events == []


def test_void_invoice_cannot_be_voided_again():
    ledger = ledger_with(invoice())
    ledger.void("INV-1", JAN_20)
    before = state(ledger)
    with pytest.raises(InvoiceError):
        ledger.void("INV-1", JAN_20)
    assert state(ledger) == before


@pytest.mark.parametrize("amount", ["0.01", "40.00", "100.00"])
def test_invoice_with_a_payment_cannot_be_voided(amount):
    ledger = ledger_with(invoice())
    ledger.receive("P1", "acme", amount, JAN_20)
    before = state(ledger)
    with pytest.raises(InvoiceError):
        ledger.void("INV-1", JAN_20)
    assert state(ledger) == before


def test_invoice_with_only_its_late_fee_paid_cannot_be_voided():
    ledger = ledger_with(invoice(price="1000.00"))
    ledger.assess_late_fees(LATE)
    ledger.receive("P1", "acme", "10.00", LATE)
    before = state(ledger)
    with pytest.raises(InvoiceError):
        ledger.void("INV-1", LATE)
    assert state(ledger) == before


# -- disputes, numbers --------------------------------------------------------


def test_dispute_and_resolve():
    ledger = ledger_with(invoice())
    ledger.dispute("INV-1")
    made = ledger.invoices["INV-1"]
    assert (made.disputed, made.status) == (True, "open")
    ledger.resolve("INV-1")
    assert (made.disputed, made.status) == (False, "open")


def _draft(ledger):
    ledger.add(invoice())


def _paid(ledger):
    issue(ledger)
    ledger.receive("P1", "acme", "100.00", JAN_20)


def _void(ledger):
    issue(ledger)
    ledger.void("INV-1", JAN_20)


@pytest.mark.parametrize("prepare", [_draft, _paid, _void])
def test_only_an_open_invoice_can_be_disputed(prepare):
    ledger = Ledger()
    prepare(ledger)
    with pytest.raises(InvoiceError):
        ledger.dispute("INV-1")
    assert not ledger.invoices["INV-1"].disputed


def test_duplicate_number_is_refused_and_the_first_kept():
    ledger = Ledger()
    ledger.add(invoice(price="1.00"))
    before = state(ledger)
    with pytest.raises(InvoiceError):
        ledger.add(invoice(price="2.00", customer="other"))
    assert state(ledger) == before


@pytest.mark.parametrize(
    "act",
    [
        lambda ledger: ledger.issue("INV-9"),
        lambda ledger: ledger.void("INV-9", JAN_20),
        lambda ledger: ledger.dispute("INV-9"),
        lambda ledger: ledger.resolve("INV-9"),
    ],
    ids=["issue", "void", "dispute", "resolve"],
)
def test_unknown_number_is_refused(act):
    ledger = ledger_with(invoice())
    with pytest.raises(InvoiceError):
        act(ledger)


def test_errors_share_a_base_class():
    with pytest.raises(TallyError):
        Ledger().issue("INV-9")
