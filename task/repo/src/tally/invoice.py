from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

from .errors import InvoiceError
from .money import money
from .terms import parse_terms


@dataclass
class Line:
    description: str
    quantity: Decimal
    unit_price: Decimal
    discount_pct: Decimal = Decimal(0)
    taxable: bool = True

    def __post_init__(self):
        self.quantity = Decimal(self.quantity)
        self.unit_price = Decimal(self.unit_price)
        self.discount_pct = Decimal(self.discount_pct)
        if self.quantity <= 0:
            raise InvoiceError("quantity must be positive")
        if not 0 <= self.discount_pct <= 100:
            raise InvoiceError("line discount must be between 0 and 100 percent")

    @property
    def net(self):
        gross = self.quantity * self.unit_price
        return money(gross * (100 - self.discount_pct) / 100)


@dataclass
class Invoice:
    number: str
    customer: str
    date: date
    terms: str
    lines: list = field(default_factory=list)
    tax_rate: Decimal = Decimal(0)
    tax_exempt: bool = False

    issued: bool = False
    voided: bool = False
    disputed: bool = False
    due: date | None = None
    paid: Decimal = Decimal(0)
    discount_taken: Decimal = Decimal(0)
    fees: Decimal = Decimal(0)
    fees_paid: Decimal = Decimal(0)
    fee_periods: int = 0

    def __post_init__(self):
        self.tax_rate = Decimal(self.tax_rate)

    @property
    def net(self):
        return sum((line.net for line in self.lines), Decimal(0))

    @property
    def tax(self):
        if self.tax_exempt:
            return Decimal("0.00")
        per_line = [money(line.net * self.tax_rate / 100) for line in self.lines if line.taxable]
        return sum(per_line, Decimal("0.00"))

    @property
    def total(self):
        return self.net + self.tax

    @property
    def principal_due(self):
        """What is still owed on the invoice itself, without late fees."""
        return self.total - self.discount_taken - self.paid

    @property
    def fees_due(self):
        return self.fees - self.fees_paid

    @property
    def balance(self):
        return self.principal_due + self.fees_due

    @property
    def status(self):
        if self.voided:
            return "void"
        if not self.issued:
            return "draft"
        return "paid" if self.balance == 0 else "open"

    def issue(self, holidays=frozenset()):
        if self.issued or self.voided:
            raise InvoiceError(f"{self.number} was already issued")
        if not self.lines:
            raise InvoiceError(f"{self.number} has no lines")
        if self.total < 0:
            raise InvoiceError(f"{self.number} has a negative total")
        self.due = parse_terms(self.terms).due_date(self.date, holidays)
        self.issued = True

    def void(self):
        if self.voided or not self.issued:
            raise InvoiceError(f"{self.number} cannot be voided")
        if self.paid or self.fees_paid:
            raise InvoiceError(f"{self.number} has payments applied")
        self.voided = True

    def early_discount(self, on, holidays=frozenset()):
        """Discount available to a payment that settles the invoice on ``on``."""
        terms = parse_terms(self.terms)
        deadline = terms.discount_deadline(self.date, holidays)
        if deadline is None or on > deadline or self.paid:
            return Decimal("0.00")
        return money(self.net * terms.discount_pct / 100)
