import json
import os
from datetime import date
from decimal import Decimal

import pytest

import tally
from tally import (
    ConflictError, ImportFormatError, Invoice, InvoiceError, Ledger, Line,
    PaymentError, StoreError, TermsError, aging, load, money, parse_deposits,
    parse_terms, save, split, statement,
)

D = Decimal


def inv(number="INV-1", customer="acme", terms="NET 30", price="100.00",
        day=date(2026, 1, 5), **kw):
    return Invoice(number, customer, day, terms, [Line("work", 1, price)], **kw)


def issued(*invoices, holidays=()):
    ledger = Ledger(holidays)
    for i in invoices:
        ledger.add(i)
        ledger.issue(i.number)
    return ledger


# money ---------------------------------------------------------------

@pytest.mark.parametrize("bad", [True, 1.5, None, [1]])
def test_money_bad_types(bad):
    with pytest.raises(TypeError):
        money(bad)


@pytest.mark.parametrize("bad", ["abc", "Infinity", "NaN", ""])
def test_money_bad_values(bad):
    with pytest.raises(ValueError):
        money(bad)


@pytest.mark.xfail(strict=True, reason="SPEC R1.2 says half to even; code rounds half up")
def test_money_half_even_spec():
    assert money("2.665") == D("2.66")


def test_split_leftover_and_ties():
    assert split("10.00", [1, 1, 1]) == [D("3.34"), D("3.33"), D("3.33")]
    assert sum(split("0.05", [1, 1, 1])) == D("0.05")


def test_split_negative_and_zero_weight():
    assert split("-10.00", [1, 1, 1]) == [D("-3.34"), D("-3.33"), D("-3.33")]
    assert split("5.00", [0, 1]) == [D("0.00"), D("5.00")]


@pytest.mark.parametrize("weights", [[-1, 2], [0, 0], []])
def test_split_bad_weights(weights):
    with pytest.raises(ValueError):
        split("1.00", weights)


# terms ---------------------------------------------------------------

def test_eom_and_cutoff():
    eom = parse_terms("eom")
    assert eom.due_date(date(2026, 3, 10)) == date(2026, 3, 31)
    assert eom.due_date(date(2026, 3, 25)) == date(2026, 3, 31)
    assert eom.due_date(date(2026, 3, 26)) == date(2026, 4, 30)
    assert eom.due_date(date(2026, 12, 28)) == date(2027, 2, 1)  # Jan 31 is a Sunday


def test_due_date_rolls_past_weekend_and_holiday():
    t = parse_terms(" net 30 ")
    assert t.due_date(date(2026, 1, 8)) == date(2026, 2, 9)  # Sat Feb 7 -> Mon
    assert t.due_date(date(2026, 1, 8), {date(2026, 2, 9)}) == date(2026, 2, 10)


def test_discount_terms():
    t = parse_terms("2/10 NET 30")
    assert (t.net_days, t.discount_pct, t.discount_days) == (30, D(2), 10)
    assert t.discount_deadline(date(2026, 1, 5)) == date(2026, 1, 15)
    assert parse_terms("NET 30").discount_deadline(date(2026, 1, 5)) is None


@pytest.mark.xfail(strict=True, reason="SPEC R2.4 says discount deadline never moves; code rolls it")
def test_discount_deadline_does_not_roll():
    assert parse_terms("2/10 NET 30").discount_deadline(date(2026, 1, 8)) == date(2026, 1, 18)


@pytest.mark.parametrize("text", ["", "SOON", "100/10 NET 30", "2/40 NET 30", "NET"])
def test_bad_terms(text):
    with pytest.raises(TermsError):
        parse_terms(text)


# invoices ------------------------------------------------------------

def test_line_validation_and_net():
    with pytest.raises(InvoiceError):
        Line("x", 0, "1")
    with pytest.raises(InvoiceError):
        Line("x", 1, "1", discount_pct=101)
    with pytest.raises(InvoiceError):
        Line("x", 1, "1", discount_pct=-1)
    assert Line("x", 3, "10.00", 10).net == D("27.00")
    assert Line("x", 1, "-5.00").net == D("-5.00")


def test_tax_exempt_and_nontaxable():
    i = Invoice("A", "c", date(2026, 1, 5), "NET 30",
                [Line("a", 1, "10.00"), Line("b", 1, "10.00", taxable=False)], tax_rate=10)
    assert i.tax == D("1.00") and i.total == D("21.00")
    i.tax_exempt = True
    assert i.tax == D("0.00")


@pytest.mark.xfail(strict=True, reason="SPEC R3.2 says tax is rounded once on the sum; code rounds per line")
def test_tax_rounded_once():
    i = Invoice("A", "c", date(2026, 1, 5), "NET 30",
                [Line("a", 1, "0.05"), Line("b", 1, "0.05")], tax_rate=10)
    assert i.tax == D("0.01")


def test_issue_and_void_errors():
    empty = Invoice("A", "c", date(2026, 1, 5), "NET 30")
    with pytest.raises(InvoiceError):
        empty.issue()
    with pytest.raises(InvoiceError):
        inv(price="-1.00").issue()
    ok = inv()
    assert ok.status == "draft"
    with pytest.raises(InvoiceError):
        ok.void()
    ok.issue()
    with pytest.raises(InvoiceError):
        ok.issue()
    ok.void()
    assert ok.status == "void"
    with pytest.raises(InvoiceError):
        ok.issue()
    with pytest.raises(InvoiceError):
        ok.void()


def test_void_with_payment_rejected_and_event():
    ledger = issued(inv())
    ledger.receive("P", "acme", "10.00", date(2026, 1, 6))
    with pytest.raises(InvoiceError):
        ledger.void("INV-1", date(2026, 1, 7))
    ledger2 = issued(inv())
    ledger2.void("INV-1", date(2026, 1, 7))
    assert ledger2.events[-1].kind == "void" and ledger2.events[-1].amount == D("-100.00")


def test_void_with_fees_paid_rejected():
    i = inv(price="1000.00")
    i.issue()
    i.fees_paid = D("5.00")
    with pytest.raises(InvoiceError):
        i.void()


def test_early_discount_conditions():
    i = inv(terms="2/10 NET 30")
    assert i.early_discount(date(2026, 1, 15)) == D("2.00")
    assert i.early_discount(date(2026, 1, 16)) == D("0.00")
    i.paid = D("1.00")
    assert i.early_discount(date(2026, 1, 10)) == D("0.00")


# ledger --------------------------------------------------------------

def test_ledger_errors():
    ledger = issued(inv())
    with pytest.raises(InvoiceError):
        ledger.add(inv())
    with pytest.raises(InvoiceError):
        ledger.issue("NOPE")
    with pytest.raises(InvoiceError):
        ledger.dispute("NOPE")
    ledger.add(inv("INV-2"))
    with pytest.raises(InvoiceError):
        ledger.dispute("INV-2")  # draft


def test_dispute_blocks_payment_and_aging():
    ledger = issued(inv())
    ledger.dispute("INV-1")
    ledger.receive("P", "acme", "50.00", date(2026, 1, 10))
    assert ledger.credit("acme") == D("50.00")
    rep = aging(ledger, "acme", date(2026, 1, 10))
    assert rep["disputed"] == D("100.00") and rep["current"] == D("-50.00")
    ledger.resolve("INV-1")
    assert not ledger.invoices["INV-1"].disputed


@pytest.mark.xfail(strict=True, reason="SPEC R4.1 says INV-2 before INV-10; _payable sorts by plain string, _number_key is unused")
def test_payment_order_numeric_sort():
    ledger = issued(inv("INV-10"), inv("INV-2"))
    p = ledger.receive("P", "acme", "150.00", date(2026, 1, 10))
    assert [a.invoice for a in p.allocations] == ["INV-2", "INV-10"]
    assert ledger.invoices["INV-2"].status == "paid"
    assert ledger.invoices["INV-10"].paid == D("50.00")


def test_earlier_due_first_and_other_customer_ignored():
    ledger = issued(inv("B", terms="NET 60"), inv("A", terms="NET 30"), inv("C", customer="zed"))
    p = ledger.receive("P", "acme", "10.00", date(2026, 1, 10))
    assert [a.invoice for a in p.allocations] == ["A"]


def test_fees_paid_before_principal():
    ledger = issued(inv(price="1000.00"))
    ledger.assess_late_fees(date(2026, 2, 20))
    p = ledger.receive("P", "acme", "20.00", date(2026, 2, 21))
    assert p.allocations[0].fees == D("15.00")
    assert p.allocations[0].principal == D("5.00")


def test_discount_granted_and_logged():
    ledger = issued(inv(terms="2/10 NET 30"))
    ledger.receive("P", "acme", "98.00", date(2026, 1, 10))
    assert ledger.invoices["INV-1"].status == "paid"
    assert [e.kind for e in ledger.events] == ["invoice", "payment", "discount"]


@pytest.mark.xfail(strict=True, reason="SPEC R4.8 says reverse undoes the discount; code leaves discount_taken set")
def test_discount_granted_logged_and_reversed():
    ledger = issued(inv(terms="2/10 NET 30"))
    p = ledger.receive("P", "acme", "98.00", date(2026, 1, 10))
    assert ledger.invoices["INV-1"].status == "paid"
    assert [e.kind for e in ledger.events] == ["invoice", "payment", "discount"]
    ledger.reverse("P", date(2026, 1, 12))
    assert ledger.events[-1].kind == "reversal" and ledger.events[-1].amount == D("100.00")
    assert ledger.invoices["INV-1"].balance == D("100.00")
    assert p.reversed


def test_discount_denied_when_underpaid():
    ledger = issued(inv(terms="2/10 NET 30"))
    p = ledger.receive("P", "acme", "50.00", date(2026, 1, 10))
    assert p.allocations[0].discount == D("0.00")


def test_receive_idempotent_and_conflicts():
    ledger = issued(inv())
    p = ledger.receive("P", "acme", "10.00", date(2026, 1, 10))
    assert ledger.receive("P", "acme", "10.00", date(2026, 1, 11)) is p
    assert len(ledger.events) == 2
    with pytest.raises(PaymentError):
        ledger.receive("P", "acme", "11.00", date(2026, 1, 10))
    with pytest.raises(PaymentError):
        ledger.receive("P", "other", "10.00", date(2026, 1, 10))
    ledger.reverse("P", date(2026, 1, 12))
    with pytest.raises(PaymentError):
        ledger.receive("P", "acme", "10.00", date(2026, 1, 13))


def test_reverse_errors_and_credit_used():
    ledger = issued(inv())
    with pytest.raises(PaymentError):
        ledger.reverse("NOPE", date(2026, 1, 10))
    ledger.receive("P", "acme", "130.00", date(2026, 1, 10))
    assert ledger.credit("acme") == D("30.00")
    ledger.add(inv("INV-2"))
    ledger.issue("INV-2")
    ledger.apply_credit("acme", date(2026, 1, 11))
    assert ledger.invoices["INV-2"].paid == D("30.00")
    with pytest.raises(PaymentError):
        ledger.reverse("P", date(2026, 1, 12))
    assert not ledger.payments["P"].reversed


def test_reverse_restores_credit_and_invoices():
    ledger = issued(inv())
    ledger.receive("P", "acme", "130.00", date(2026, 1, 10))
    ledger.reverse("P", date(2026, 1, 12))
    assert ledger.credit("acme") == 0
    assert ledger.invoices["INV-1"].balance == D("100.00")
    with pytest.raises(PaymentError):
        ledger.reverse("P", date(2026, 1, 13))


def test_payment_must_be_positive_and_apply_credit_no_discount():
    ledger = issued(inv(terms="2/10 NET 30"))
    ledger.credits["acme"] = D("98.00")
    n = len(ledger.events)
    allocations = ledger.apply_credit("acme", date(2026, 1, 8))
    assert allocations[0].discount == D("0.00")
    assert len(ledger.events) == n
    assert ledger.invoices["INV-1"].balance == D("2.00")


def test_late_fee_periods_cap_and_repeat():
    ledger = issued(inv(price="100.00"))
    assert ledger.assess_late_fees(date(2026, 2, 4)) == {}
    assert ledger.assess_late_fees(date(2026, 2, 12)) == {"INV-1": D("5.00")}
    assert ledger.assess_late_fees(date(2026, 2, 12)) == {}
    assert ledger.assess_late_fees(date(2026, 3, 20)) == {"INV-1": D("5.00")}
    assert ledger.invoices["INV-1"].fee_periods == 2
    assert ledger.assess_late_fees(date(2026, 6, 1)) == {}  # cap of 10.00 reached
    assert ledger.invoices["INV-1"].fees == D("10.00")


@pytest.mark.xfail(strict=True, reason="SPEC R5.1 says no fee at exactly 5 days late; code charges on day 5")
def test_no_fee_on_fifth_day():
    ledger = issued(inv())
    assert ledger.assess_late_fees(date(2026, 2, 9)) == {}


def test_late_fee_disputed_stays_waived():
    ledger = issued(inv(price="1000.00"))
    ledger.dispute("INV-1")
    assert ledger.assess_late_fees(date(2026, 2, 20)) == {}
    ledger.resolve("INV-1")
    assert ledger.assess_late_fees(date(2026, 2, 20)) == {}


def test_late_fee_skips_nonopen():
    ledger = issued(inv())
    ledger.add(inv("DRAFT"))
    ledger.receive("P", "acme", "100.00", date(2026, 1, 6))
    assert ledger.assess_late_fees(date(2026, 6, 1)) == {}


def test_late_fee_skips_when_only_fees_owed():
    ledger = issued(inv(price="1000.00"))
    i = ledger.invoices["INV-1"]
    i.paid = i.total
    i.fees = D("5.00")
    assert ledger.assess_late_fees(date(2026, 6, 1)) == {}


# reports -------------------------------------------------------------

def test_aging_buckets_and_credit():
    day = date(2026, 1, 1)
    ledger = issued(
        inv("A", day=day, terms="NET 10"),   # due Jan 11 -> Mar 10: 58 days late? see below
        inv("B", day=day, terms="NET 40"),
        inv("C", day=day, terms="NET 70"),
        inv("D", day=day, terms="NET 100"),
        inv("E", day=day, terms="NET 120"),
        inv("F", customer="zed"),
    )
    ledger.add(inv("G"))  # draft, ignored
    on = date(2026, 3, 1)
    rep = aging(ledger, "acme", on)
    expected = {}
    for n in "ABCDE":
        late = (on - ledger.invoices[n].due).days
        expected[n] = late
    assert rep["91+"] + rep["61-90"] + rep["31-60"] + rep["1-30"] + rep["current"] == D("500.00")
    assert all(v >= 0 for v in rep.values())
    assert rep["disputed"] == 0
    # far in the future everything is 91+
    assert aging(ledger, "acme", date(2027, 1, 1))["91+"] == D("500.00")
    ledger.credits["acme"] = D("150.00")
    after = aging(ledger, "acme", date(2027, 1, 1))
    assert after["91+"] == D("350.00")
    ledger.credits["acme"] = D("600.00")
    assert aging(ledger, "acme", date(2027, 1, 1))["current"] == D("-100.00")


def test_aging_each_bucket():
    day = date(2026, 1, 1)
    nets = {"current": 100, "1-30": 70, "31-60": 40, "61-90": 10, "91+": 0}
    ledger = Ledger()
    for k, (name, n) in enumerate(nets.items()):
        i = inv(f"I{k}", day=day, terms=f"NET {n}")
        ledger.add(i)
        ledger.issue(i.number)
    on = date(2026, 4, 11)  # 100 days after Jan 1
    rep = aging(ledger, "acme", on)
    for name in nets:
        assert rep[name] == D("100.00"), name


def test_statement():
    ledger = issued(inv())
    ledger.receive("P", "acme", "40.00", date(2026, 1, 10))
    s = statement(ledger, "acme", date(2026, 1, 6), date(2026, 1, 31))
    assert s.opening == D("100.00") and s.closing == D("60.00")
    assert [x.kind for x in s.lines] == ["payment"] and s.lines[0].balance == D("60.00")
    s = statement(ledger, "acme", date(2026, 3, 1), date(2026, 3, 31))
    assert s.lines == [] and s.closing == s.opening == D("60.00")
    assert statement(ledger, "nobody", date(2026, 1, 1), date(2026, 12, 31)).closing == 0


def test_statement_same_day_order():
    ledger = issued(inv(terms="2/10 NET 30"))
    ledger.receive("P", "acme", "98.00", date(2026, 1, 5))
    s = statement(ledger, "acme", date(2026, 1, 5), date(2026, 1, 5))
    assert [x.kind for x in s.lines] == ["invoice", "payment", "discount"]


# importer ------------------------------------------------------------

HEADER = "Date,Reference,Customer,Amount\n"


def test_import_header_errors():
    with pytest.raises(ImportFormatError):
        parse_deposits("")
    with pytest.raises(ImportFormatError):
        parse_deposits("date,customer,amount\n")


def test_import_accepts_variants():
    text = chr(0xFEFF) + 'AMOUNT,customer,extra,reference,DATE\n"$1,234.50",Acme,x,R1,2026-01-05\n'
    r = parse_deposits(text)
    assert r.rejected == []
    d = r.accepted[0]
    assert d.amount == D("1234.50") and d.date == date(2026, 1, 5) and d.reference == "R1"
    r = parse_deposits(HEADER + "01/05/2026,R2,Acme,5\n")
    assert r.accepted[0].amount == D("5.00")


def test_import_rejections():
    rows = [
        "2026-01-05,,Acme,5",
        "2026-01-05,R,,5",
        "bad,R,Acme,5",
        "2026-01-05,R,Acme,-5",
        "2026-01-05,R,Acme,0",
        '2026-01-05,R,Acme,"1,23"',
        "2026-01-05,R,Acme,5",
        "2026-01-05,r,Acme,5",
    ]
    r = parse_deposits(HEADER + "\n".join(rows) + "\n")
    assert [x.reason for x in r.rejected] == [
        "missing_reference", "missing_customer", "bad_date", "bad_amount",
        "bad_amount", "bad_amount", "duplicate"]
    assert [x.line for x in r.rejected] == [2, 3, 4, 5, 6, 7, 9]
    assert len(r.accepted) == 1


def test_import_rejected_does_not_block_and_short_row():
    r = parse_deposits(HEADER + "2026-01-05,R,Acme,bad\n2026-01-05,R,Acme,5\n2026-01-05,S\n")
    assert [d.reference for d in r.accepted] == ["R"]
    assert [x.reason for x in r.rejected] == ["bad_amount", "missing_customer"]


@pytest.mark.xfail(strict=True, reason="SPEC R8.2 counts blank lines in line numbers; code drops them first")
def test_import_line_numbers_count_blank_lines():
    r = parse_deposits(HEADER + "\n,R,Acme,5\n")
    assert r.rejected[0].line == 3


def test_import_blank_lines_ignored():
    r = parse_deposits(HEADER + "\n  , ,\n2026-01-05,R,Acme,5\n")
    assert len(r.accepted) == 1 and r.rejected == []


# store ---------------------------------------------------------------

def full_ledger():
    ledger = issued(inv(terms="2/10 NET 30", price="1000.00"), holidays=[date(2026, 2, 9)])
    ledger.receive("P", "acme", "200.00", date(2026, 1, 10))
    ledger.assess_late_fees(date(2026, 3, 1))
    ledger.credits["acme"] = D("1.25")
    return ledger


def test_roundtrip_and_versions(tmp_path):
    path = tmp_path / "l.json"
    ledger = full_ledger()
    assert save(ledger, path, 0) == 1
    assert save(ledger, path, 1) == 2
    back, version = load(path)
    assert version == 2
    assert back.holidays == ledger.holidays
    assert back.invoices == ledger.invoices
    assert back.payments == ledger.payments
    assert back.credits == ledger.credits
    assert back.events == ledger.events
    assert os.listdir(tmp_path) == ["l.json"]


def test_conflicts(tmp_path):
    path = tmp_path / "l.json"
    with pytest.raises(ConflictError):
        save(Ledger(), path, 3)
    assert not path.exists()
    save(Ledger(), path, 0)
    before = path.read_text()
    with pytest.raises(ConflictError):
        save(Ledger(), path, 0)
    assert path.read_text() == before


@pytest.mark.parametrize("content", ["not json", "[1]", json.dumps({"schema": 2})])
def test_bad_files(tmp_path, content):
    path = tmp_path / "l.json"
    path.write_text(content)
    with pytest.raises(StoreError):
        load(path)
    with pytest.raises(StoreError):
        save(Ledger(), path, 0)


def test_failed_save_leaves_file_and_no_temp(tmp_path):
    path = tmp_path / "l.json"
    save(Ledger(), path, 0)
    before = path.read_text()
    ledger = Ledger()
    ledger.credits["x"] = object()
    with pytest.raises(TypeError):
        save(ledger, path, 1)
    assert path.read_text() == before
    assert os.listdir(tmp_path) == ["l.json"]


def test_package_exports():
    for name in tally.__all__:
        assert hasattr(tally, name)
