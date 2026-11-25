from datetime import date

import pytest

from helpers import D, JAN5, events, invoice, late, ledger_with
from tally import Line, Ledger, PaymentError

PAY = date(2026, 1, 10)


def balances(ledger):
    return {n: i.balance for n, i in ledger.invoices.items()}


def snapshot(ledger):
    return (len(ledger.events), ledger.credit("acme"), balances(ledger),
            {k: p.reversed for k, p in ledger.payments.items()})


def discount_invoice(number="INV-1", price="1000.00", day=JAN5, **kwargs):
    return invoice(number, terms="2/10 NET 30", price=price, day=day, **kwargs)


# R4.1 ---------------------------------------------------------------------

def test_payment_goes_to_the_earliest_due_date_first():
    # INV-1 is dated later so it falls due later, even though its number sorts first
    ledger = ledger_with(invoice("INV-1", day=date(2026, 1, 20)), invoice("INV-2", day=JAN5))
    ledger.receive("P1", "acme", "100.00", PAY)
    assert balances(ledger) == {"INV-1": D("100.00"), "INV-2": D("0.00")}


def test_payment_spills_to_the_next_invoice_and_then_to_credit():
    ledger = ledger_with(invoice("INV-1", day=JAN5), invoice("INV-2", day=date(2026, 1, 6)))
    payment = ledger.receive("P1", "acme", "150.00", PAY)
    assert balances(ledger) == {"INV-1": D("0"), "INV-2": D("50.00")}
    assert ledger.credit("acme") == 0
    assert [a.invoice for a in payment.allocations] == ["INV-1", "INV-2"]
    assert [a.principal for a in payment.allocations] == [D("100.00"), D("50.00")]
    ledger.receive("P2", "acme", "80.00", PAY)
    assert balances(ledger) == {"INV-1": D("0"), "INV-2": D("0")}
    assert ledger.credit("acme") == D("30.00")


def test_equal_due_dates_go_in_invoice_number_order():
    ledger = ledger_with(invoice("INV-2"), invoice("INV-1"))
    ledger.receive("P1", "acme", "100.00", PAY)
    assert balances(ledger) == {"INV-2": D("100.00"), "INV-1": D("0.00")}


@pytest.mark.xfail(strict=True, reason="invoice numbers are compared as text, so INV-10 comes before INV-2")
def test_digit_runs_in_invoice_numbers_compare_as_numbers():
    ledger = ledger_with(invoice("INV-10"), invoice("INV-2"))
    ledger.receive("P1", "acme", "100.00", PAY)
    assert balances(ledger) == {"INV-10": D("100.00"), "INV-2": D("0.00")}


@pytest.mark.xfail(strict=True, reason="invoice numbers are compared as text, so INV-100 comes before INV-9")
def test_digit_runs_compare_as_numbers_with_other_widths():
    ledger = ledger_with(invoice("A-100"), invoice("A-9"), invoice("A-20"))
    ledger.receive("P1", "acme", "200.00", PAY)
    assert balances(ledger) == {"A-100": D("100.00"), "A-9": D("0.00"), "A-20": D("0.00")}


def test_payments_only_touch_the_paying_customers_invoices():
    ledger = ledger_with(invoice("INV-1", customer="other"), invoice("INV-2", customer="acme"))
    ledger.receive("P1", "acme", "100.00", PAY)
    assert balances(ledger) == {"INV-1": D("100.00"), "INV-2": D("0.00")}
    ledger.receive("P2", "acme", "10.00", PAY)
    assert ledger.invoices["INV-1"].balance == D("100.00")
    assert ledger.credit("acme") == D("10.00")
    assert ledger.credit("other") == 0


# R4.2 ---------------------------------------------------------------------

def test_late_fees_are_paid_before_principal():
    ledger = ledger_with(invoice(price="1000.00"))
    ledger.assess_late_fees(late(16))                      # fee 15.00
    payment = ledger.receive("P1", "acme", "20.00", late(17))
    [allocation] = payment.allocations
    assert (allocation.fees, allocation.principal) == (D("15.00"), D("5.00"))
    assert ledger.invoices["INV-1"].balance == D("995.00")


def test_payment_smaller_than_the_fees_pays_only_fees():
    ledger = ledger_with(invoice(price="1000.00"))
    ledger.assess_late_fees(late(16))
    payment = ledger.receive("P1", "acme", "10.00", late(17))
    [allocation] = payment.allocations
    assert (allocation.fees, allocation.principal) == (D("10.00"), D("0.00"))
    assert ledger.invoices["INV-1"].balance == D("1005.00")


# R4.3 ---------------------------------------------------------------------

def test_discount_is_a_percentage_of_net_before_tax():
    ledger = ledger_with(discount_invoice(tax_rate=10))      # net 1000, total 1100
    ledger.receive("P1", "acme", "1080.00", date(2026, 1, 15))   # last day of the window
    inv = ledger.invoices["INV-1"]
    assert inv.status == "paid"
    assert inv.balance == 0
    [discount] = events(ledger, "discount")
    assert discount.amount == D("-20.00")
    assert (discount.ref, discount.date) == ("INV-1", date(2026, 1, 15))
    assert ledger.credit("acme") == 0


def test_discount_is_rounded_to_the_cent():
    ledger = ledger_with(invoice(terms="3/10 NET 30", price="123.45"))   # 3.7035
    ledger.receive("P1", "acme", "119.75", PAY)
    assert ledger.invoices["INV-1"].balance == 0
    assert events(ledger, "discount")[0].amount == D("-3.70")


def test_payment_before_the_deadline_gets_the_discount():
    ledger = ledger_with(discount_invoice())
    ledger.receive("P1", "acme", "980.00", date(2026, 1, 5))
    assert ledger.invoices["INV-1"].status == "paid"


def test_payment_after_the_deadline_gets_no_discount():
    ledger = ledger_with(discount_invoice())
    ledger.receive("P1", "acme", "980.00", date(2026, 1, 16))
    assert ledger.invoices["INV-1"].balance == D("20.00")
    assert events(ledger, "discount") == []


def test_payment_one_cent_short_of_the_discounted_balance_gets_no_discount_at_all():
    ledger = ledger_with(discount_invoice(tax_rate=10))
    ledger.receive("P1", "acme", "1079.99", date(2026, 1, 15))
    assert ledger.invoices["INV-1"].balance == D("20.01")
    assert events(ledger, "discount") == []


def test_a_small_early_payment_gets_no_discount():
    ledger = ledger_with(discount_invoice())
    ledger.receive("P1", "acme", "500.00", date(2026, 1, 10))
    assert ledger.invoices["INV-1"].balance == D("500.00")


def test_no_discount_when_the_invoice_already_has_a_payment():
    ledger = ledger_with(discount_invoice())
    ledger.receive("P1", "acme", "500.00", date(2026, 1, 8))
    ledger.receive("P2", "acme", "480.00", date(2026, 1, 10))
    assert ledger.invoices["INV-1"].balance == D("20.00")
    assert events(ledger, "discount") == []
    ledger.receive("P3", "acme", "20.00", date(2026, 1, 11))
    assert ledger.invoices["INV-1"].status == "paid"


def test_discount_comes_back_after_the_earlier_payment_is_reversed():
    ledger = ledger_with(discount_invoice())
    ledger.receive("P1", "acme", "500.00", date(2026, 1, 8))
    ledger.reverse("P1", date(2026, 1, 9))
    ledger.receive("P2", "acme", "980.00", date(2026, 1, 10))
    assert ledger.invoices["INV-1"].balance == 0


def test_discount_needs_the_money_that_reaches_the_invoice_not_the_whole_payment():
    first = invoice("INV-1", price="100.00")                           # due Feb 4
    second = discount_invoice("INV-2", day=date(2026, 1, 8))            # due Feb 7
    ledger = ledger_with(first, second)
    ledger.receive("P1", "acme", "1080.00", PAY)       # 100 to INV-1, 980 to INV-2
    assert balances(ledger) == {"INV-1": D("0"), "INV-2": D("0")}
    assert events(ledger, "discount")[0].ref == "INV-2"

    ledger = ledger_with(invoice("INV-1", price="100.00"), discount_invoice("INV-2", day=date(2026, 1, 8)))
    ledger.receive("P1", "acme", "1079.00", PAY)       # only 979 reaches INV-2
    assert balances(ledger) == {"INV-1": D("0"), "INV-2": D("21.00")}
    assert events(ledger, "discount") == []


@pytest.mark.parametrize("amount, left", [("995.00", "0.00"), ("994.99", "20.01")])
def test_discount_needs_the_money_to_cover_late_fees_plus_the_discounted_principal(amount, left):
    ledger = ledger_with(discount_invoice())
    ledger.assess_late_fees(late(16))        # a 15.00 fee, recorded before the payment's date
    ledger.receive("P1", "acme", amount, date(2026, 1, 12))
    assert ledger.invoices["INV-1"].balance == D(left)
    assert bool(events(ledger, "discount")) == (left == "0.00")


def test_overpaying_an_invoice_with_a_discount_leaves_credit():
    ledger = ledger_with(discount_invoice())
    ledger.receive("P1", "acme", "1100.00", PAY)
    assert ledger.invoices["INV-1"].status == "paid"
    assert ledger.credit("acme") == D("120.00")


def test_payment_allocation_reports_the_discount():
    ledger = ledger_with(discount_invoice())
    payment = ledger.receive("P1", "acme", "980.00", PAY)
    [allocation] = payment.allocations
    assert (allocation.invoice, allocation.principal, allocation.fees) == ("INV-1", D("980.00"), D("0.00"))
    assert allocation.discount == D("20.00")


@pytest.mark.xfail(strict=True, reason="discount deadline is moved past weekends")
def test_discount_deadline_does_not_move_for_a_weekend():
    # 2/5 NET 30 from Monday Jan 5: the window ends Saturday Jan 10.
    ledger = ledger_with(invoice(terms="2/5 NET 30", price="1000.00"))
    ledger.receive("P1", "acme", "980.00", date(2026, 1, 12))
    assert ledger.invoices["INV-1"].balance == D("20.00")
    assert events(ledger, "discount") == []


@pytest.mark.xfail(strict=True, reason="discount deadline is moved past holidays")
def test_discount_deadline_does_not_move_for_a_holiday():
    ledger = ledger_with(discount_invoice(), holidays=[date(2026, 1, 15)])
    ledger.receive("P1", "acme", "980.00", date(2026, 1, 16))
    assert ledger.invoices["INV-1"].balance == D("20.00")
    assert events(ledger, "discount") == []


def test_discount_is_still_given_on_the_weekend_deadline_day_itself():
    ledger = ledger_with(invoice(terms="2/5 NET 30", price="1000.00"))
    ledger.receive("P1", "acme", "980.00", date(2026, 1, 10))
    assert ledger.invoices["INV-1"].balance == 0


# R4.4 ---------------------------------------------------------------------

def test_leftover_money_becomes_credit():
    ledger = ledger_with(invoice())
    payment = ledger.receive("P1", "acme", "250.00", PAY)
    assert payment.credit == D("150.00")
    assert ledger.credit("acme") == D("150.00")


def test_payment_with_nothing_owed_is_all_credit_and_credits_add_up():
    ledger = Ledger()
    ledger.receive("P1", "acme", "40.00", PAY)
    ledger.receive("P2", "acme", "2.50", PAY)
    assert ledger.credit("acme") == D("42.50")
    assert ledger.credit("nobody") == 0


def test_amounts_are_rounded_to_cents_and_floats_are_refused():
    ledger = Ledger()
    payment = ledger.receive("P1", "acme", "10.004", PAY)
    assert payment.amount == D("10.00")
    with pytest.raises(TypeError):
        ledger.receive("P2", "acme", 10.5, PAY)


# R4.5 / R4.6 --------------------------------------------------------------

def test_repeating_a_payment_changes_nothing_and_returns_the_original():
    ledger = ledger_with(invoice())
    first = ledger.receive("P1", "acme", "60.00", PAY)
    before = snapshot(ledger)
    again = ledger.receive("P1", "acme", "60.00", date(2026, 1, 20))
    assert again == first
    assert snapshot(ledger) == before
    assert len(ledger.payments) == 1


def test_payment_id_reused_with_another_amount_or_customer_raises():
    ledger = ledger_with(invoice())
    ledger.receive("P1", "acme", "60.00", PAY)
    before = snapshot(ledger)
    with pytest.raises(PaymentError):
        ledger.receive("P1", "acme", "61.00", PAY)
    with pytest.raises(PaymentError):
        ledger.receive("P1", "other", "60.00", PAY)
    assert snapshot(ledger) == before


@pytest.mark.parametrize("amount", ["0", "0.00", "-5.00", "0.004", -1])
def test_payment_must_be_more_than_zero(amount):
    ledger = ledger_with(invoice())
    with pytest.raises(PaymentError):
        ledger.receive("P1", "acme", amount, PAY)
    assert ledger.payments == {}
    assert len(ledger.events) == 1


# R4.7 ---------------------------------------------------------------------

def test_draft_invoice_receives_nothing():
    ledger = Ledger()
    ledger.add(invoice())
    ledger.receive("P1", "acme", "100.00", PAY)
    assert ledger.invoices["INV-1"].status == "draft"
    assert ledger.credit("acme") == D("100.00")


def test_void_invoice_receives_nothing():
    ledger = ledger_with(invoice())
    ledger.void("INV-1", date(2026, 1, 6))
    ledger.receive("P1", "acme", "100.00", PAY)
    assert ledger.invoices["INV-1"].status == "void"
    assert ledger.credit("acme") == D("100.00")


def test_paid_invoice_receives_nothing_more():
    ledger = ledger_with(invoice())
    ledger.receive("P1", "acme", "100.00", PAY)
    ledger.receive("P2", "acme", "30.00", PAY)
    assert ledger.invoices["INV-1"].balance == 0
    assert ledger.credit("acme") == D("30.00")


def test_disputed_invoice_receives_nothing_until_resolved():
    ledger = ledger_with(invoice("INV-1"), invoice("INV-2", day=date(2026, 1, 6)))
    ledger.dispute("INV-1")
    ledger.receive("P1", "acme", "100.00", PAY)
    assert balances(ledger) == {"INV-1": D("100.00"), "INV-2": D("0.00")}
    ledger.receive("P2", "acme", "30.00", PAY)
    assert ledger.credit("acme") == D("30.00")
    assert ledger.invoices["INV-1"].balance == D("100.00")
    ledger.resolve("INV-1")
    ledger.receive("P3", "acme", "100.00", PAY)
    assert ledger.invoices["INV-1"].balance == 0


# R4.8 ---------------------------------------------------------------------

def test_reverse_restores_principal_and_logs_one_event():
    ledger = ledger_with(invoice())
    ledger.receive("P1", "acme", "60.00", PAY)
    ledger.reverse("P1", date(2026, 1, 12))
    assert ledger.invoices["INV-1"].balance == D("100.00")
    assert ledger.invoices["INV-1"].status == "open"
    assert ledger.payments["P1"].reversed is True
    [reversal] = events(ledger, "reversal")
    assert reversal.amount == D("60.00")
    assert (reversal.ref, reversal.customer, reversal.date) == ("P1", "acme", date(2026, 1, 12))


def test_reverse_restores_late_fees_that_were_paid():
    ledger = ledger_with(invoice(price="1000.00"))
    ledger.assess_late_fees(late(16))
    ledger.receive("P1", "acme", "20.00", late(17))
    ledger.reverse("P1", late(18))
    inv = ledger.invoices["INV-1"]
    assert inv.balance == D("1015.00")
    assert events(ledger, "reversal")[0].amount == D("20.00")


@pytest.mark.xfail(strict=True, reason="reverse does not take back the discount the payment earned")
def test_reverse_gives_back_the_discount():
    ledger = ledger_with(discount_invoice(tax_rate=10))
    ledger.receive("P1", "acme", "1080.00", PAY)
    ledger.reverse("P1", date(2026, 1, 11))
    inv = ledger.invoices["INV-1"]
    assert inv.balance == D("1100.00")
    assert inv.status == "open"
    # with no payment left on it, the invoice can earn its discount again
    ledger.receive("P2", "acme", "1080.00", date(2026, 1, 12))
    assert inv.balance == 0


def test_reverse_event_includes_the_discount():
    ledger = ledger_with(discount_invoice(tax_rate=10))
    ledger.receive("P1", "acme", "1080.00", PAY)
    ledger.reverse("P1", date(2026, 1, 11))
    [reversal] = events(ledger, "reversal")
    assert reversal.amount == D("1100.00")
    assert sum(e.amount for e in ledger.events) == D("1100.00")


def test_reverse_removes_the_credit_it_left():
    ledger = ledger_with(invoice())
    ledger.receive("P1", "acme", "250.00", PAY)
    ledger.reverse("P1", date(2026, 1, 11))
    assert ledger.credit("acme") == 0
    assert ledger.invoices["INV-1"].balance == D("100.00")
    assert events(ledger, "reversal")[0].amount == D("250.00")


def test_reverse_a_payment_spread_over_several_invoices():
    ledger = ledger_with(invoice("INV-1"), invoice("INV-2", day=date(2026, 1, 6)))
    ledger.receive("P1", "acme", "150.00", PAY)
    ledger.reverse("P1", date(2026, 1, 11))
    assert balances(ledger) == {"INV-1": D("100.00"), "INV-2": D("100.00")}


def test_reverse_only_undoes_the_named_payment():
    ledger = ledger_with(invoice("INV-1"), invoice("INV-2", day=date(2026, 1, 6)))
    ledger.receive("P1", "acme", "100.00", PAY)
    ledger.receive("P2", "acme", "40.00", PAY)
    ledger.reverse("P2", date(2026, 1, 11))
    assert balances(ledger) == {"INV-1": D("0.00"), "INV-2": D("100.00")}


def test_reverse_unknown_or_already_reversed_raises():
    ledger = ledger_with(invoice())
    with pytest.raises(PaymentError):
        ledger.reverse("NOPE", PAY)
    ledger.receive("P1", "acme", "60.00", PAY)
    ledger.reverse("P1", PAY)
    before = snapshot(ledger)
    with pytest.raises(PaymentError):
        ledger.reverse("P1", PAY)
    assert snapshot(ledger) == before


def test_a_reversed_payment_id_cannot_be_received_again():
    ledger = ledger_with(invoice())
    ledger.receive("P1", "acme", "60.00", PAY)
    ledger.reverse("P1", PAY)
    before = snapshot(ledger)
    with pytest.raises(PaymentError):
        ledger.receive("P1", "acme", "60.00", PAY)
    assert snapshot(ledger) == before
    ledger.receive("P2", "acme", "60.00", PAY)
    assert ledger.invoices["INV-1"].balance == D("40.00")


# R4.9 ---------------------------------------------------------------------

@pytest.mark.parametrize("second_invoice_price", ["100.00", "30.00"])
def test_cannot_reverse_once_its_credit_was_used(second_invoice_price):
    ledger = ledger_with(invoice("INV-1"))
    ledger.receive("P1", "acme", "150.00", PAY)             # 50.00 credit
    ledger.add(invoice("INV-2", price=second_invoice_price, day=date(2026, 1, 8)))
    ledger.issue("INV-2")
    ledger.apply_credit("acme", date(2026, 1, 11))
    before = snapshot(ledger)
    with pytest.raises(PaymentError):
        ledger.reverse("P1", date(2026, 1, 12))
    assert snapshot(ledger) == before
    assert ledger.payments["P1"].reversed is False


def test_can_reverse_when_the_credit_is_untouched():
    ledger = ledger_with(invoice("INV-1"))
    ledger.receive("P1", "acme", "150.00", PAY)
    ledger.reverse("P1", date(2026, 1, 12))
    assert ledger.credit("acme") == 0


# R4.10 --------------------------------------------------------------------

def test_apply_credit_pays_invoices_in_payment_order_and_logs_nothing():
    ledger = Ledger()
    ledger.receive("P1", "acme", "150.00", date(2026, 1, 2))
    for item in (invoice("INV-1", day=date(2026, 1, 20)), invoice("INV-2", day=JAN5)):
        ledger.add(item)
        ledger.issue(item.number)
    count = len(ledger.events)
    ledger.apply_credit("acme", date(2026, 1, 25))
    assert balances(ledger) == {"INV-1": D("50.00"), "INV-2": D("0.00")}
    assert ledger.credit("acme") == 0
    assert len(ledger.events) == count


def test_apply_credit_keeps_what_it_cannot_use():
    ledger = Ledger()
    ledger.receive("P1", "acme", "150.00", date(2026, 1, 2))
    ledger.add(invoice())
    ledger.issue("INV-1")
    ledger.apply_credit("acme", PAY)
    assert ledger.invoices["INV-1"].status == "paid"
    assert ledger.credit("acme") == D("50.00")


def test_apply_credit_never_earns_the_early_payment_discount():
    ledger = Ledger()
    ledger.receive("P1", "acme", "1000.00", date(2026, 1, 2))
    ledger.add(discount_invoice())
    ledger.issue("INV-1")
    ledger.apply_credit("acme", date(2026, 1, 6))
    assert ledger.invoices["INV-1"].status == "paid"
    assert ledger.credit("acme") == 0
    assert events(ledger, "discount") == []


def test_apply_credit_pays_late_fees_first():
    ledger = Ledger()
    ledger.receive("P1", "acme", "20.00", date(2026, 1, 2))
    ledger.add(invoice(price="1000.00"))
    ledger.issue("INV-1")
    ledger.assess_late_fees(late(16))
    ledger.apply_credit("acme", late(17))
    inv = ledger.invoices["INV-1"]
    assert inv.balance == D("995.00")
    assert events(ledger, "fee")[0].amount == D("15.00")


def test_apply_credit_skips_disputed_and_does_nothing_without_credit():
    ledger = ledger_with(invoice())
    ledger.apply_credit("acme", PAY)
    assert ledger.invoices["INV-1"].balance == D("100.00")
    ledger2 = Ledger()
    ledger2.receive("P1", "acme", "50.00", date(2026, 1, 2))
    ledger2.add(invoice())
    ledger2.issue("INV-1")
    ledger2.dispute("INV-1")
    ledger2.apply_credit("acme", PAY)
    assert ledger2.invoices["INV-1"].balance == D("100.00")
    assert ledger2.credit("acme") == D("50.00")


def test_invoice_with_lines_still_pays_by_total():
    lines = [Line("a", 1, "100.00"), Line("b", 1, "50.00", taxable=False)]
    ledger = ledger_with(invoice(lines=lines, tax_rate=10))
    ledger.receive("P1", "acme", "160.00", PAY)
    assert ledger.invoices["INV-1"].status == "paid"
