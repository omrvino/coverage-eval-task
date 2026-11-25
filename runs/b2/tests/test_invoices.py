from datetime import date

import pytest

from helpers import D, JAN5, events, invoice, ledger_with
from tally import Invoice, InvoiceError, Ledger, Line


# R3.1 ---------------------------------------------------------------------

@pytest.mark.parametrize("qty, price, disc, expected", [
    (1, "100.00", 0, "100.00"),
    (3, "19.99", 0, "59.97"),
    (3, "19.99", 10, "53.97"),         # 53.973
    ("1.5", "10.00", 0, "15.00"),
    (2, "0.333", 0, "0.67"),           # 0.666
    (4, "25.00", 100, "0.00"),
    (2, "-10.00", 0, "-20.00"),        # credit line
    (10, "9.99", "12.5", "87.41"),     # 87.4125
])
def test_line_net(qty, price, disc, expected):
    assert Line("x", qty, price, disc).net == D(expected)


def test_each_line_is_rounded_to_the_cent_before_adding():
    lines = [Line("a", 1, "0.006"), Line("b", 1, "0.006"), Line("c", 1, "0.006")]
    assert [line.net for line in lines] == [D("0.01")] * 3
    assert invoice(lines=lines).net == D("0.03")
    lines = [Line("a", 1, "0.004"), Line("b", 1, "0.004"), Line("c", 1, "0.004")]
    assert invoice(lines=lines).net == D("0.00")


# R3.2 / R3.3 --------------------------------------------------------------

def test_tax_on_a_single_line():
    inv = invoice(lines=[Line("a", 1, "100.00")], tax_rate="8.25")
    assert inv.net == D("100.00")
    assert inv.tax == D("8.25")
    assert inv.total == D("108.25")


def test_non_taxable_lines_are_left_out_of_tax():
    lines = [Line("a", 1, "100.00"), Line("b", 1, "50.00", taxable=False)]
    inv = invoice(lines=lines, tax_rate=10)
    assert inv.net == D("150.00")
    assert inv.tax == D("10.00")
    assert inv.total == D("160.00")


def test_invoice_with_only_non_taxable_lines_has_no_tax():
    inv = invoice(lines=[Line("b", 1, "50.00", taxable=False)], tax_rate=10)
    assert inv.tax == 0
    assert inv.total == D("50.00")


def test_tax_exempt_invoice_has_no_tax():
    inv = invoice(lines=[Line("a", 1, "100.00")], tax_rate=10, tax_exempt=True)
    assert inv.tax == 0
    assert inv.total == D("100.00")


def test_tax_rate_zero_gives_no_tax():
    assert invoice(price="100.00").tax == 0


@pytest.mark.xfail(strict=True, reason="tax is rounded line by line")
def test_tax_is_rounded_once_on_the_taxable_sum():
    lines = [Line("a", 1, "1.00"), Line("b", 1, "1.00"), Line("c", 1, "1.00")]
    inv = invoice(lines=lines, tax_rate="8.25")
    assert inv.tax == D("0.25")           # 3.00 x 8.25% = 0.2475, not 3 x 0.08
    assert inv.total == D("3.25")


@pytest.mark.xfail(strict=True, reason="tax is rounded line by line")
def test_tax_once_ignores_non_taxable_lines_in_the_sum():
    lines = [Line("a", 1, "1.00"), Line("n", 1, "9.00", taxable=False),
             Line("b", 1, "1.00"), Line("c", 1, "1.00")]
    inv = invoice(lines=lines, tax_rate="8.25")
    assert inv.tax == D("0.25")
    assert inv.total == D("12.25")


# R3.4 ---------------------------------------------------------------------

@pytest.mark.parametrize("qty", [0, -1, "-0.5", "0.00"])
def test_quantity_must_be_positive(qty):
    with pytest.raises(InvoiceError):
        Line("x", qty, "10.00")


@pytest.mark.parametrize("disc", [-1, "-0.01", "100.01", 101, 1000])
def test_line_discount_must_be_between_0_and_100(disc):
    with pytest.raises(InvoiceError):
        Line("x", 1, "10.00", disc)


def test_line_discount_edges_and_tiny_quantity_are_allowed():
    assert Line("x", 1, "10.00", 0).net == D("10.00")
    assert Line("x", 1, "10.00", 100).net == D("0.00")
    assert Line("x", "0.001", "1000.00").net == D("1.00")


def test_unit_price_may_be_negative():
    assert Line("credit", 1, "-25.00").net == D("-25.00")


# R3.5 / R3.6 --------------------------------------------------------------

def test_new_invoice_is_a_draft_and_issue_opens_it():
    ledger = Ledger()
    ledger.add(invoice())
    inv = ledger.invoices["INV-1"]
    assert inv.status == "draft"
    ledger.issue("INV-1")
    assert inv.status == "open"
    assert inv.balance == D("100.00")
    assert inv.due == date(2026, 2, 4)


def test_issue_logs_one_invoice_event_for_the_total():
    ledger = ledger_with(invoice(lines=[Line("a", 1, "100.00")], tax_rate=10))
    [event] = ledger.events
    assert (event.kind, event.ref, event.customer) == ("invoice", "INV-1", "acme")
    assert event.date == JAN5
    assert event.amount == D("110.00")


def test_cannot_issue_without_lines():
    ledger = Ledger()
    ledger.add(invoice(lines=[]))
    with pytest.raises(InvoiceError):
        ledger.issue("INV-1")
    assert ledger.invoices["INV-1"].status == "draft"
    assert ledger.events == []


def test_cannot_issue_a_negative_total():
    ledger = Ledger()
    ledger.add(invoice(lines=[Line("credit", 1, "-0.01")]))
    with pytest.raises(InvoiceError):
        ledger.issue("INV-1")
    assert ledger.invoices["INV-1"].status == "draft"
    assert ledger.events == []


def test_a_total_of_zero_can_be_issued_and_counts_as_paid():
    lines = [Line("a", 1, "100.00"), Line("credit", 1, "-100.00")]
    ledger = ledger_with(invoice(lines=lines))
    assert ledger.invoices["INV-1"].total == 0
    assert ledger.invoices["INV-1"].status == "paid"


def test_cannot_issue_twice():
    ledger = ledger_with(invoice())
    with pytest.raises(InvoiceError):
        ledger.issue("INV-1")
    assert len(ledger.events) == 1


def test_cannot_issue_a_void_invoice():
    ledger = ledger_with(invoice())
    ledger.void("INV-1", date(2026, 1, 6))
    with pytest.raises(InvoiceError):
        ledger.issue("INV-1")
    assert ledger.invoices["INV-1"].status == "void"


def test_status_paid_needs_late_fees_paid_too():
    ledger = ledger_with(invoice(price="1000.00"))
    ledger.assess_late_fees(date(2026, 2, 20))          # one fee of 15.00
    inv = ledger.invoices["INV-1"]
    ledger.receive("P1", "acme", "1000.00", date(2026, 2, 20))
    assert inv.status == "open"
    assert inv.balance == D("15.00")
    ledger.receive("P2", "acme", "15.00", date(2026, 2, 21))
    assert inv.status == "paid"
    assert inv.balance == 0


def test_status_goes_back_to_open_when_a_payment_is_reversed():
    ledger = ledger_with(invoice())
    ledger.receive("P1", "acme", "100.00", date(2026, 1, 10))
    assert ledger.invoices["INV-1"].status == "paid"
    ledger.reverse("P1", date(2026, 1, 11))
    assert ledger.invoices["INV-1"].status == "open"


# R3.7 ---------------------------------------------------------------------

def test_void_writes_off_the_balance_as_one_event():
    ledger = ledger_with(invoice(price="1000.00"))
    ledger.assess_late_fees(date(2026, 2, 20))
    ledger.void("INV-1", date(2026, 2, 21))
    inv = ledger.invoices["INV-1"]
    assert inv.status == "void"
    [void] = events(ledger, "void")
    assert void.amount == D("-1015.00")
    assert void.date == date(2026, 2, 21)
    assert (void.ref, void.customer) == ("INV-1", "acme")
    assert sum(e.amount for e in ledger.events) == 0


def test_cannot_void_a_draft():
    ledger = Ledger()
    ledger.add(invoice())
    with pytest.raises(InvoiceError):
        ledger.void("INV-1", JAN5)
    assert ledger.invoices["INV-1"].status == "draft"
    assert ledger.events == []


def test_cannot_void_twice():
    ledger = ledger_with(invoice())
    ledger.void("INV-1", JAN5)
    with pytest.raises(InvoiceError):
        ledger.void("INV-1", JAN5)
    assert len(events(ledger, "void")) == 1


def test_cannot_void_once_a_payment_is_applied():
    ledger = ledger_with(invoice())
    ledger.receive("P1", "acme", "40.00", date(2026, 1, 10))
    count = len(ledger.events)
    with pytest.raises(InvoiceError):
        ledger.void("INV-1", date(2026, 1, 11))
    assert ledger.invoices["INV-1"].status == "open"
    assert len(ledger.events) == count


def test_cannot_void_when_a_payment_only_covered_late_fees():
    ledger = ledger_with(invoice(price="1000.00"))
    ledger.assess_late_fees(date(2026, 2, 20))
    ledger.receive("P1", "acme", "10.00", date(2026, 2, 21))
    with pytest.raises(InvoiceError):
        ledger.void("INV-1", date(2026, 2, 22))
    assert events(ledger, "void") == []


def test_cannot_void_a_paid_invoice():
    ledger = ledger_with(invoice())
    ledger.receive("P1", "acme", "100.00", date(2026, 1, 10))
    with pytest.raises(InvoiceError):
        ledger.void("INV-1", date(2026, 1, 11))


def test_can_void_after_the_payment_was_reversed():
    ledger = ledger_with(invoice())
    ledger.receive("P1", "acme", "40.00", date(2026, 1, 10))
    ledger.reverse("P1", date(2026, 1, 11))
    ledger.void("INV-1", date(2026, 1, 12))
    assert ledger.invoices["INV-1"].status == "void"
    assert events(ledger, "void")[0].amount == D("-100.00")


def test_void_leaves_other_invoices_alone():
    ledger = ledger_with(invoice("INV-1"), invoice("INV-2"))
    ledger.void("INV-1", JAN5)
    assert ledger.invoices["INV-2"].status == "open"


# R3.8 ---------------------------------------------------------------------

def test_dispute_an_open_invoice_and_resolve_it():
    ledger = ledger_with(invoice())
    ledger.dispute("INV-1")
    assert ledger.invoices["INV-1"].disputed is True
    ledger.resolve("INV-1")
    assert ledger.invoices["INV-1"].disputed is False


def test_cannot_dispute_a_draft():
    ledger = Ledger()
    ledger.add(invoice())
    with pytest.raises(InvoiceError):
        ledger.dispute("INV-1")
    assert ledger.invoices["INV-1"].disputed is False


def test_cannot_dispute_a_paid_invoice():
    ledger = ledger_with(invoice())
    ledger.receive("P1", "acme", "100.00", date(2026, 1, 10))
    with pytest.raises(InvoiceError):
        ledger.dispute("INV-1")
    assert ledger.invoices["INV-1"].disputed is False


def test_cannot_dispute_a_void_invoice():
    ledger = ledger_with(invoice())
    ledger.void("INV-1", date(2026, 1, 10))
    with pytest.raises(InvoiceError):
        ledger.dispute("INV-1")
    assert ledger.invoices["INV-1"].disputed is False


def test_duplicate_invoice_number_is_rejected():
    ledger = Ledger()
    first = invoice(price="10.00")
    ledger.add(first)
    with pytest.raises(InvoiceError):
        ledger.add(invoice(price="20.00"))
    assert ledger.invoices["INV-1"] is first


@pytest.mark.parametrize("action", [
    lambda ledger: ledger.issue("NOPE"),
    lambda ledger: ledger.void("NOPE", JAN5),
    lambda ledger: ledger.dispute("NOPE"),
    lambda ledger: ledger.resolve("NOPE"),
])
def test_unknown_invoice_numbers_raise(action):
    with pytest.raises(InvoiceError):
        action(ledger_with(invoice()))


def test_invoice_can_be_built_directly():
    inv = Invoice("X", "c", JAN5, "NET 30", [Line("a", 2, "5.00")])
    assert inv.total == D("10.00")
    assert inv.status == "draft"
