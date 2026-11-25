"""Every fault the grader injects, as small text edits to the correct source.

SHIPPED are the bugs left in the repository the model is given, and UNSCORED the
ones there whose rule can be read two ways.
HIDDEN and DEEP are applied one at a time to the correct source while grading.
Each edit is (file, old text, new text) and must match exactly once unless ALL is set.
"""

from dataclasses import dataclass

ALL = "ALL"


@dataclass(frozen=True)
class Fault:
    id: str
    rule: str
    what: str
    edits: tuple


def F(id, rule, what, *edits):
    return Fault(id, rule, what, edits)


SHIPPED = [
    F("S1", "R1.2", "rounds half up instead of half to even",
      ("money.py", "ROUND_HALF_EVEN", "ROUND_HALF_UP", ALL)),
    F("S2", "R2.4", "discount deadline moves for weekends and holidays",
      ("terms.py", "        return deadline\n", "        return _roll_forward(deadline, holidays)\n")),
    F("S3", "R3.2", "tax rounded per line, then summed",
      ("invoice.py",
       "        taxable = sum((line.net for line in self.lines if line.taxable), Decimal(0))\n"
       "        return money(taxable * self.tax_rate / 100)\n",
       "        per_line = [money(line.net * self.tax_rate / 100) for line in self.lines if line.taxable]\n"
       "        return sum(per_line, Decimal(\"0.00\"))\n")),
    F("S4", "R4.1", "equal due dates sorted by invoice number as text",
      ("ledger.py", "(inv.due, _number_key(inv.number))", "(inv.due, inv.number)")),
    F("S5", "R5.1", "grace period one day short",
      ("ledger.py", "if days_late <= GRACE_DAYS", "if days_late < GRACE_DAYS")),
    F("S6", "R6.3", "credit reduces the newest bucket first",
      ("reports.py", "for name in reversed(BUCKETS):", "for name in BUCKETS:")),
    F("S7", "R4.8", "reversal leaves the early-payment discount in place",
      ("ledger.py", "            invoice.discount_taken -= allocation.discount\n", "")),
    F("S8", "R8.2", "line numbers skip blank lines",
      ("importer.py",
       "    for row in reader:\n        line = reader.line_num\n",
       "    rows = [row for row in reader if any(cell.strip() for cell in row)]\n"
       "    for line, row in enumerate(rows, start=2):\n")),
    # Not planted. I left this one in by accident and the first agent runs found it.
    F("S9", "R9.4", "a file that is not UTF-8 raises UnicodeDecodeError",
      ("store.py", "    except (json.JSONDecodeError, UnicodeDecodeError):\n", "    except json.JSONDecodeError:\n")),
]

# Also left in by accident: cases the spec can be read two ways on, or that need dates
# entered out of order. Reporting one is neither rewarded nor punished. The correct
# source follows the strict reading.
UNSCORED = [
    F("U3", "R4.3", "discount still granted when the earlier payment covered only late fees",
      ("invoice.py", "on > deadline or self.paid or self.fees_paid:", "on > deadline or self.paid:")),
    F("U1", "R1.3", "split can return a Decimal without two places",
      ("money.py", "    return [money(sign * Decimal(p) / 100) for p in parts]\n",
       "    return [sign * Decimal(p) / 100 for p in parts]\n")),
    F("U2", "R8.5", "single-digit months and days accepted",
      ("importer.py",
       "    for pattern, shape in ((\"%Y-%m-%d\", r\"\\d{4}-\\d\\d-\\d\\d\"), (\"%m/%d/%Y\", r\"\\d\\d/\\d\\d/\\d{4}\")):\n"
       "        if not re.fullmatch(shape, text):\n            continue\n        try:\n",
       "    for pattern in (\"%Y-%m-%d\", \"%m/%d/%Y\"):\n        try:\n")),
]

# Rules where a reported finding is ignored, because a fair reader could report it.
OPEN_TO_READING = {f.rule for f in UNSCORED} | {"R2.5", "R4.9"}

HIDDEN = [
    F("H01", "R1.1", "accepts bool as money", ("money.py", "(bool, float)", "(float,)")),
    F("H02", "R1.1", "accepts NaN as money",
      ("money.py", "if not amount.is_finite():", "if amount.is_infinite():")),
    F("H03", "R1.3", "ties for leftover cents go to the later position",
      ("money.py", "(-(exact[i] - parts[i]), i)", "(-(exact[i] - parts[i]), -i)")),
    F("H04", "R1.3", "leftover cents go to the first positions",
      ("money.py", "key=lambda i: (-(exact[i] - parts[i]), i)", "key=lambda i: i")),
    F("H05", "R1.3", "negative totals lose their sign",
      ("money.py", "sign = -1 if total < 0 else 1", "sign = 1")),
    F("H06", "R1.4", "negative weights allowed",
      ("money.py", "if any(w < 0 for w in shares):", "if all(w < 0 for w in shares):")),
    F("H07", "R2.3", "a weekend that rolls onto a holiday stays on the holiday",
      ("terms.py", "    while day.weekday() >= 5 or day in holidays:\n        day += timedelta(days=1)\n",
       "    while day in holidays:\n        day += timedelta(days=1)\n"
       "    while day.weekday() >= 5:\n        day += timedelta(days=1)\n")),
    F("H08", "R2.2", "EOM cutoff is the 27th",
      ("terms.py", "day.day >= EOM_CUTOFF_DAY", "day.day > EOM_CUTOFF_DAY")),
    F("H09", "R2.2", "EOM after the cutoff in December stays in the same year",
      ("terms.py", "day.year + day.month // 12", "day.year")),
    F("H10", "R4.3", "no discount on the deadline day itself",
      ("invoice.py", "on > deadline", "on >= deadline")),
    F("H11", "R4.3", "discount computed on the total including tax",
      ("invoice.py", "money(self.net * terms.discount_pct / 100)", "money(self.total * terms.discount_pct / 100)")),
    F("H12", "R2.5", "a 100 percent discount is accepted", ("terms.py", "pct >= 100", "pct > 100")),
    F("H13", "R2.5", "discount window may exceed the net days", ("terms.py", " or days > net", "")),
    F("H14", "R3.4", "a 100 percent line discount is refused",
      ("invoice.py", "0 <= self.discount_pct <= 100", "0 <= self.discount_pct < 100")),
    F("H15", "R3.2", "tax charged on non-taxable lines",
      ("invoice.py", "line.net for line in self.lines if line.taxable", "line.net for line in self.lines")),
    F("H16", "R3.1", "line net is not rounded",
      ("invoice.py", "return money(gross * (100 - self.discount_pct) / 100)",
       "return gross * (100 - self.discount_pct) / 100")),
    F("H17", "R3.5", "zero-total invoices cannot be issued", ("invoice.py", "if self.total < 0:", "if self.total <= 0:")),
    F("H18", "R3.7", "can void after a payment that covered only late fees",
      ("invoice.py", "if self.paid or self.fees_paid:", "if self.paid:")),
    F("H19", "R3.7", "void writes off the total but not late fees",
      ("ledger.py", "owed = invoice.balance", "owed = invoice.total")),
    F("H20", "R3.6", "paid while late fees are still owed",
      ("invoice.py", "return \"paid\" if self.balance == 0", "return \"paid\" if self.principal_due == 0")),
    F("H21", "R4.2", "principal paid before late fees",
      ("ledger.py",
       "            fees = min(amount, invoice.fees_due)\n"
       "            principal = min(amount - fees, invoice.principal_due - discount)\n",
       "            principal = min(amount, invoice.principal_due - discount)\n"
       "            fees = min(amount - principal, invoice.fees_due)\n")),
    F("H22", "R4.3", "discount granted after an earlier partial payment",
      ("invoice.py", " or self.paid or self.fees_paid:\n            return Decimal(\"0.00\")", ":\n            return Decimal(\"0.00\")")),
    F("H23", "R4.3", "discount granted to a partial payment",
      ("ledger.py", "if not discount or amount < invoice.balance - discount:", "if not discount:")),
    F("H24", "R4.5", "a reused payment id with another amount is ignored",
      ("ledger.py", " or known.amount != amount", "")),
    F("H25", "R4.8", "a reversed payment id can be received again silently",
      ("ledger.py", "if known.reversed or known.amount", "if known.amount")),
    F("H26", "R4.7", "payments reach disputed invoices", ("ledger.py", " and not inv.disputed", "")),
    F("H27", "R4.8", "reversal does not restore late fees paid",
      ("ledger.py", "            invoice.fees_paid -= allocation.fees\n", "")),
    F("H28", "R4.8", "reversal keeps the credit the payment left",
      ("ledger.py", "        self.credits[payment.customer] = self.credit(payment.customer) - payment.credit\n", "")),
    F("H29", "R4.9", "payment can be reversed after its credit was used",
      ("ledger.py", "if self.credit(payment.customer) < payment.credit:", "if False:")),
    F("H30", "R4.10", "credit earns the early-payment discount",
      ("ledger.py", "on, discounts=False)", "on, discounts=True)")),
    F("H31", "R5.2", "day 30 already starts the second period",
      ("ledger.py", "(days_late + PERIOD_DAYS - 1) // PERIOD_DAYS", "days_late // PERIOD_DAYS + 1")),
    F("H32", "R5.3", "no minimum fee",
      ("ledger.py", "max(money(invoice.principal_due * FEE_RATE), MIN_FEE)", "money(invoice.principal_due * FEE_RATE)")),
    F("H33", "R5.3", "late fees earn late fees",
      ("ledger.py", "money(invoice.principal_due * FEE_RATE)", "money(invoice.balance * FEE_RATE)")),
    F("H34", "R5.4", "the cap forgets fees already charged",
      ("ledger.py", "money(invoice.total * FEE_CAP) - invoice.fees\n", "money(invoice.total * FEE_CAP)\n")),
    F("H35", "R5.6", "periods under dispute are billed after it is resolved",
      ("ledger.py",
       "            invoice.fee_periods = periods\n            if invoice.disputed:\n                continue\n",
       "            if invoice.disputed:\n                continue\n            invoice.fee_periods = periods\n")),
    F("H36", "R5.5", "earlier periods are charged again",
      ("ledger.py", "per_period * new_periods", "per_period * periods")),
    F("H37", "R6.1", "day 60 falls in the 61-90 bucket", ("reports.py", "if days_late <= 60:", "if days_late < 60:")),
    F("H38", "R6.1", "aging leaves out late fees",
      ("reports.py", "report[name] += invoice.balance", "report[name] += invoice.principal_due")),
    F("H39", "R6.3", "credit reduces the disputed column",
      ("reports.py", "for name in reversed(BUCKETS):", "for name in (*reversed(BUCKETS), \"disputed\"):")),
    F("H40", "R7.1", "statement leaves out its last day", ("reports.py", "start <= e.date <= end", "start <= e.date < end")),
    F("H41", "R7.1", "first day counted in the opening balance", ("reports.py", "if e.date < start)", "if e.date <= start)")),
    F("H42", "R7.2", "same-day events stay in entry order",
      ("reports.py", "(e.date, _SAME_DAY[e.kind])", "e.date")),
    F("H43", "R7.3", "closing balance leaves out the opening balance",
      ("reports.py", "Statement(customer, opening, balance, lines)", "Statement(customer, opening, balance - opening, lines)")),
    F("H44", "R7.4", "statement shows every customer",
      ("reports.py", "[e for e in ledger.events if e.customer == customer]", "list(ledger.events)")),
    F("H45", "R8.4", "a rejected row blocks a later good one",
      ("importer.py", "        elif reference.casefold() in seen:\n            reason = \"duplicate\"\n        else:\n"
                      "            seen.add(reference.casefold())\n",
       "        elif reference.casefold() in seen:\n            reason = \"duplicate\"\n        else:\n"),
      ("importer.py", "        if not reference:\n",
       "        first = reference.casefold() not in seen\n        seen.add(reference.casefold())\n        if not reference:\n"),
      ("importer.py", "elif reference.casefold() in seen:", "elif not first:")),
    F("H46", "R8.4", "duplicate check is case sensitive", ("importer.py", ".casefold()", "", ALL)),
    F("H47", "R8.6", "misplaced commas accepted",
      ("importer.py", "(\\d{1,3}(?:,\\d{3})+|\\d+)", "([\\d,]*\\d)")),
    F("H48", "R8.6", "zero amounts accepted", ("importer.py", "if amount > 0 else None", "if amount >= 0 else None")),
    F("H49", "R8.1", "byte order mark breaks the header", ("importer.py", ".removeprefix(BOM)", "")),
    F("H50", "R8.3", "date checked before customer",
      ("importer.py",
       "        elif not customer:\n            reason = \"missing_customer\"\n"
       "        elif when is None:\n            reason = \"bad_date\"\n",
       "        elif when is None:\n            reason = \"bad_date\"\n"
       "        elif not customer:\n            reason = \"missing_customer\"\n")),
    F("H51", "R9.3", "a failed save leaves its temporary file", ("store.py", "        os.unlink(temp)\n", "")),
    F("H52", "R9.3", "a failed save destroys the existing file",
      ("store.py", "        with os.fdopen(handle, \"w\", encoding=\"utf-8\") as out:\n",
       "        os.close(handle)\n        if path.is_file():\n            path.write_text(\"\", encoding=\"utf-8\")\n"
       "        with open(temp, \"w\", encoding=\"utf-8\") as out:\n")),
    F("H53", "R9.2", "any later expected version is accepted",
      ("store.py", "if current != expected_version:", "if current > expected_version:")),
    F("H54", "R9.1", "holidays are lost on load", ("store.py", "Ledger(data[\"holidays\"])", "Ledger()")),
    F("H55", "R9.4", "unknown schema accepted", ("store.py", " or data.get(\"schema\") != SCHEMA", "")),
    F("H56", "R3.3", "tax-exempt invoices are taxed", ("invoice.py", "        if self.tax_exempt:", "        if False:")),
]

_PAID_BEFORE = "any(a.invoice == {} for p in self.payments.values() for a in p.allocations)"

# Bugs that show only across several steps: pay then reverse, charge then pay then
# charge, save then load then carry on. Written from the spec, before looking at any
# submission's tests.
DEEP = [
    F("D01", "R4.8", "a reversed payment still blocks the early-payment discount",
      ("ledger.py", "if discounts else Decimal(\"0.00\")\n",
       "if discounts and not " + _PAID_BEFORE.format("invoice.number") + " else Decimal(\"0.00\")\n")),
    F("D02", "R3.7", "cannot void after the only payment was reversed",
      ("ledger.py", "        owed = invoice.balance\n",
       "        owed = invoice.balance\n        if " + _PAID_BEFORE.format("number") + ":\n"
       "            raise InvoiceError(number)\n")),
    F("D03", "R5.5", "reversing a payment makes past periods chargeable again",
      ("ledger.py", "            invoice.paid -= allocation.principal\n",
       "            invoice.paid -= allocation.principal\n            invoice.fee_periods = 0\n")),
    F("D04", "R9.1", "a loaded ledger forgets which fee periods were charged",
      ("store.py", "        ledger.invoices[item[\"number\"]]", "        item[\"fee_periods\"] = 0\n        ledger.invoices[item[\"number\"]]")),
    F("D05", "R9.1", "payments that only left credit are lost on load",
      ("store.py", "        ledger.payments[item[\"id\"]] = Payment(**item)\n",
       "        if item[\"allocations\"]:\n            ledger.payments[item[\"id\"]] = Payment(**item)\n")),
    F("D06", "R9.1", "a reversed payment can be reversed again after load",
      ("store.py", "        ledger.payments[item[\"id\"]]", "        item[\"reversed\"] = False\n        ledger.payments[item[\"id\"]]")),
    F("D07", "R5.3", "fee charged on the invoice total after a part payment",
      ("ledger.py", "money(invoice.principal_due * FEE_RATE)", "money(invoice.total * FEE_RATE)")),
    F("D08", "R5.3", "minimum fee applied once instead of per period",
      ("ledger.py", "max(money(invoice.principal_due * FEE_RATE), MIN_FEE)\n", "money(invoice.principal_due * FEE_RATE)\n"),
      ("ledger.py", "min(per_period * new_periods, room)", "min(max(per_period * new_periods, MIN_FEE), room)")),
    F("D09", "R5.3", "fee rounded after adding the periods up",
      ("ledger.py", "money(invoice.principal_due * FEE_RATE)", "invoice.principal_due * FEE_RATE"),
      ("ledger.py", "min(per_period * new_periods, room)", "min(money(per_period * new_periods), room)")),
    F("D10", "R5.4", "cap taken from the net, before tax",
      ("ledger.py", "money(invoice.total * FEE_CAP)", "money(invoice.net * FEE_CAP)")),
    F("D11", "R5.4", "cap shrinks as the invoice is paid",
      ("ledger.py", "money(invoice.total * FEE_CAP)", "money(invoice.principal_due * FEE_CAP)")),
    F("D12", "R5.1", "periods counted from the end of the grace days",
      ("ledger.py", "(days_late + PERIOD_DAYS - 1)", "(days_late - GRACE_DAYS + PERIOD_DAYS - 1)")),
    F("D13", "R4.4", "a second overpayment replaces the first credit",
      ("ledger.py", "self.credits[customer] = self.credit(customer) + payment.credit", "self.credits[customer] = payment.credit")),
    F("D14", "R4.9", "reversal allowed while only part of the credit is left",
      ("ledger.py", "if self.credit(payment.customer) < payment.credit:", "if payment.credit and not self.credit(payment.customer):")),
    F("D15", "R4.10", "credit pays the latest invoice first",
      ("ledger.py", "        for invoice in self._payable(customer):", "        for invoice in self._payable(customer)[:: 1 if discounts else -1]:")),
    F("D16", "R4.10", "using credit is logged as a second payment",
      ("ledger.py", "        self.credits[customer] = left\n",
       "        for a in allocations:\n            self._log(on, customer, \"payment\", a.invoice, -a.principal - a.fees)\n"
       "        self.credits[customer] = left\n")),
    F("D17", "R4.3", "discount judged on the whole payment, not what reaches the invoice",
      ("ledger.py", "        allocations = []\n        for", "        allocations, whole = [], amount\n        for"),
      ("ledger.py", "amount < invoice.balance - discount", "whole < invoice.balance - discount")),
    F("D18", "R4.3", "only the first invoice in a payment can earn its discount",
      ("ledger.py", "            allocations.append(Allocation(invoice.number, principal, fees, discount))\n",
       "            allocations.append(Allocation(invoice.number, principal, fees, discount))\n            discounts = False\n")),
    F("D19", "R4.8", "reversal event leaves out the discount",
      ("ledger.py", "            restored += allocation.discount\n", "")),
    F("D20", "R4.8", "reversal event carries the payment's date",
      ("ledger.py", "self._log(on, payment.customer, \"reversal\"", "self._log(payment.date, payment.customer, \"reversal\"")),
    F("D21", "R3.7", "void event carries the invoice's date",
      ("ledger.py", "self._log(on, invoice.customer, \"void\"", "self._log(invoice.date, invoice.customer, \"void\"")),
    F("D22", "R2.3", "EOM due dates are not moved",
      ("terms.py", "            due = _end_of_month(invoice_date)\n", "            return _end_of_month(invoice_date)\n")),
    F("D23", "R2.2", "EOM from late January skips February",
      ("terms.py", "day = date(day.year + day.month // 12, day.month % 12 + 1, 1)", "day = day + timedelta(days=31)")),
    F("D24", "R2.3", "the ledger's holidays are not used when issuing",
      ("ledger.py", "invoice.issue(self.holidays)", "invoice.issue()")),
    F("D25", "R3.2", "tax charged on the price before the line discount",
      ("invoice.py", "taxable = sum((line.net for line", "taxable = sum((line.quantity * line.unit_price for line")),
    F("D26", "R9.2", "any expected version is accepted for a new file",
      ("store.py", "if current != expected_version:", "if current and current != expected_version:")),
    F("D27", "R4.5", "repeating a payment logs it again",
      ("ledger.py", "            return known\n",
       "            self._log(on, customer, \"payment\", payment_id, -amount)\n            return known\n")),
]


def apply_fault(fault, sources):
    """Return a copy of ``sources`` ({name: text}) with the fault in place."""
    out = dict(sources)
    for name, old, new, *flag in fault.edits:
        found = out[name].count(old)
        if found == 0 or (found > 1 and ALL not in flag):
            raise ValueError(f"{fault.id}: edit to {name} matches {found} times")
        out[name] = out[name].replace(old, new)
    return out
