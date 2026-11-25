# tally: behavior specification

This document is the contract. Where code and spec disagree, the spec is right.

- The public API is what `tally/__init__.py` exports, plus the public attributes and methods of those objects. Names starting with an underscore are internal.
- Exception **types** are part of the contract. Message wording is not.
- All money is `Decimal` with two places. No function reads the system clock; dates are always passed in.

## 1. Money

- **R1.1** `money(x)` accepts `int`, `str` and `Decimal`. `float`, `bool` and any other type raise `TypeError`. Text that is not a number, infinities and NaN raise `ValueError`.
- **R1.2** Rounding is to the cent, half to even: `2.665` becomes `2.66`, `2.675` becomes `2.68`.
- **R1.3** `split(total, weights)` returns one part per weight, and the parts always add up to exactly `money(total)`. Each part starts at its exact share cut down to the cent. Leftover cents go one each to the largest remainders; ties go to the earlier position. A negative total gives the negated result of the positive one.
- **R1.4** Negative weights, all-zero weights and an empty list raise `ValueError`. A zero weight always receives zero.

## 2. Terms and dates

- **R2.1** `NET n`: due `n` calendar days after the invoice date.
- **R2.2** `EOM`: due on the last day of the invoice's month. An invoice dated the 26th or later is due at the end of the **next** month.
- **R2.3** A due date on a Saturday, Sunday or holiday moves forward to the next day that is none of these.
- **R2.4** `p/d NET n` (for example `2/10 NET 30`): `p` percent off if settled within `d` calendar days of the invoice date. The discount deadline does **not** move for weekends or holidays.
- **R2.5** Terms text ignores case and surrounding spaces. Anything else raises `TermsError`, including a discount of 100 percent or more and a discount window longer than the net days.

## 3. Invoices

- **R3.1** Line net = quantity x unit price, less the line discount, rounded to the cent per line.
- **R3.2** Tax is computed once, on the sum of the taxable line nets, and rounded once. It is never rounded per line. Non-taxable lines are left out.
- **R3.3** A tax-exempt invoice has no tax.
- **R3.4** Quantity must be more than zero and the line discount between 0 and 100 inclusive, otherwise `InvoiceError`. Unit price may be negative (a credit line).
- **R3.5** Issuing needs at least one line and a total of zero or more, otherwise `InvoiceError`. Issuing twice, or issuing a void invoice, raises `InvoiceError`.
- **R3.6** Status is `draft`, `open`, `paid` (issued and nothing owed, late fees included) or `void`.
- **R3.7** An invoice can be voided only when issued, not already void and with no payment applied; otherwise `InvoiceError`. Voiding writes off the whole balance, late fees included, as one `void` event.
- **R3.8** Only an open invoice can be disputed, otherwise `InvoiceError`. Adding a duplicate invoice number, or naming an unknown one, raises `InvoiceError`.

## 4. Payments

- **R4.1** A payment is applied to the customer's open invoices, earliest due date first. Equal due dates go in invoice number order, with digit runs compared as numbers (`INV-2` before `INV-10`).
- **R4.2** On each invoice, late fees are paid before principal.
- **R4.3** Early-payment discount: granted when the payment is dated on or before the discount deadline, the invoice has no earlier payment on it, and the money reaching the invoice covers its balance less the discount. The discount is `p` percent of the invoice **net** (before tax), rounded to the cent. Otherwise no discount at all.
- **R4.4** Money left over becomes the customer's credit.
- **R4.5** Repeating a payment id with the same customer and amount changes nothing and returns the original payment. The same id with a different customer or amount raises `PaymentError`.
- **R4.6** The amount must be more than zero, otherwise `PaymentError`.
- **R4.7** Draft, void, paid and disputed invoices receive nothing.
- **R4.8** `reverse` undoes a payment completely: principal, late fees paid, any discount it earned and any credit it left. It logs one `reversal` event for the amount restored to the account (payment plus discounts). Reversing an unknown or already reversed payment raises `PaymentError`, and a reversed id cannot be received again.
- **R4.9** A payment cannot be reversed once the credit it left has been used; that raises `PaymentError` and changes nothing.
- **R4.10** `apply_credit` uses the customer's credit in the same order as a payment, never earns an early-payment discount, and logs no event.

## 5. Late fees

- **R5.1** No fee while an invoice is 5 days late or less. From day 6 the fee covers the whole time since the due date.
- **R5.2** One fee for each 30-day period **started** after the due date: days 6 to 30 late is one period, days 31 to 60 two.
- **R5.3** The fee per period is 1.5 percent of the principal still owed on the day it is assessed, rounded to the cent, and at least 5.00. Late fees never earn late fees.
- **R5.4** Late fees on one invoice never add up to more than 10 percent of the invoice total.
- **R5.5** Assessing twice charges each period once.
- **R5.6** A disputed invoice is charged nothing, and periods assessed while it was disputed stay waived after it is resolved.

## 6. Aging

- **R6.1** Open invoices go by days past due: `current` (0 or less), `1-30`, `31-60`, `61-90`, `91+`. The balance includes late fees.
- **R6.2** Disputed invoices go in `disputed` and nowhere else. Drafts, void and paid invoices are left out.
- **R6.3** The customer's credit reduces the **oldest** bucket first, never below zero, and never reduces `disputed`. Credit still left over shows as a negative amount in `current`.

## 7. Statements

- **R7.1** The period includes both its first and last day. The opening balance is everything before the first day.
- **R7.2** Lines are in date order. On one day: invoices, fees, payments, discounts, reversals, voids.
- **R7.3** Each line shows the running balance. The closing balance is the last one, or the opening balance when there are no lines.
- **R7.4** Amounts are signed: invoices, fees and reversals are positive; payments, discounts and voids are negative. Only the named customer's activity appears.

## 8. Bank import

- **R8.1** The header needs `date`, `reference`, `customer` and `amount`, in any order and any case, otherwise `ImportFormatError`. Extra columns are ignored. A leading byte order mark is ignored.
- **R8.2** A bad row is rejected with a reason and its line number in the file (the header is line 1 and blank lines count); the rest of the file is still read. Blank lines are neither accepted nor rejected.
- **R8.3** Reasons, first match wins: `missing_reference`, `missing_customer`, `bad_date`, `bad_amount`, `duplicate`.
- **R8.4** A row is a `duplicate` when an earlier row with the same reference, ignoring case, was **accepted**. A rejected row does not block a later good one.
- **R8.5** Dates are `YYYY-MM-DD` or `MM/DD/YYYY`.
- **R8.6** Amounts may have `$` and thousands commas and at most two decimals, and must be more than zero. Anything else, including negatives, parentheses and misplaced commas, is `bad_amount`.

## 9. Storage

- **R9.1** `load` after `save` gives back the same ledger: holidays, invoices, payments, credits and events, with exact amounts.
- **R9.2** `save(ledger, path, expected_version)` returns the new version. A new file expects version 0; each save adds 1. Any other expected version raises `ConflictError` and leaves the file alone.
- **R9.3** If a save fails part way, the existing file is untouched and no extra file is left in the folder.
- **R9.4** A file that is not JSON, or not schema 1, raises `StoreError`.
