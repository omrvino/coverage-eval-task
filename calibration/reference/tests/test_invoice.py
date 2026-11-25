from datetime import date
from decimal import Decimal as D

import pytest

from tally import Invoice, InvoiceError, Ledger, Line

DAY = date(2026, 1, 5)


def ledger_with(*lines, terms="NET 30", **kw):
    ledger = Ledger()
    ledger.add(Invoice("INV-1", "acme", DAY, terms, list(lines), **kw))
    return ledger, ledger.invoices["INV-1"]


def test_line_net_rounds_each_line():
    assert Line("a", 3, "0.333").net == D("1.00")
    assert Line("a", 1, "10.00", "12.5").net == D("8.75")
    _, inv = ledger_with(Line("a", 1, "0.333"), Line("b", 1, "0.333"), Line("c", 1, "0.333"))
    assert inv.net == D("0.99")
    assert str(Line("a", 1, "0.333").net) == "0.33"


def test_line_limits():
    assert Line("a", 1, "10.00", 100).net == 0
    assert Line("a", 1, "10.00", 0).net == D("10.00")
    assert Line("a", 1, "-10.00").net == D("-10.00")
    for quantity, discount in [(0, 0), (-1, 0), (1, 101), (1, -1)]:
        with pytest.raises(InvoiceError):
            Line("a", quantity, "1.00", discount)


def test_tax_on_taxable_lines_only():
    _, inv = ledger_with(Line("a", 1, "100.00"), Line("b", 1, "50.00", taxable=False), tax_rate="6")
    assert inv.tax == D("6.00")
    assert inv.total == D("156.00")


@pytest.mark.xfail(strict=True, reason="R3.2: tax rounded per line")
def test_tax_rounds_once():
    _, inv = ledger_with(*[Line("a", 1, "0.06") for _ in range(10)], tax_rate="6")
    assert inv.tax == D("0.04")


def test_tax_exempt():
    _, inv = ledger_with(Line("a", 1, "100.00"), tax_rate="6", tax_exempt=True)
    assert inv.tax == 0 and inv.total == D("100.00")


def test_issue_rules():
    ledger, inv = ledger_with(Line("a", 1, "1.00"))
    assert inv.status == "draft"
    ledger.issue("INV-1")
    assert inv.status == "open"
    with pytest.raises(InvoiceError):
        ledger.issue("INV-1")
    ledger.void("INV-1", DAY)
    with pytest.raises(InvoiceError):
        ledger.issue("INV-1")


def test_issue_needs_lines_and_nonnegative_total():
    ledger, _ = ledger_with()
    with pytest.raises(InvoiceError):
        ledger.issue("INV-1")
    ledger, _ = ledger_with(Line("a", 1, "-1.00"))
    with pytest.raises(InvoiceError):
        ledger.issue("INV-1")
    ledger, inv = ledger_with(Line("a", 1, "1.00"), Line("b", 1, "-1.00"))
    ledger.issue("INV-1")
    assert inv.status == "paid"


def test_paid_means_fees_too():
    ledger, inv = ledger_with(Line("a", 1, "1000.00"))
    ledger.issue("INV-1")
    ledger.assess_late_fees(date(2026, 2, 20))
    ledger.receive("P1", "acme", "1000.00", date(2026, 2, 21))
    assert inv.balance == D("15.00")
    assert inv.status == "open"
    ledger.receive("P2", "acme", "15.00", date(2026, 2, 21))
    assert inv.status == "paid"


def test_void_rules():
    ledger, inv = ledger_with(Line("a", 1, "1000.00"))
    with pytest.raises(InvoiceError):
        ledger.void("INV-1", DAY)
    ledger.issue("INV-1")
    ledger.assess_late_fees(date(2026, 2, 20))
    ledger.void("INV-1", date(2026, 2, 21))
    assert inv.status == "void"
    assert (ledger.events[-1].kind, ledger.events[-1].amount) == ("void", D("-1015.00"))
    with pytest.raises(InvoiceError):
        ledger.void("INV-1", date(2026, 2, 22))


@pytest.mark.parametrize("amount", ["5.00", "500.00"])
def test_no_void_after_payment(amount):
    ledger, inv = ledger_with(Line("a", 1, "1000.00"))
    ledger.issue("INV-1")
    ledger.assess_late_fees(date(2026, 2, 20))
    ledger.receive("P1", "acme", amount, date(2026, 2, 21))
    with pytest.raises(InvoiceError):
        ledger.void("INV-1", date(2026, 2, 22))
    assert inv.status == "open"


def test_dispute_and_lookup_errors():
    ledger, inv = ledger_with(Line("a", 1, "1.00"))
    with pytest.raises(InvoiceError):
        ledger.dispute("INV-1")
    for call in (ledger.issue, ledger.dispute, ledger.resolve):
        with pytest.raises(InvoiceError):
            call("NOPE")
    with pytest.raises(InvoiceError):
        ledger.void("NOPE", DAY)
    with pytest.raises(InvoiceError):
        ledger.add(Invoice("INV-1", "other", DAY, "EOM"))
    ledger.issue("INV-1")
    ledger.dispute("INV-1")
    assert inv.disputed
    ledger.resolve("INV-1")
    assert not inv.disputed


def test_open_when_only_fees_are_owed():
    ledger, inv = ledger_with(Line("a", 1, "1000.00"))
    ledger.issue("INV-1")
    ledger.assess_late_fees(date(2026, 2, 20))
    ledger.receive("P1", "acme", "15.00", date(2026, 2, 21))
    ledger.receive("P2", "acme", "1000.00", date(2026, 2, 22))
    assert inv.status == "paid"
    ledger.reverse("P1", date(2026, 2, 23))
    assert (inv.principal_due, inv.fees_due, inv.status) == (0, D("15.00"), "open")
