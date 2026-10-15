# Partial returns

This document describes how Change Order downsizes are returned to Adobe using
partial quantity returns. The steps live in
`adobe_vipm/flows/fulfillment/downsize_returns.py` and
`adobe_vipm/flows/fulfillment/return_submission.py`. The I/O-free rules live in
`adobe_vipm/flows/utils/returns.py` and `adobe_vipm/flows/utils/return_errors.py`.
For the surrounding layers and routing see [architecture.md](architecture.md).

## Returnable pool

Adobe accepts a `RETURN` order for any quantity up to a NEW or RENEWAL line
item's `remainingQuantity`. That is the line quantity minus the returns and
mid-term switch plan cancellations placed against it. Several returns can be
placed against the same line.

`AdobeClient.get_returnable_orders_by_subscription_id` builds the pool of a
subscription from these orders:

- NEW and RENEWAL orders placed in the last 14 days, up to the customer's coterm
  date, completed, and on or after the latest RENEWAL order in that window;
- each line's returnable quantity is its `remainingQuantity`, and lines with
  nothing left are dropped. When Adobe omits the field, the line quantity is
  used and a warning is logged.

The pool is sorted oldest order first. The extension keeps no local ledger:
`remainingQuantity` is always read from Adobe.

## Per-line outcome

`PlanDownsizeReturns` resolves each downsize line on its own. The pool is
restricted to the order's deployment.

| Condition | Outcome |
|---|---|
| The MPT order already returned part of the line (previous run) | `RETURN` of the outstanding quantity |
| The pool covers the whole downsize and the offer is returnable | `RETURN` of the whole downsize, oldest order first |
| Otherwise (pool too small, consumables, no returnable order) | `DEFER`: nothing is returned; the renewal quantity is reduced |

A line is never split between a return and a deferral. A Change Order can
complete with some lines returned and others deferred. The draft validation
(`ValidateDownsizes`) runs the same planner and only logs the outcome, so it never
rejects a downsize.

## Submission

`SubmitReturnAllocations` runs `ReturnSubmission`:

1. **Confirm before committing.** Every planned allocation is checked against
   Adobe's current `remainingQuantity` (Get Order Details). Lines whose pool
   shrank are re-planned while nothing has been committed. A line with a
   pending RETURN keeps the order in Processing.
2. **Order by risk.** Lines whose allocation spans several source orders go
   first, then single-source lines. Deferred lines have their renewal quantity
   reduced last, by `UpdateRenewalQuantitiesDownsizes`.
3. **One RETURN at a time.** Each RETURN returns its allocated quantity with the
   external reference `{mptOrderId}_{sourceAdobeOrderId}_{line}` (35-character
   limit). It is recorded on `adobeOrderIds` as soon as it is created. A pending
   RETURN keeps the order in Processing. The next run computes the outstanding
   quantity from the RETURN orders the MPT order already placed, so retries never
   re-submit or over-return.

## Renewal quantity reconciliation

Adobe does not lower an explicit renewal quantity after a return. After every
completed RETURN, and before the next RETURN of a line that was already partly
returned, the subscription's renewal quantity is set to
`min(currentQuantity, renewalQuantity)`. It never exceeds the licences held and
never undoes an earlier deferred reduction. The line's target quantity is
written when the line completes. A subscription in its renewal window
(`3120 INVALID_RENEWAL_STATE`) is retried on the next run.

## Error handling

| Failure | Handling |
|---|---|
| Transport error, 5xx | Re-raised; the order stays in Processing and is retried |
| `RETURN_QTY_EXCEEDS_REMAINING`, or a RETURN ending `1004` | Re-plan the line once per run |
| Any other rejection (for example `RETURN_NOT_SUPPORTED_MOQ_SKU`) before the line is credited | The line is deferred |
| `RETURN_VIOLATES_3YC_MCQ` with nothing credited | Order fails with `VIPM0056` |
| Any rejection after part of the order was credited | Order fails with `VIPM0055` |

A failed order keeps the returns already made; no compensating order is
placed. The `VIPM0055` message lists every line as `RETURNED`, `PARTIAL`,
`NOT PROCESSED` or `DEFERRED` with its RETURN order ids. A Teams notification is
sent and the agreement is synced so MPT quantities match Adobe.

## Termination and renew-now

Termination Orders still require the whole subscription quantity to be
returnable (`VIPM0033`). They now return each line's `remainingQuantity`.
When a termination returns more than one order line, it places the RETURN
orders one at a time: the next RETURN is placed only after the previous one is
complete, and while one is open the order stays in Processing until the next
fulfilment attempt.
Renew-now returns the previous RENEWAL line's `remainingQuantity` and skips a
line with nothing left to return.
