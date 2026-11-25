from datetime import date
from decimal import Decimal

import pytest

from tally import Invoice, InvoiceError, Line


def make(lines, terms="NET 30", **kwargs):
    return Invoice("INV-1", "acme", date(2026, 1, 5), terms, list(lines), **kwargs)


def issued(lines, terms="NET 30", **kwargs):
    invoice = make(lines, terms, **kwargs)
    invoice.issue()
    return invoice


def test_line_net_applies_line_discount():
    assert Line("work", 3, "9.99", discount_pct="10").net == Decimal("26.97")


def test_line_net_rounds_to_the_cent():
    assert Line("work", 1, "33.33", discount_pct="2").net == Decimal("32.66")


def test_line_net_can_be_a_negative_credit():
    assert Line("credit", 1, "-20.00").net == Decimal("-20.00")


@pytest.mark.parametrize("quantity", [0, -1])
def test_line_quantity_must_be_positive(quantity):
    with pytest.raises(InvoiceError):
        Line("work", quantity, "10")


@pytest.mark.parametrize("discount", ["-0.01", "100.01"])
def test_line_discount_must_be_between_zero_and_one_hundred(discount):
    with pytest.raises(InvoiceError):
        Line("work", 1, "10", discount_pct=discount)


def test_line_discount_bounds_are_inclusive():
    assert Line("free", 1, "10", discount_pct="100").net == Decimal("0.00")
    assert Line("work", 1, "10", discount_pct="0").net == Decimal("10.00")


def test_tax_is_charged_on_taxable_lines_only():
    invoice = make([Line("a", 1, "100.00"), Line("b", 1, "50.00", taxable=False)], tax_rate="10")
    assert invoice.net == Decimal("150.00")
    assert invoice.tax == Decimal("10.00")
    assert invoice.total == Decimal("160.00")


def test_tax_exempt_invoice_has_no_tax():
    invoice = make([Line("a", 1, "100.00")], tax_rate="10", tax_exempt=True)
    assert invoice.tax == Decimal("0.00")
    assert invoice.total == Decimal("100.00")


@pytest.mark.xfail(strict=True, reason="R3.2: tax is computed once on the taxable sum, never per line")
def test_tax_is_rounded_once_not_per_line():
    invoice = make([Line("a", 1, "0.05"), Line("b", 1, "0.05")], tax_rate="10")
    assert invoice.tax == Decimal("0.01")


def test_issue_sets_due_date_and_opens_the_invoice():
    invoice = make([Line("a", 1, "100.00")])
    assert invoice.status == "draft"
    invoice.issue()
    assert invoice.due == date(2026, 2, 4)
    assert invoice.status == "open"


def test_issue_uses_holidays_for_the_due_date():
    invoice = make([Line("a", 1, "100.00")], terms="NET 5")
    invoice.issue(frozenset({date(2026, 1, 12)}))
    assert invoice.due == date(2026, 1, 13)


def test_issue_needs_at_least_one_line():
    with pytest.raises(InvoiceError):
        make([]).issue()


def test_issue_refuses_a_negative_total():
    with pytest.raises(InvoiceError):
        make([Line("credit", 1, "-10.00")]).issue()


def test_issue_allows_a_zero_total_which_is_paid_at_once():
    invoice = issued([Line("free", 1, "0")])
    assert invoice.status == "paid"


def test_issue_twice_is_refused():
    invoice = issued([Line("a", 1, "1")])
    with pytest.raises(InvoiceError):
        invoice.issue()


def test_voided_invoice_cannot_be_issued():
    invoice = issued([Line("a", 1, "1")])
    invoice.void()
    with pytest.raises(InvoiceError):
        invoice.issue()


def test_void_writes_off_an_issued_invoice():
    invoice = issued([Line("a", 1, "100.00")])
    invoice.void()
    assert invoice.status == "void"


def test_void_needs_an_issued_invoice():
    with pytest.raises(InvoiceError):
        make([Line("a", 1, "100.00")]).void()


def test_void_twice_is_refused():
    invoice = issued([Line("a", 1, "100.00")])
    invoice.void()
    with pytest.raises(InvoiceError):
        invoice.void()


@pytest.mark.parametrize("field", ["paid", "fees_paid"])
def test_void_is_refused_once_money_has_been_applied(field):
    invoice = issued([Line("a", 1, "100.00")])
    setattr(invoice, field, Decimal("1.00"))
    with pytest.raises(InvoiceError):
        invoice.void()


def test_balance_counts_late_fees_until_they_are_paid():
    invoice = issued([Line("a", 1, "100.00")])
    invoice.fees = Decimal("5.00")
    assert invoice.principal_due == Decimal("100.00")
    assert invoice.fees_due == Decimal("5.00")
    assert invoice.balance == Decimal("105.00")
    assert invoice.status == "open"
    invoice.fees_paid = Decimal("5.00")
    invoice.paid = Decimal("100.00")
    assert invoice.balance == Decimal("0.00")
    assert invoice.status == "paid"


def test_early_discount_is_percent_of_net_before_tax():
    invoice = issued([Line("a", 1, "100.00")], terms="2/10 NET 30", tax_rate="10")
    assert invoice.early_discount(date(2026, 1, 15)) == Decimal("2.00")


def test_early_discount_is_rounded_to_the_cent():
    invoice = issued([Line("a", 1, "33.33")], terms="2/10 NET 30")
    assert invoice.early_discount(date(2026, 1, 15)) == Decimal("0.67")


def test_early_discount_stops_after_the_deadline():
    invoice = issued([Line("a", 1, "100.00")], terms="2/10 NET 30")
    assert invoice.early_discount(date(2026, 1, 15)) == Decimal("2.00")
    assert invoice.early_discount(date(2026, 1, 16)) == Decimal("0.00")


def test_no_early_discount_without_discount_terms_or_after_an_earlier_payment():
    plain = issued([Line("a", 1, "100.00")])
    assert plain.early_discount(date(2026, 1, 6)) == Decimal("0.00")
    already_paid = issued([Line("a", 1, "100.00")], terms="2/10 NET 30")
    already_paid.paid = Decimal("1.00")
    assert already_paid.early_discount(date(2026, 1, 6)) == Decimal("0.00")
