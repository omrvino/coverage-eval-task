from datetime import date
from decimal import Decimal

import pytest

from tally import Invoice, InvoiceError, Ledger, Line, TermsError

from helpers import D0, issued, kinds, make_invoice

D = Decimal


def invoice_with(lines, **kwargs):
    return Invoice("INV-1", "acme", date(2026, 2, 2), "NET 30", lines, **kwargs)


# -- R3.1 ------------------------------------------------------------------

def test_line_net_is_quantity_times_price():
    assert Line("a", 3, "19.99").net == D("59.97")
    assert Line("a", "2.5", "10.00").net == D("25.00")


def test_line_discount_is_taken_off_and_rounded_per_line():
    assert Line("a", 3, "19.99", discount_pct=10).net == D("53.97")      # 53.973
    assert Line("a", 1, "100.00", discount_pct=100).net == D("0.00")
    assert Line("a", 1, "100.00", discount_pct="12.5").net == D("87.50")


def test_invoice_net_adds_rounded_lines():
    lines = [Line("a", 3, "0.333"), Line("b", 3, "0.333")]   # each 0.999 -> 1.00
    assert invoice_with(lines).net == D("2.00")


def test_negative_unit_price_is_a_credit_line():
    inv = invoice_with([Line("work", 1, "100.00"), Line("credit", 1, "-30.00")])
    assert inv.net == D("70.00")


# -- R3.2 / R3.3 -----------------------------------------------------------

@pytest.mark.xfail(strict=True, reason="tax is rounded per line")
def test_tax_is_computed_once_on_the_sum_of_taxable_nets():
    lines = [Line("a", 1, "0.30"), Line("b", 1, "0.30")]
    inv = invoice_with(lines, tax_rate=5)
    assert inv.tax == D("0.03")           # 0.60 x 5%, not 0.02 + 0.02
    assert inv.total == D("0.63")


@pytest.mark.xfail(strict=True, reason="tax is rounded per line")
def test_tax_is_not_rounded_per_line():
    inv = invoice_with([Line("a", 1, "0.04")] * 10, tax_rate=10)
    assert inv.tax == D("0.04")           # 0.40 x 10%; per line would give 0.00


def test_non_taxable_lines_are_left_out_of_tax():
    lines = [Line("a", 1, "100.00"), Line("b", 1, "50.00", taxable=False)]
    inv = invoice_with(lines, tax_rate=10)
    assert inv.tax == D("10.00")
    assert inv.net == D("150.00")
    assert inv.total == D("160.00")


def test_tax_on_discounted_line_uses_the_line_net():
    inv = invoice_with([Line("a", 1, "200.00", discount_pct=50)], tax_rate=10)
    assert inv.tax == D("10.00")


def test_tax_exempt_invoice_has_no_tax():
    inv = invoice_with([Line("a", 1, "100.00")], tax_rate=10, tax_exempt=True)
    assert inv.tax == D("0.00")
    assert inv.total == D("100.00")


def test_no_tax_rate_means_no_tax():
    assert invoice_with([Line("a", 1, "100.00")]).tax == D("0.00")


# -- R3.4 ------------------------------------------------------------------

@pytest.mark.parametrize("quantity", [0, -1, "-0.5"])
def test_quantity_must_be_more_than_zero(quantity):
    with pytest.raises(InvoiceError):
        Line("a", quantity, "1.00")


@pytest.mark.parametrize("pct", [-1, "-0.01", "100.01", 101])
def test_line_discount_must_be_between_0_and_100(pct):
    with pytest.raises(InvoiceError):
        Line("a", 1, "1.00", discount_pct=pct)


def test_small_quantity_and_edge_discounts_are_fine():
    assert Line("a", "0.001", "1000.00").net == D("1.00")
    assert Line("a", 1, "10.00", discount_pct=0).net == D("10.00")


# -- R3.5 ------------------------------------------------------------------

def test_issuing_sets_the_due_date_and_logs_one_invoice_event():
    ledger = issued(make_invoice(price="250.00"))
    inv = ledger.invoices["INV-1"]
    assert inv.due == D0
    assert [(e.kind, e.ref, e.amount) for e in ledger.events] == [("invoice", "INV-1", D("250.00"))]
    assert ledger.events[0].customer == "acme"
    assert ledger.events[0].date == inv.date


def test_issue_moves_due_date_past_weekends_and_holidays():
    ledger = Ledger([date(2026, 3, 9)])
    ledger.add(Invoice("A", "acme", date(2026, 2, 5), "NET 30", [Line("w", 1, "10")]))
    ledger.issue("A")
    assert ledger.invoices["A"].due == date(2026, 3, 10)     # Sat -> Sun -> Mon holiday -> Tue


def test_cannot_issue_without_lines():
    ledger = Ledger()
    ledger.add(Invoice("A", "acme", date(2026, 2, 2), "NET 30"))
    with pytest.raises(InvoiceError):
        ledger.issue("A")
    assert ledger.invoices["A"].status == "draft"
    assert ledger.events == []


def test_cannot_issue_a_negative_total():
    ledger = Ledger()
    ledger.add(make_invoice(lines=[Line("a", 1, "10.00"), Line("c", 1, "-10.01")]))
    with pytest.raises(InvoiceError):
        ledger.issue("INV-1")
    assert ledger.invoices["INV-1"].status == "draft"


def test_a_zero_total_can_be_issued():
    ledger = issued(make_invoice(lines=[Line("a", 1, "10.00"), Line("c", 1, "-10.00")]))
    assert ledger.invoices["INV-1"].total == D("0.00")
    assert ledger.invoices["INV-1"].status == "paid"


def test_cannot_issue_twice_or_a_void_invoice():
    ledger = issued(make_invoice())
    with pytest.raises(InvoiceError):
        ledger.issue("INV-1")
    ledger.void("INV-1", D0)
    with pytest.raises(InvoiceError):
        ledger.issue("INV-1")
    assert len(kinds(ledger, "invoice")) == 1


def test_bad_terms_stop_issuing():
    ledger = Ledger()
    ledger.add(make_invoice(terms="whenever"))
    with pytest.raises(TermsError):
        ledger.issue("INV-1")
    assert ledger.invoices["INV-1"].status == "draft"


# -- R3.6 ------------------------------------------------------------------

def test_status_follows_the_invoice_through_its_life():
    ledger = Ledger()
    inv = ledger.add(make_invoice())
    assert inv.status == "draft"
    ledger.issue("INV-1")
    assert inv.status == "open"
    ledger.receive("P1", "acme", "99.99", D0)
    assert inv.status == "open"
    ledger.receive("P2", "acme", "0.01", D0)
    assert inv.status == "paid"


def test_an_invoice_is_not_paid_while_late_fees_are_owed():
    ledger = issued(make_invoice(price="1000.00"))
    ledger.assess_late_fees(date(2026, 3, 20))
    ledger.receive("P1", "acme", "1000.00", date(2026, 3, 20))
    inv = ledger.invoices["INV-1"]
    assert inv.status == "open"
    assert inv.balance == D("15.00")
    ledger.receive("P2", "acme", "15.00", date(2026, 3, 21))
    assert inv.status == "paid"


def test_voided_invoice_status_is_void():
    ledger = issued(make_invoice())
    ledger.void("INV-1", D0)
    assert ledger.invoices["INV-1"].status == "void"


# -- R3.7 ------------------------------------------------------------------

def test_void_writes_off_the_whole_balance_as_one_event():
    ledger = issued(make_invoice(price="1000.00"))
    ledger.assess_late_fees(date(2026, 3, 20))                  # fee 15.00
    ledger.void("INV-1", date(2026, 3, 25))
    voids = kinds(ledger, "void")
    assert len(voids) == 1
    assert voids[0].amount == D("-1015.00")
    assert voids[0].date == date(2026, 3, 25)
    assert voids[0].ref == "INV-1"
    assert voids[0].customer == "acme"
    assert ledger.invoices["INV-1"].status == "void"


def test_void_amount_includes_tax():
    ledger = issued(make_invoice(price="100.00", tax_rate=10))
    ledger.void("INV-1", D0)
    assert kinds(ledger, "void")[0].amount == D("-110.00")


def test_cannot_void_a_draft():
    ledger = Ledger()
    ledger.add(make_invoice())
    with pytest.raises(InvoiceError):
        ledger.void("INV-1", D0)
    assert ledger.events == []


def test_cannot_void_twice():
    ledger = issued(make_invoice())
    ledger.void("INV-1", D0)
    with pytest.raises(InvoiceError):
        ledger.void("INV-1", D0)
    assert len(kinds(ledger, "void")) == 1


def test_cannot_void_with_a_payment_applied():
    ledger = issued(make_invoice())
    ledger.receive("P1", "acme", "10.00", D0)
    with pytest.raises(InvoiceError):
        ledger.void("INV-1", D0)
    assert ledger.invoices["INV-1"].status == "open"
    assert kinds(ledger, "void") == []


def test_cannot_void_a_paid_invoice():
    ledger = issued(make_invoice())
    ledger.receive("P1", "acme", "100.00", D0)
    with pytest.raises(InvoiceError):
        ledger.void("INV-1", D0)


def test_can_void_after_the_payment_was_reversed():
    ledger = issued(make_invoice())
    ledger.receive("P1", "acme", "40.00", D0)
    ledger.reverse("P1", D0)
    ledger.void("INV-1", D0)
    assert kinds(ledger, "void")[0].amount == D("-100.00")


def test_cannot_void_when_only_late_fees_were_paid():
    ledger = issued(make_invoice(price="1000.00"))
    ledger.assess_late_fees(date(2026, 3, 20))
    ledger.dispute("INV-1")
    ledger.resolve("INV-1")
    ledger.receive("P1", "acme", "10.00", date(2026, 3, 20))
    with pytest.raises(InvoiceError):
        ledger.void("INV-1", date(2026, 3, 21))


# -- R3.8 ------------------------------------------------------------------

@pytest.mark.parametrize("setup", ["draft", "paid", "void"])
def test_only_an_open_invoice_can_be_disputed(setup):
    ledger = Ledger()
    ledger.add(make_invoice())
    if setup != "draft":
        ledger.issue("INV-1")
    if setup == "paid":
        ledger.receive("P1", "acme", "100.00", D0)
    if setup == "void":
        ledger.void("INV-1", D0)
    with pytest.raises(InvoiceError):
        ledger.dispute("INV-1")
    assert not ledger.invoices["INV-1"].disputed


def test_dispute_and_resolve_toggle_the_flag():
    ledger = issued(make_invoice())
    ledger.dispute("INV-1")
    assert ledger.invoices["INV-1"].disputed
    ledger.resolve("INV-1")
    assert not ledger.invoices["INV-1"].disputed


def test_duplicate_invoice_number_is_rejected():
    ledger = Ledger()
    ledger.add(make_invoice())
    with pytest.raises(InvoiceError):
        ledger.add(make_invoice(customer="other"))
    assert ledger.invoices["INV-1"].customer == "acme"


def test_add_returns_the_invoice():
    ledger = Ledger()
    inv = make_invoice()
    assert ledger.add(inv) is inv
    assert ledger.invoices["INV-1"] is inv


@pytest.mark.parametrize("action", [
    lambda ledger: ledger.issue("NOPE"),
    lambda ledger: ledger.void("NOPE", D0),
    lambda ledger: ledger.dispute("NOPE"),
    lambda ledger: ledger.resolve("NOPE"),
])
def test_unknown_invoice_number_is_rejected(action):
    with pytest.raises(InvoiceError):
        action(Ledger())
