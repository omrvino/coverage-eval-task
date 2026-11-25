from datetime import date
from decimal import Decimal as D

import pytest

from tally import Invoice, Ledger, Line, PaymentError

DAY = date(2026, 1, 5)          # Monday


def ledger_with(*specs, tax_rate=0):
    """specs: (number, price, terms) or (number, price, terms, date)."""
    ledger = Ledger()
    for number, price, terms, *day in specs:
        ledger.add(Invoice(number, "acme", day[0] if day else DAY, terms, [Line("w", 1, price)], tax_rate=tax_rate))
        ledger.issue(number)
    return ledger


def test_oldest_due_first():
    ledger = ledger_with(("A-1", "100", "NET 60"), ("A-2", "100", "NET 30"))
    ledger.receive("P", "acme", "150", date(2026, 1, 8))
    assert ledger.invoices["A-2"].balance == 0
    assert ledger.invoices["A-1"].balance == D("50.00")


@pytest.mark.xfail(strict=True, reason="R4.1: numbers sorted as text")
def test_equal_due_dates_go_by_number():
    ledger = ledger_with(("INV-10", "100", "NET 30"), ("INV-2", "100", "NET 30"))
    ledger.receive("P", "acme", "100", date(2026, 1, 8))
    assert ledger.invoices["INV-2"].status == "paid"
    assert ledger.invoices["INV-10"].status == "open"


def test_equal_due_dates_same_width_numbers():
    ledger = ledger_with(("INV-3", "100", "NET 30"), ("INV-2", "100", "NET 30"))
    ledger.receive("P", "acme", "100", date(2026, 1, 8))
    assert ledger.invoices["INV-2"].status == "paid"


def test_fees_before_principal():
    ledger = ledger_with(("A", "1000", "NET 30"))
    ledger.assess_late_fees(date(2026, 2, 20))
    payment = ledger.receive("P", "acme", "20", date(2026, 2, 21))
    inv = ledger.invoices["A"]
    assert (inv.fees_due, inv.principal_due) == (0, D("995.00"))
    assert (payment.allocations[0].fees, payment.allocations[0].principal) == (D("15.00"), D("5.00"))


def test_early_discount_on_net_on_the_deadline():
    ledger = ledger_with(("A", "100", "2/10 NET 30"), tax_rate=10)
    payment = ledger.receive("P", "acme", "108", date(2026, 1, 15))
    inv = ledger.invoices["A"]
    assert inv.status == "paid" and inv.discount_taken == D("2.00")
    assert payment.allocations[0].discount == D("2.00") and payment.credit == 0
    assert [(e.kind, e.amount) for e in ledger.events[1:]] == [("payment", D("-108.00")), ("discount", D("-2.00"))]


@pytest.mark.parametrize("amount, day", [("108", date(2026, 1, 16)), ("107.99", date(2026, 1, 15))])
def test_no_discount_when_late_or_short(amount, day):
    ledger = ledger_with(("A", "100", "2/10 NET 30"), tax_rate=10)
    ledger.receive("P", "acme", amount, day)
    assert ledger.invoices["A"].discount_taken == 0
    assert ledger.invoices["A"].balance == D("110.00") - D(amount)


def test_no_discount_after_an_earlier_payment():
    ledger = ledger_with(("A", "100", "2/10 NET 30"))
    ledger.receive("P1", "acme", "50", date(2026, 1, 8))
    ledger.receive("P2", "acme", "48", date(2026, 1, 9))
    assert ledger.invoices["A"].balance == D("2.00")


def test_leftover_becomes_credit():
    ledger = ledger_with(("A", "100", "NET 30"))
    payment = ledger.receive("P", "acme", "130", date(2026, 1, 8))
    assert payment.credit == ledger.credit("acme") == D("30.00")
    assert ledger.credit("other") == 0


def test_repeat_payment_id():
    ledger = ledger_with(("A", "100", "NET 30"))
    first = ledger.receive("P", "acme", "40", date(2026, 1, 8))
    assert ledger.receive("P", "acme", "40.00", date(2026, 1, 9)) is first
    assert ledger.invoices["A"].balance == D("60.00")
    assert [e.kind for e in ledger.events] == ["invoice", "payment"]
    for customer, amount in (("acme", "41"), ("other", "40")):
        with pytest.raises(PaymentError):
            ledger.receive("P", customer, amount, date(2026, 1, 9))


@pytest.mark.parametrize("amount", ["0", "-5"])
def test_amount_must_be_positive(amount):
    with pytest.raises(PaymentError):
        Ledger().receive("P", "acme", amount, DAY)


def test_disputed_draft_and_void_receive_nothing():
    ledger = ledger_with(("A", "100", "NET 30"), ("B", "100", "NET 30"))
    ledger.add(Invoice("C", "acme", DAY, "NET 0", [Line("w", 1, "100")]))
    ledger.dispute("A")
    ledger.void("B", DAY)
    payment = ledger.receive("P", "acme", "100", date(2026, 1, 8))
    assert payment.allocations == [] and payment.credit == D("100.00")
    ledger.resolve("A")
    ledger.apply_credit("acme", date(2026, 1, 9))
    assert ledger.invoices["A"].status == "paid"


def test_other_customers_untouched():
    ledger = ledger_with(("A", "100", "NET 30"))
    ledger.receive("P", "other", "100", date(2026, 1, 8))
    assert ledger.invoices["A"].balance == D("100.00")


def test_reverse_restores_principal_fees_and_credit():
    ledger = ledger_with(("A", "1000", "NET 30"))
    ledger.assess_late_fees(date(2026, 2, 20))
    ledger.receive("P", "acme", "1100", date(2026, 2, 21))
    assert ledger.credit("acme") == D("85.00")
    ledger.reverse("P", date(2026, 2, 25))
    inv = ledger.invoices["A"]
    assert (inv.status, inv.principal_due, inv.fees_due) == ("open", D("1000.00"), D("15.00"))
    assert ledger.credit("acme") == 0
    assert (ledger.events[-1].kind, ledger.events[-1].amount) == ("reversal", D("1100.00"))
    with pytest.raises(PaymentError):
        ledger.reverse("P", date(2026, 2, 26))
    with pytest.raises(PaymentError):
        ledger.receive("P", "acme", "1100", date(2026, 2, 26))


@pytest.mark.xfail(strict=True, reason="R4.8: the discount stays")
def test_reverse_revokes_the_discount():
    ledger = ledger_with(("A", "100", "2/10 NET 30"))
    ledger.receive("P", "acme", "98", date(2026, 1, 8))
    ledger.reverse("P", date(2026, 1, 20))
    assert ledger.events[-1].amount == D("100.00")
    assert ledger.invoices["A"].balance == D("100.00")


def test_reverse_unknown():
    with pytest.raises(PaymentError):
        Ledger().reverse("P", DAY)


def test_no_reverse_after_credit_was_used():
    ledger = ledger_with(("A", "100", "NET 30"))
    ledger.receive("P", "acme", "150", date(2026, 1, 8))
    ledger.add(Invoice("B", "acme", DAY, "NET 30", [Line("w", 1, "20")]))
    ledger.issue("B")
    events = len(ledger.events)
    used = ledger.apply_credit("acme", date(2026, 1, 9))
    assert [a.invoice for a in used] == ["B"] and len(ledger.events) == events
    with pytest.raises(PaymentError):
        ledger.reverse("P", date(2026, 1, 10))
    assert ledger.invoices["A"].status == "paid" and ledger.credit("acme") == D("30.00")


def test_credit_earns_no_discount():
    ledger = Ledger()
    ledger.receive("P", "acme", "100", DAY)
    ledger.add(Invoice("A", "acme", DAY, "2/10 NET 30", [Line("w", 1, "100")]))
    ledger.issue("A")
    ledger.apply_credit("acme", date(2026, 1, 8))
    assert ledger.invoices["A"].discount_taken == 0
    assert ledger.credit("acme") == 0
