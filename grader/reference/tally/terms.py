import calendar
import re
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal

from .errors import TermsError

EOM_CUTOFF_DAY = 26

_NET = re.compile(r"NET\s*(\d+)")
_DISCOUNT = re.compile(r"(\d+(?:\.\d+)?)\s*/\s*(\d+)\s+NET\s*(\d+)")


def _roll_forward(day, holidays):
    while day.weekday() >= 5 or day in holidays:
        day += timedelta(days=1)
    return day


def _end_of_month(day):
    if day.day >= EOM_CUTOFF_DAY:
        day = date(day.year + day.month // 12, day.month % 12 + 1, 1)
    return day.replace(day=calendar.monthrange(day.year, day.month)[1])


@dataclass(frozen=True)
class Terms:
    """Parsed payment terms."""

    net_days: int | None
    discount_pct: Decimal = Decimal(0)
    discount_days: int = 0

    def due_date(self, invoice_date, holidays=frozenset()):
        if self.net_days is None:
            due = _end_of_month(invoice_date)
        else:
            due = invoice_date + timedelta(days=self.net_days)
        return _roll_forward(due, holidays)

    def discount_deadline(self, invoice_date, holidays=frozenset()):
        """Last day the early-payment discount is available, or None."""
        if not self.discount_pct:
            return None
        deadline = invoice_date + timedelta(days=self.discount_days)
        return deadline


def parse_terms(text):
    """Parse ``NET 30``, ``EOM`` or ``2/10 NET 30``."""
    cleaned = text.strip().upper()
    if cleaned == "EOM":
        return Terms(net_days=None)
    match = _NET.fullmatch(cleaned)
    if match:
        return Terms(net_days=int(match.group(1)))
    match = _DISCOUNT.fullmatch(cleaned)
    if match:
        pct, days, net = Decimal(match.group(1)), int(match.group(2)), int(match.group(3))
        if pct >= 100 or days > net:
            raise TermsError(f"impossible discount terms: {text!r}")
        return Terms(net_days=net, discount_pct=pct, discount_days=days)
    raise TermsError(f"unknown terms: {text!r}")
