from datetime import date, timedelta
from decimal import Decimal as D

import pytest

from tally import Invoice, InvoiceError, Ledger, Line, statement

DAY = date(2026, 1, 5)


def make(lines=None, **kwargs):
    if lines is None:
        lines = [Line("work", 1, "100.00")]
    terms = kwargs.pop("terms", "NET 30")
    return Invoice("INV-1", "acme", DAY, terms, lines, **kwargs)


def ledger_with(invoice):
    ledger = Ledger()
    ledger.add(invoice)
    return ledger


def status(ledger):
    return ledger.invoices["INV-1"].status


# R3.1
def test_line_net_applies_line_discount_and_rounds_per_line():
    assert Line("x", 3, "9.99", "10").net == D("26.97")
    assert Line("y", 1, "0.333").net == D("0.33")
    assert make(lines=[Line("a", 1, "0.333"), Line("b", 1, "0.333")]).net == D("0.66")


def test_negative_unit_price_is_a_credit_line():
    assert Line("credit", 1, "-20").net == D("-20.00")
    assert make(lines=[Line("work", 1, "100"), Line("credit", 1, "-20")]).total == D("80.00")


# R3.2
def test_tax_is_charged_on_taxable_lines_only():
    invoice = make(lines=[Line("a", 1, "100"), Line("b", 1, "50", taxable=False)], tax_rate="10")
    assert invoice.net == D("150.00")
    assert invoice.tax == D("10.00")
    assert invoice.total == D("160.00")


def test_tax_rate_with_cents():
    assert make(tax_rate="8.25").tax == D("8.25")


@pytest.mark.xfail(strict=True, reason="tax is rounded per line and summed; spec R3.2 says tax on the summed taxable nets, rounded once")
def test_tax_is_rounded_once_on_the_sum_of_taxable_nets():
    invoice = make(lines=[Line("a", 1, "0.05"), Line("b", 1, "0.05")], tax_rate="10")
    assert invoice.tax == D("0.01")


# R3.3
def test_tax_exempt_invoice_has_no_tax():
    invoice = make(tax_rate="10", tax_exempt=True)
    assert invoice.tax == D("0.00")
    assert invoice.total == D("100.00")


# R3.4
@pytest.mark.parametrize("quantity", [0, -1, "0"])
def test_quantity_must_be_more_than_zero(quantity):
    with pytest.raises(InvoiceError):
        Line("x", quantity, "1")


@pytest.mark.parametrize("discount", ["-0.01", "100.01", "150"])
def test_line_discount_must_be_between_0_and_100(discount):
    with pytest.raises(InvoiceError):
        Line("x", 1, "10", discount)


@pytest.mark.parametrize("discount, net", [("0", "10.00"), ("100", "0.00")])
def test_line_discount_bounds_are_inclusive(discount, net):
    assert Line("x", 1, "10", discount).net == D(net)


def test_negative_unit_price_is_allowed_on_a_line():
    Line("credit", 1, "-5")


# R3.5
def test_issue_needs_at_least_one_line():
    ledger = ledger_with(make(lines=[]))
    with pytest.raises(InvoiceError):
        ledger.issue("INV-1")
    assert status(ledger) == "draft"


def test_issue_needs_a_total_of_zero_or_more():
    ledger = ledger_with(make(lines=[Line("credit", 1, "-5")]))
    with pytest.raises(InvoiceError):
        ledger.issue("INV-1")
    assert status(ledger) == "draft"


def test_zero_total_invoice_issues_and_is_paid():
    ledger = ledger_with(make(lines=[Line("free", 1, "0")]))
    ledger.issue("INV-1")
    assert status(ledger) == "paid"


def test_invoice_cannot_be_issued_twice():
    ledger = ledger_with(make())
    ledger.issue("INV-1")
    with pytest.raises(InvoiceError):
        ledger.issue("INV-1")


def test_void_invoice_cannot_be_issued():
    ledger = ledger_with(make())
    ledger.issue("INV-1")
    ledger.void("INV-1", DAY)
    with pytest.raises(InvoiceError):
        ledger.issue("INV-1")


# R3.6
def test_status_goes_draft_open_paid():
    ledger = ledger_with(make())
    assert status(ledger) == "draft"
    ledger.issue("INV-1")
    assert status(ledger) == "open"
    ledger.receive("P1", "acme", "100", DAY)
    assert status(ledger) == "paid"


def test_status_is_void_after_voiding():
    ledger = ledger_with(make())
    ledger.issue("INV-1")
    ledger.void("INV-1", DAY)
    assert status(ledger) == "void"


# R3.7
def test_void_needs_an_issued_invoice():
    ledger = ledger_with(make())
    with pytest.raises(InvoiceError):
        ledger.void("INV-1", DAY)


def test_invoice_can_only_be_voided_once():
    ledger = ledger_with(make())
    ledger.issue("INV-1")
    ledger.void("INV-1", DAY)
    with pytest.raises(InvoiceError):
        ledger.void("INV-1", DAY)


def test_void_is_refused_once_a_payment_is_applied():
    ledger = ledger_with(make())
    ledger.issue("INV-1")
    ledger.receive("P1", "acme", "10", DAY)
    with pytest.raises(InvoiceError):
        ledger.void("INV-1", DAY)
    assert status(ledger) == "open"


def test_void_is_refused_once_only_a_late_fee_has_been_paid():
    ledger = ledger_with(make())
    ledger.issue("INV-1")
    due = ledger.invoices["INV-1"].due
    ledger.assess_late_fees(due + timedelta(days=6))  # 5.00 fee
    ledger.receive("P1", "acme", "5", due + timedelta(days=7))
    with pytest.raises(InvoiceError):
        ledger.void("INV-1", due + timedelta(days=8))


def test_void_writes_off_whole_balance_with_late_fees_as_one_event():
    ledger = ledger_with(make())
    ledger.issue("INV-1")
    due = ledger.invoices["INV-1"].due
    ledger.assess_late_fees(due + timedelta(days=6))  # a 5.00 minimum fee
    ledger.void("INV-1", due + timedelta(days=10))
    voids = [e for e in ledger.events if e.kind == "void"]
    assert len(voids) == 1
    assert voids[0].amount == D("-105.00")
    assert voids[0].date == due + timedelta(days=10)
    assert status(ledger) == "void"
    assert statement(ledger, "acme", DAY, due + timedelta(days=30)).closing == D("0.00")


# R3.8
def test_only_open_invoices_can_be_disputed():
    draft = ledger_with(make())
    with pytest.raises(InvoiceError):
        draft.dispute("INV-1")

    paid = ledger_with(make())
    paid.issue("INV-1")
    paid.receive("P1", "acme", "100", DAY)
    with pytest.raises(InvoiceError):
        paid.dispute("INV-1")

    voided = ledger_with(make())
    voided.issue("INV-1")
    voided.void("INV-1", DAY)
    with pytest.raises(InvoiceError):
        voided.dispute("INV-1")


def test_open_invoice_can_be_disputed_and_resolved():
    ledger = ledger_with(make())
    ledger.issue("INV-1")
    ledger.dispute("INV-1")
    ledger.resolve("INV-1")
    assert status(ledger) == "open"


def test_duplicate_invoice_number_is_rejected():
    ledger = ledger_with(make())
    with pytest.raises(InvoiceError):
        ledger.add(make())


@pytest.mark.parametrize(
    "action",
    [
        lambda ledger: ledger.issue("NOPE"),
        lambda ledger: ledger.void("NOPE", DAY),
        lambda ledger: ledger.dispute("NOPE"),
        lambda ledger: ledger.resolve("NOPE"),
    ],
)
def test_unknown_invoice_number_is_rejected(action):
    with pytest.raises(InvoiceError):
        action(Ledger())
