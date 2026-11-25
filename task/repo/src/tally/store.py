import json
import os
import tempfile
from dataclasses import fields
from datetime import date
from decimal import Decimal
from pathlib import Path

from .errors import ConflictError, StoreError
from .invoice import Invoice, Line
from .ledger import Allocation, Event, Ledger, Payment

SCHEMA = 1


def _pack(value):
    if isinstance(value, Decimal):
        return {"$d": str(value)}
    if isinstance(value, date):
        return {"$t": value.isoformat()}
    if isinstance(value, list):
        return [_pack(v) for v in value]
    if isinstance(value, (Invoice, Line, Payment, Allocation, Event)):
        return {f.name: _pack(getattr(value, f.name)) for f in fields(value)}
    return value


def _unpack(value):
    if isinstance(value, dict):
        if "$d" in value:
            return Decimal(value["$d"])
        if "$t" in value:
            return date.fromisoformat(value["$t"])
        return {k: _unpack(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_unpack(v) for v in value]
    return value


def _read(path):
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        raise StoreError(f"{path} is not a ledger file") from None
    if not isinstance(data, dict) or data.get("schema") != SCHEMA:
        raise StoreError(f"{path} has an unknown schema")
    return data


def save(ledger, path, expected_version):
    """Write the ledger if nobody else has since ``expected_version``."""
    path = Path(path)
    current = _read(path)["version"] if path.is_file() else 0
    if current != expected_version:
        raise ConflictError(f"expected version {expected_version}, found {current}")
    data = {
        "schema": SCHEMA,
        "version": current + 1,
        "holidays": [_pack(day) for day in sorted(ledger.holidays)],
        "invoices": [_pack(inv) for inv in ledger.invoices.values()],
        "payments": [_pack(pay) for pay in ledger.payments.values()],
        "credits": {name: _pack(amount) for name, amount in ledger.credits.items()},
        "events": [_pack(event) for event in ledger.events],
    }
    handle, temp = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
    try:
        with os.fdopen(handle, "w", encoding="utf-8") as out:
            json.dump(data, out, indent=1)
        os.replace(temp, path)
    except BaseException:
        os.unlink(temp)
        raise
    return current + 1


def load(path):
    """Return ``(ledger, version)``."""
    data = _unpack(_read(Path(path)))
    ledger = Ledger(data["holidays"])
    for item in data["invoices"]:
        item["lines"] = [Line(**line) for line in item["lines"]]
        ledger.invoices[item["number"]] = Invoice(**item)
    for item in data["payments"]:
        item["allocations"] = [Allocation(**a) for a in item["allocations"]]
        ledger.payments[item["id"]] = Payment(**item)
    ledger.credits = data["credits"]
    ledger.events = [Event(**item) for item in data["events"]]
    return ledger, data["version"]
