from datetime import date
from decimal import Decimal

import pytest

from tally import Invoice, InvoiceError, Line

D = Decimal


def make(lines=None, **kwargs):
    if lines is None:
        lines = [Line("work", 1, "100.00")]
    terms = kwargs.pop("terms", "NET 30")
    return Invoice("INV-1", "acme", date(2026, 1, 5), terms, lines, **kwargs)


def test_line_net_applies_discount_and_rounds_per_line():
    assert Line("w", 3, "10.00", discount_pct="10").net == D("27.00")
    assert Line("w", 1, "10.00", discount_pct="33.33").net == D("6.67")


def test_line_discount_bounds_are_inclusive():
    assert Line("w", 1, "10.00", discount_pct=0).net == D("10.00")
    assert Line("w", 1, "10.00", discount_pct=100).net == D("0.00")


def test_line_may_have_a_negative_price_as_a_credit():
    assert Line("credit", 1, "-5.00").net == D("-5.00")


@pytest.mark.parametrize("quantity", [0, -1])
def test_line_quantity_must_be_positive(quantity):
    with pytest.raises(InvoiceError):
        Line("w", quantity, "1.00")


@pytest.mark.parametrize("discount", [-0.01, 100.01])
def test_line_discount_must_be_between_0_and_100(discount):
    with pytest.raises(InvoiceError):
        Line("w", 1, "1.00", discount_pct=discount)


def test_tax_is_charged_on_taxable_lines_only():
    lines = [Line("a", 1, "100.00"), Line("b", 1, "50.00", taxable=False)]
    invoice = make(lines, tax_rate="10")
    assert invoice.net == D("150.00")
    assert invoice.tax == D("10.00")
    assert invoice.total == D("160.00")


def test_no_taxable_lines_means_no_tax():
    invoice = make([Line("b", 1, "50.00", taxable=False)], tax_rate="10")
    assert invoice.tax == D("0.00")


def test_tax_exempt_invoice_has_no_tax():
    invoice = make(tax_rate="10", tax_exempt=True)
    assert invoice.tax == D("0.00")
    assert invoice.total == D("100.00")


def test_issue_sets_due_date_and_status():
    invoice = make()
    invoice.issue()
    assert invoice.issued
    assert invoice.due == date(2026, 2, 4)
    assert invoice.status == "open"


def test_issue_uses_holidays_for_due_date():
    invoice = make()
    invoice.issue(holidays={date(2026, 2, 4)})
    assert invoice.due == date(2026, 2, 5)


def test_issue_needs_at_least_one_line():
    with pytest.raises(InvoiceError):
        make([]).issue()


def test_issue_refuses_negative_total():
    with pytest.raises(InvoiceError):
        make([Line("credit", 1, "-5.00")]).issue()


def test_issue_twice_is_refused():
    invoice = make()
    invoice.issue()
    with pytest.raises(InvoiceError):
        invoice.issue()


def test_issue_a_voided_invoice_is_refused():
    invoice = make()
    invoice.issue()
    invoice.void()
    with pytest.raises(InvoiceError):
        invoice.issue()


def test_status_draft_then_paid_then_void():
    invoice = make()
    assert invoice.status == "draft"
    invoice.issue()
    invoice.paid = D("100.00")
    assert invoice.status == "paid"


def test_void_only_an_issued_unpaid_invoice():
    with pytest.raises(InvoiceError):
        make().void()

    invoice = make()
    invoice.issue()
    invoice.paid = D("1.00")
    with pytest.raises(InvoiceError):
        invoice.void()

    invoice.paid = D("0.00")
    invoice.fees_paid = D("1.00")
    with pytest.raises(InvoiceError):
        invoice.void()

    invoice.fees_paid = D("0.00")
    invoice.void()
    assert invoice.status == "void"
    with pytest.raises(InvoiceError):
        invoice.void()


def test_fees_due_and_balance_include_late_fees():
    invoice = make()
    invoice.issue()
    invoice.fees = D("15.00")
    invoice.fees_paid = D("5.00")
    assert invoice.fees_due == D("10.00")
    assert invoice.balance == D("110.00")


def test_early_discount_before_deadline_only():
    invoice = make(terms="2/10 NET 30")
    assert invoice.early_discount(date(2026, 1, 15)) == D("2.00")
    assert invoice.early_discount(date(2026, 1, 16)) == D("0.00")


def test_early_discount_is_a_percent_of_net_not_total():
    invoice = make(terms="2/10 NET 30", tax_rate="10")
    assert invoice.total == D("110.00")
    assert invoice.early_discount(date(2026, 1, 5)) == D("2.00")


def test_no_early_discount_without_discount_terms():
    assert make().early_discount(date(2026, 1, 5)) == D("0.00")


def test_no_early_discount_once_anything_is_paid():
    invoice = make(terms="2/10 NET 30")
    invoice.paid = D("1.00")
    assert invoice.early_discount(date(2026, 1, 5)) == D("0.00")
