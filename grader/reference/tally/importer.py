import csv
import io
import re
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal

from .errors import ImportFormatError

BOM = chr(0xFEFF)
REQUIRED = ("date", "reference", "customer", "amount")
_AMOUNT = re.compile(r"\$?(\d{1,3}(?:,\d{3})+|\d+)(\.\d{1,2})?")


@dataclass
class Deposit:
    date: date
    reference: str
    customer: str
    amount: Decimal


@dataclass
class Rejection:
    line: int
    reason: str


@dataclass
class ImportResult:
    accepted: list = field(default_factory=list)
    rejected: list = field(default_factory=list)


def _parse_date(text):
    for pattern, shape in (("%Y-%m-%d", r"\d{4}-\d\d-\d\d"), ("%m/%d/%Y", r"\d\d/\d\d/\d{4}")):
        if not re.fullmatch(shape, text):
            continue
        try:
            return datetime.strptime(text, pattern).date()
        except ValueError:
            pass
    return None


def _parse_amount(text):
    if not _AMOUNT.fullmatch(text):
        return None
    amount = Decimal(text.replace("$", "").replace(",", "")).quantize(Decimal("0.01"))
    return amount if amount > 0 else None


def parse_deposits(text):
    """Read a bank deposit CSV. Bad rows are reported, not fatal."""
    reader = csv.reader(io.StringIO(text.removeprefix(BOM)))
    header = [name.strip().lower() for name in next(reader, [])]
    missing = [name for name in REQUIRED if name not in header]
    if missing:
        raise ImportFormatError(f"missing columns: {', '.join(missing)}")
    result, seen = ImportResult(), set()
    for row in reader:
        line = reader.line_num
        if not any(cell.strip() for cell in row):
            continue
        record = {name: cell.strip() for name, cell in zip(header, row)}
        reference = record.get("reference", "")
        customer = record.get("customer", "")
        when = _parse_date(record.get("date", ""))
        amount = _parse_amount(record.get("amount", ""))
        if not reference:
            reason = "missing_reference"
        elif not customer:
            reason = "missing_customer"
        elif when is None:
            reason = "bad_date"
        elif amount is None:
            reason = "bad_amount"
        elif reference.casefold() in seen:
            reason = "duplicate"
        else:
            seen.add(reference.casefold())
            result.accepted.append(Deposit(when, reference, customer, amount))
            continue
        result.rejected.append(Rejection(line, reason))
    return result
