"""Rules that only show when several steps follow each other."""
from datetime import date, timedelta
from decimal import Decimal as D

import pytest

from tally import Invoice, Ledger, Line, PaymentError, load, parse_terms, save, statement

DAY = date(2026, 1, 5)
DUE = date(2026, 2, 4)


def make(*specs, tax_rate=0, holidays=()):
    ledger = Ledger(holidays)
    for number, price, terms in specs:
        ledger.add(Invoice(number, "acme", DAY, terms, [Line("w", 1, price)], tax_rate=tax_rate))
        ledger.issue(number)
    return ledger


def late(days):
    return DUE + timedelta(days=days)


def test_discount_available_again_after_reversal():
    ledger = make(("A", "100", "2/10 NET 30"))
    ledger.receive("P1", "acme", "50", date(2026, 1, 6))
    ledger.reverse("P1", date(2026, 1, 7))
    ledger.receive("P2", "acme", "98", date(2026, 1, 8))
    assert ledger.invoices["A"].status == "paid"


def test_void_after_reversal():
    ledger = make(("A", "100", "NET 30"))
    ledger.receive("P1", "acme", "50", date(2026, 1, 6))
    ledger.reverse("P1", date(2026, 1, 7))
    ledger.void("A", date(2026, 1, 8))
    assert ledger.invoices["A"].status == "void"
    assert (ledger.events[-1].date, ledger.events[-1].amount) == (date(2026, 1, 8), D("-100.00"))


def test_reversal_does_not_recharge_fees():
    ledger = make(("A", "1000", "NET 30"))
    ledger.assess_late_fees(late(10))
    ledger.receive("P1", "acme", "100", late(11))
    ledger.reverse("P1", late(12))
    assert ledger.assess_late_fees(late(12)) == {}


def test_loaded_ledger_carries_on(tmp_path):
    ledger = make(("A", "1000", "NET 30"))
    ledger.assess_late_fees(late(10))
    ledger.receive("P1", "acme", "100", late(11))
    ledger.reverse("P1", late(12))
    ledger.receive("P2", "other", "40", late(12))
    save(ledger, tmp_path / "l.json", 0)
    back, _ = load(tmp_path / "l.json")
    assert back.assess_late_fees(late(12)) == {}
    assert back.receive("P2", "other", "40", late(13)).credit == D("40.00")
    assert back.credit("other") == D("40.00")
    with pytest.raises(PaymentError):
        back.reverse("P1", late(13))


def test_fee_after_part_payment():
    ledger = make(("A", "1000", "NET 30"))
    ledger.receive("P1", "acme", "400", late(1))
    assert ledger.assess_late_fees(late(10)) == {"A": D("9.00")}


def test_minimum_is_per_period():
    assert make(("A", "200", "NET 30")).assess_late_fees(late(40)) == {"A": D("10.00")}


def test_each_period_is_rounded():
    assert make(("A", "1000.33", "NET 30")).assess_late_fees(late(40)) == {"A": D("30.00")}


def test_cap_includes_tax_and_ignores_payments():
    ledger = make(("A", "1000", "NET 30"), tax_rate=10)
    ledger.assess_late_fees(late(400))
    assert ledger.invoices["A"].fees == D("110.00")
    ledger = make(("A", "1000", "NET 30"))
    ledger.receive("P1", "acme", "900", late(1))
    ledger.assess_late_fees(late(100))
    assert ledger.invoices["A"].fees == D("20.00")


@pytest.mark.parametrize("days, fee", [(31, "30.00"), (35, "30.00"), (36, "30.00")])
def test_periods_count_from_the_due_date(days, fee):
    assert make(("A", "1000", "NET 30")).assess_late_fees(late(days)) == {"A": D(fee)}


def test_credit_adds_up_and_part_use_blocks_reversal():
    ledger = Ledger()
    ledger.receive("P1", "acme", "30", DAY)
    ledger.receive("P2", "acme", "20", DAY)
    assert ledger.credit("acme") == D("50.00")
    ledger.add(Invoice("A", "acme", DAY, "NET 30", [Line("w", 1, "25")]))
    ledger.issue("A")
    ledger.apply_credit("acme", DAY)
    assert ledger.credit("acme") == D("25.00")
    with pytest.raises(PaymentError):
        ledger.reverse("P1", DAY)


def test_credit_pays_the_earliest_due_and_logs_nothing():
    ledger = Ledger()
    ledger.receive("P1", "acme", "100", DAY)
    for number, terms in (("LATER", "NET 60"), ("SOON", "NET 10")):
        ledger.add(Invoice(number, "acme", DAY, terms, [Line("w", 1, "100")]))
        ledger.issue(number)
    before = len(ledger.events)
    ledger.apply_credit("acme", DAY)
    assert ledger.invoices["SOON"].status == "paid" and ledger.invoices["LATER"].status == "open"
    assert len(ledger.events) == before


def test_discount_judged_per_invoice():
    specs = (("A", "100", "2/10 NET 30"), ("B", "100", "2/10 NET 30"))
    ledger = make(*specs)
    ledger.receive("P", "acme", "150", date(2026, 1, 8))
    assert ledger.invoices["A"].discount_taken == D("2.00")
    assert ledger.invoices["B"].discount_taken == 0 and ledger.invoices["B"].balance == D("48.00")
    ledger = make(*specs)
    ledger.receive("P", "acme", "196", date(2026, 1, 8))
    assert ledger.invoices["B"].status == "paid"


def test_reversal_event():
    ledger = make(("A", "100", "2/10 NET 30"))
    ledger.receive("P", "acme", "98", date(2026, 1, 8))
    ledger.reverse("P", date(2026, 1, 20))
    event = ledger.events[-1]
    assert (event.kind, event.date, event.amount) == ("reversal", date(2026, 1, 20), D("100.00"))
    assert statement(ledger, "acme", DAY, date(2026, 1, 31)).closing == D("100.00")


def test_eom_rolls_and_handles_short_months():
    assert parse_terms("EOM").due_date(date(2026, 1, 10)) == date(2026, 2, 2)
    assert parse_terms("EOM").due_date(date(2027, 12, 31)) == date(2028, 1, 31)
    for day in (29, 30, 31):
        assert parse_terms("EOM").due_date(date(2028, 1, day)) == date(2028, 2, 29)


def test_ledger_holidays_move_due_dates():
    assert make(("A", "1", "NET 30"), holidays=[DUE]).invoices["A"].due == date(2026, 2, 5)


def test_tax_after_line_discount():
    inv = Invoice("A", "acme", DAY, "EOM", [Line("w", 1, "100.00", 50)], tax_rate=10)
    assert inv.tax == D("5.00")


def test_repeat_payment_logs_once():
    ledger = make(("A", "100", "NET 30"))
    for _ in range(2):
        ledger.receive("P", "acme", "10", DAY)
    assert statement(ledger, "acme", DAY, DAY).closing == D("90.00")
