# Findings

Places where the code contradicts docs/SPEC.md. Each has a strict xfail test that will start failing (XPASS) once the code is fixed, so remove the marker then.

- R1.2: money() rounds ties half up (2.665 gives 2.67, 2.645 gives 2.65); the spec says round half to even (2.66, 2.64).
- R2.4: Terms.discount_deadline() rolls a weekend or holiday deadline forward (Sat Jan 17 2026 becomes Mon Jan 19); the spec says the discount deadline does not move.
- R3.2: Invoice.tax rounds tax per taxable line (two lines of 0.02 at 30% give 0.02); the spec says tax is computed once on the summed net (0.04 gives 0.01).
- R4.1: payments order equal due dates as text, so INV-10 is paid before INV-2; the spec compares digit runs as numbers (the _number_key helper exists but is never used).
- R4.8: Ledger.reverse() restores principal and late fees but not the early-payment discount, so a reversed discounted payment leaves the invoice 2.00 short; the spec says the reversal undoes the discount too.
- R5.1: assess_late_fees() charges a fee on the 5th day late (days_late < 5 check); the spec says no fee for 5 days late or less.
- R6.3: aging() applies a customer's credit to the current bucket first and 91+ last; the spec says the oldest bucket (91+) first.
- R8.2: parse_deposits() drops blank lines before numbering rows, so a rejected row after a blank line gets the wrong line number; the spec says blank lines count and the header is line 1.
- R8.5: parse_deposits() reads dates with strptime, which accepts single-digit fields (2026-1-5, 1/5/2026); the spec allows only YYYY-MM-DD and MM/DD/YYYY.
- R9.4: load() and save() let a non-UTF-8 file raise UnicodeDecodeError; the spec says a file that is not a ledger raises StoreError.
