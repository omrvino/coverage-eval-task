# tally

A small accounts-receivable ledger: invoices, payments, late fees, aging, statements, bank imports and a JSON store. Pure Python, no runtime dependencies.

The rules are in [docs/SPEC.md](docs/SPEC.md).

## Tests

```
python -m pytest --cov=tally --cov-branch
```
