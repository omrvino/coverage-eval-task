import re
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

from .errors import InvoiceError, PaymentError
from .money import money

GRACE_DAYS = 5
PERIOD_DAYS = 30
FEE_RATE = Decimal("0.015")
MIN_FEE = Decimal("5.00")
FEE_CAP = Decimal("0.10")


@dataclass
class Event:
    date: date
    customer: str
    kind: str
    ref: str
    amount: Decimal


@dataclass
class Allocation:
    invoice: str
    principal: Decimal
    fees: Decimal
    discount: Decimal = Decimal("0.00")


@dataclass
class Payment:
    id: str
    customer: str
    amount: Decimal
    date: date
    allocations: list = field(default_factory=list)
    credit: Decimal = Decimal("0.00")
    reversed: bool = False


def _number_key(number):
    """Sort key that reads digit runs as numbers, so INV-2 < INV-10."""
    return [(0, int(p), "") if p.isdigit() else (1, 0, p) for p in re.findall(r"\d+|\D+", number)]


class Ledger:
    def __init__(self, holidays=()):
        self.holidays = frozenset(holidays)
        self.invoices = {}
        self.payments = {}
        self.credits = {}
        self.events = []

    # -- invoices ---------------------------------------------------------

    def add(self, invoice):
        if invoice.number in self.invoices:
            raise InvoiceError(f"duplicate invoice number {invoice.number}")
        self.invoices[invoice.number] = invoice
        return invoice

    def issue(self, number):
        invoice = self._invoice(number)
        invoice.issue(self.holidays)
        self._log(invoice.date, invoice.customer, "invoice", number, invoice.total)

    def void(self, number, on):
        invoice = self._invoice(number)
        owed = invoice.balance
        invoice.void()
        self._log(on, invoice.customer, "void", number, -owed)

    def dispute(self, number):
        invoice = self._invoice(number)
        if invoice.status != "open":
            raise InvoiceError(f"{number} is not open")
        invoice.disputed = True

    def resolve(self, number):
        self._invoice(number).disputed = False

    # -- money in ---------------------------------------------------------

    def receive(self, payment_id, customer, amount, on):
        """Record a customer payment and spread it over what they owe."""
        amount = money(amount)
        if amount <= 0:
            raise PaymentError("payment must be positive")
        known = self.payments.get(payment_id)
        if known is not None:
            if known.reversed or known.amount != amount or known.customer != customer:
                raise PaymentError(f"payment id {payment_id} was already used")
            return known
        payment = Payment(payment_id, customer, amount, on)
        payment.allocations, payment.credit = self._spread(customer, amount, on, discounts=True)
        self.credits[customer] = self.credit(customer) + payment.credit
        self.payments[payment_id] = payment
        self._log(on, customer, "payment", payment_id, -amount)
        for allocation in payment.allocations:
            if allocation.discount:
                self._log(on, customer, "discount", allocation.invoice, -allocation.discount)
        return payment

    def apply_credit(self, customer, on):
        """Use the customer's unapplied credit on what they owe."""
        allocations, left = self._spread(customer, self.credit(customer), on, discounts=False)
        self.credits[customer] = left
        return allocations

    def reverse(self, payment_id, on):
        """Undo a payment that did not clear."""
        payment = self.payments.get(payment_id)
        if payment is None or payment.reversed:
            raise PaymentError(f"no payment {payment_id} to reverse")
        if self.credit(payment.customer) < payment.credit:
            raise PaymentError(f"credit from {payment_id} has been used")
        restored = payment.amount
        for allocation in payment.allocations:
            invoice = self.invoices[allocation.invoice]
            invoice.paid -= allocation.principal
            invoice.fees_paid -= allocation.fees
            restored += allocation.discount
        self.credits[payment.customer] = self.credit(payment.customer) - payment.credit
        payment.reversed = True
        self._log(on, payment.customer, "reversal", payment_id, restored)

    def credit(self, customer):
        return self.credits.get(customer, Decimal("0.00"))

    # -- late fees --------------------------------------------------------

    def assess_late_fees(self, on):
        """Charge late fees for every period started by ``on``. Safe to repeat."""
        charged = {}
        for number, invoice in self.invoices.items():
            if invoice.status != "open" or invoice.principal_due <= 0:
                continue
            days_late = (on - invoice.due).days
            if days_late < GRACE_DAYS:
                continue
            periods = (days_late + PERIOD_DAYS - 1) // PERIOD_DAYS
            new_periods = periods - invoice.fee_periods
            if new_periods <= 0:
                continue
            invoice.fee_periods = periods
            if invoice.disputed:
                continue
            per_period = max(money(invoice.principal_due * FEE_RATE), MIN_FEE)
            room = money(invoice.total * FEE_CAP) - invoice.fees
            fee = min(per_period * new_periods, room)
            if fee > 0:
                invoice.fees += fee
                charged[number] = fee
                self._log(on, invoice.customer, "fee", number, fee)
        return charged

    # -- helpers ----------------------------------------------------------

    def _invoice(self, number):
        try:
            return self.invoices[number]
        except KeyError:
            raise InvoiceError(f"no invoice {number}") from None

    def _log(self, on, customer, kind, ref, amount):
        self.events.append(Event(on, customer, kind, ref, amount))

    def _payable(self, customer):
        found = [
            inv for inv in self.invoices.values()
            if inv.customer == customer and inv.status == "open" and not inv.disputed
        ]
        return sorted(found, key=lambda inv: (inv.due, inv.number))

    def _spread(self, customer, amount, on, discounts):
        allocations = []
        for invoice in self._payable(customer):
            if amount <= 0:
                break
            discount = invoice.early_discount(on, self.holidays) if discounts else Decimal("0.00")
            if not discount or amount < invoice.balance - discount:
                discount = Decimal("0.00")
            fees = min(amount, invoice.fees_due)
            principal = min(amount - fees, invoice.principal_due - discount)
            invoice.fees_paid += fees
            invoice.paid += principal
            invoice.discount_taken += discount
            amount -= fees + principal
            allocations.append(Allocation(invoice.number, principal, fees, discount))
        return allocations, amount
