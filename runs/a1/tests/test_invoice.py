from datetime import date
from decimal import Decimal

import pytest

from tally import Invoice, InvoiceError, Line

D = Decimal

XFAIL_TAX_ONCE = pytest.mark.xfail(
    strict=True,
    reason="R3.2: tax is rounded per line (each 0.006 becomes 0.01, total 0.02); the spec says tax is computed once on the summed net (0.012 becomes 0.01)",
)


def invoice(lines, **kwargs):
    return Invoice("INV-1", "acme", date(2026, 1, 5), "NET 30", lines, **kwargs)


def test_line_net_is_quantity_times_unit_price():
    assert str(Line("work", 3, "10.00").net) == "30.00"


def test_line_discount_is_a_percentage_of_the_gross():
    assert Line("work", 2, "50.00", discount_pct="10").net == D("90.00")


def test_line_net_is_rounded_to_the_cent():
    assert str(Line("work", 3, "1.334").net) == "4.00"  # 4.002
    assert str(Line("work", 1, "9.99", discount_pct="33.33").net) == "6.66"  # 6.660333


def test_unit_price_may_be_negative_for_a_credit_line():
    assert Line("credit", 1, "-40.00").net == D("-40.00")


@pytest.mark.parametrize("quantity", [0, -1])
def test_quantity_must_be_more_than_zero(quantity):
    with pytest.raises(InvoiceError):
        Line("work", quantity, "1.00")


@pytest.mark.parametrize("discount", ["-0.01", "100.01"])
def test_line_discount_must_be_between_0_and_100(discount):
    with pytest.raises(InvoiceError):
        Line("work", 1, "1.00", discount_pct=discount)


def test_line_discount_limits_are_inclusive():
    assert Line("free", 1, "5.00", discount_pct="100").net == D("0.00")
    assert Line("full", 1, "5.00", discount_pct="0").net == D("5.00")


def test_tax_is_charged_on_taxable_lines_only():
    inv = invoice([Line("a", 1, "100.00"), Line("b", 1, "50.00", taxable=False)], tax_rate="10")
    assert inv.net == D("150.00")
    assert inv.tax == D("10.00")
    assert inv.total == D("160.00")


def test_tax_is_rounded_to_the_cent():
    inv = invoice([Line("a", 1, "33.33")], tax_rate="8.25")  # 2.749725
    assert inv.tax == D("2.75")
    assert inv.total == D("36.08")


@XFAIL_TAX_ONCE
def test_tax_is_computed_once_on_the_summed_nets():
    inv = invoice([Line("a", 1, "0.02"), Line("b", 1, "0.02")], tax_rate="30")
    assert inv.net == D("0.04")
    assert inv.tax == D("0.01")


def test_tax_exempt_invoice_has_no_tax():
    inv = invoice([Line("a", 1, "100.00")], tax_rate="10", tax_exempt=True)
    assert inv.tax == 0
    assert inv.total == D("100.00")


def test_new_invoice_is_a_draft_with_no_due_date():
    inv = invoice([Line("a", 1, "100.00")])
    assert inv.status == "draft"
    assert inv.due is None
