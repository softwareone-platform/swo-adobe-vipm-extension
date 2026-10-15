# Renew-now renewals

This document describes the renew-now fulfilment flow
(`adobe_vipm/flows/fulfillment/renewal_now.py`). It covers change orders that
carry a `renewalPayload` ordering parameter with `renewalPath: "now"`. For the
at-anniversary path see `renewal.py`. For the surrounding layers and routing see
[architecture.md](architecture.md).

## Flow summary

The resulting renewing aggregate of the plan is first validated against the 3YC
committed minimum, then the renewing subscriptions — and any net-new items — are
validated with an Adobe `PREVIEW_RENEWAL` order and committed as an actual Adobe
`RENEWAL` order, invoiced immediately. After the commit, lapsing subscriptions
have their auto-renewal disabled, previous renewal lines are returned, the MPT
subscriptions for net-new items are created, renewed subscriptions have their
auto-renewal normalised, and the redeemed flex discount codes are recorded on the
AirTable redemptions table. None of the post-commit steps fails the MPT order (see
[Post-commit steps](#post-commit-steps)).

## Retries after the commit

A fulfilment attempt can stop with the MPT order still in Processing after the
`RENEWAL` was placed, for example when Adobe answers `OPEN` (1002) or a `RETURN`
is still pending, and the next attempt runs the pipeline from the top.
`DetectCommittedRenewal` runs right after `StartOrderProcessing` and looks up the
`RENEWAL` this MPT order placed (by its external reference id, the MPT order id).
Once Adobe holds it as `OPEN` or `COMPLETE` it is invoiced, so the checks that only
guard the commit are skipped (`SkipOnceRenewalCommitted`):

- the due date (`SetupDueDate`, `VIPM0025`);
- duplicated or existing items (`ValidateDuplicateLines`);
- the last 24 hours before the coterm date (`ValidateRenewalWindow`);
- the net-new order lines (`ValidateNetNewOrderLines`);
- the 3YC committed minimum (`Validate3YCRenewalFloor`, `VIPM0034`);
- the 14-day return window in `ResolvePreviousRenewalReturns` (`VIPM0053`): the
  `RETURN` candidates are still resolved and the seat check still applies, but the
  `RETURN` is submitted and Adobe decides whether it still accepts it.

These checks depend on today's date or on the agreement's current state, so on a
retry they could otherwise fail an order whose `RENEWAL` Adobe has already
invoiced. A `RENEWAL` Adobe failed was never invoiced and does not count as
committed: the checks still run. `PreviewRenewalNowOrder` and
`SubmitRenewalNowOrder` reuse the order found instead of querying Adobe again, and
`SubmitRenewalNowOrder` carries it forward even when the plan no longer yields a
line to submit (a renewing subscription's `renewedQuantity` is populated after the
commit, see `_is_already_renewed`).

## Post-commit steps

Once the `RENEWAL` is committed it is invoiced, so a Failed MPT order would only
hide what Adobe holds. The post-commit steps therefore never fail the MPT order.
They run in this order:

1. `DisableLapsingSubscriptions` — first, so nothing else can delay it: a lapsing
   subscription left enabled would renew a second time at the anniversary.
2. `ReturnPreviousRenewalOrders`.
3. `ResolveNetNewRenewedSubscriptions`, then `CreateNetNewMptSubscriptions` for the
   subscriptions resolved.
4. `NormalizeRenewedSubscriptions`.
5. `HoldOnOutstandingSteps`, then `CompleteOrder`.

A step that cannot complete records what is outstanding on the context and lets
the next step run; within a step, one subscription or line failing does not stop
the others. `HoldOnOutstandingSteps` then completes the order when nothing is
outstanding, and otherwise stops with the MPT order in Processing. The next
fulfilment attempt runs every step again: they are idempotent (existing `RETURN`s
are reused, the auto-renewal `PATCH`es are re-applied, net-new subscriptions are
re-resolved by line number), so the order completes once the outstanding step
succeeds. What is outstanding is told apart as follows:

| Outstanding | Examples | Operations notified |
| --- | --- | --- |
| Waiting | a `RETURN` still open | no |
| Transient Adobe error | transport error, timeout, Adobe 5xx | no |
| Refusal | Adobe 4xx on a `RETURN` or `PATCH`, a `RETURN` that ended failed, a committed net-new line missing or without `subscriptionId` | yes |

A refusal sends one Teams error (`notify_renewal_now_outstanding_steps`) naming
the MPT order, the Adobe orders it created (`adobeOrderIdsCreated`) and each
refused step with Adobe's message. The notification is cached, so the same
refusals of the same order are notified once per worker process although the
order is retried on every cycle; a worker restart notifies them again once.
Operations resolves the refusal in Adobe and the next attempt completes the
order. Once the `RENEWAL` is committed the due date no longer applies, so such an
order stays in Processing until then.

A plan with no line to commit (only lapsing subscriptions) runs the same
post-commit steps; with no `RENEWAL` committed the due date still applies to it.

## 3YC committed minimum floor (VIPM0034)

`Validate3YCRenewalFloor(include_net_new_items=True)`, shared with the
at-anniversary flow, runs **before** return resolution and before any Adobe
preview or commit operation. It projects the plan onto the customer's Adobe
subscriptions snapshotted by `SetupRenewalPlan` and validates the resulting
licenses and consumables aggregate with the same 3YC guard used by the other
order types. Net-new items are included in the projection because this flow
commits them on the same `RENEWAL` order (see [Net-new items](#net-new-items)).

The floor is enforced only for a 3YC renewal, that is a customer with a
`COMMITTED`/`ACTIVE` commitment that does not end before the coterm date;
otherwise the step is a no-op. A breach fails the MPT order with
`ERR_COMMITMENT_3YC_VALIDATION` (`VIPM0034`) and processing stops before any
mutation has been made in Adobe, so there is nothing to reverse. The check is
skipped on a retry once the `RENEWAL` is committed (see
[Retries after the commit](#retries-after-the-commit)).

## 14-day return window (VIPM0053)

A lapsing subscription (`renew = false`) whose pre-mutation snapshot carries a
`renewedQuantity` above 0 still holds early-renewed seats, possibly from several
`RENEWAL` orders of this term: Adobe keeps `renewedQuantity` as their running
total and lowers it as seats are returned (a `renewedQuantity` of 0 is a plain
lapse, with nothing to return). Those seats have to be returned, so the customer
is not left paying for a renewal that is being toggled off.

The `ResolvePreviousRenewalReturns` step walks the customer's `RENEWAL` orders
newest first, skips lines already fully returned (status 1008, or no
`remainingQuantity` left) and takes each remaining line's `remainingQuantity`
until the seats add up to what is still renewed, returning fewer from the last
line if that completes the total. Adobe only accepts a `RETURN` within
`CANCELLATION_WINDOW_DAYS` (14 days) of the original order placement, so every
line is checked against that window **before anything is committed**. Two
outcomes fail the MPT order at that point, while nothing has been mutated in
Adobe:

- the seats on the `RENEWAL` lines do not add up to the renewed quantity
  (including when no previous renewal order is found), which fails with
  `ERR_RENEWAL_RETURN_FAILED` (`VIPM0050`);
- a line to return was placed outside the 14-day window, which fails with
  `ERR_RENEWAL_RETURN_WINDOW_CLOSED` (`VIPM0053`).

Failing up front is deliberate. Committing the new `RENEWAL` first and only then
discovering that an old one cannot be returned would leave a committed and
invoiced Adobe order behind a Failed MPT order, with no way to reverse it.

After the commit, `ReturnPreviousRenewalOrders` creates one `RETURN` per line,
each for that line's resolved quantity, **one at a time**: the next `RETURN` is
placed only once the previous one has completed. Adobe lowers `renewedQuantity`
as each `RETURN` completes, and two `RETURN`s in flight together can lose one of
the decrements (sandbox, 29 Sep 2026: two placed 2 seconds apart left
`renewedQuantity` at 2 instead of 0, for good, so every later attempt failed the
seat check). A `RETURN` still open stops the sequence of `RETURN`s (the other
post-commit steps still run) and keeps the MPT order in Processing, and the next
fulfilment attempt carries on from there, so each hand-over re-reads the state
from Adobe and survives a restart. A removal of several early renewals therefore
takes one fulfilment attempt per `RETURN`. A `RETURN` Adobe refuses, or that ended
failed, stops the sequence the same way and is notified (see
[Post-commit steps](#post-commit-steps)).

`RETURN` orders created by an earlier attempt of the same MPT order are matched
to the `RENEWAL` order and line they reference, reused as-is whatever the window
says today, and their seats count towards the total, so retries neither return a
line twice nor fail the seat check. On a retry that finds this order's `RENEWAL`
already committed, the window is not checked for the `RETURN`s still to place
either (see [Retries after the commit](#retries-after-the-commit)).

## Flex discount codes committed

Only a discount code that the renewal plan **explicitly selected** for a line,
and that the `PREVIEW_RENEWAL` response then **confirmed** with result
`SUCCESS`, is submitted on the real `RENEWAL` order.

- A selected code the preview did not confirm fails the order **before** the
  `RENEWAL` is committed, with `VIPM0056` naming each refused code, its line and
  Adobe's result. Only an explicit `result: SUCCESS` confirms a code; a missing
  result or a missing `flexDiscounts` entry does not. The renew-now `RENEWAL` is
  invoiced immediately, so committing without the code would bill the renewal at
  full price. Lines are matched to the request by `extLineItemNumber`.
- Reusable discounts the customer already holds are auto-applied by Adobe at
  renewal without any opt-in. The preview reports them alongside the requested
  ones, but they are never echoed back on the commit, so they are not
  double-applied. An explicitly selected code takes precedence over them.
- Adobe accepts at most one code per line and rejects more with error `2147`, so
  a single surviving code is submitted per line.

The redemptions written to the AirTable table mirror this committed set:
`RecordDiscountRedemptions` records only the codes confirmed (result `SUCCESS`)
on the committed `RENEWAL` order, for both renewing and net-new lines. A
requested code the preview dropped is not recorded, so it does not wrongly
consume the customer's once-per-customer eligibility. (The at-anniversary flow
places no `RENEWAL` order and records its requested codes directly, since Adobe
validates them at subscription create/update time.)

## Net-new items

A net-new item (a product the customer does not yet hold) is submitted as an
additional line on the same immediate `RENEWAL` order, carrying `offerId` and
`quantity` and **no** `subscriptionId`: Adobe creates-and-renews the new
subscription in one shot and returns its assigned `subscriptionId` on the
committed order. Net-new lines are validated by the same `PREVIEW_RENEWAL` as the
renewing subscriptions and are numbered after them, so `extLineItemNumber` is the
join key from the plan item back to the committed line — the committed line's
`offerId` can differ from the ordered one across the renewal offer-type shift, so
it is not a safe key. After the order commits,
`ResolveNetNewRenewedSubscriptions` reads each new `subscriptionId` and
`CreateNetNewMptSubscriptions` (shared with the at-anniversary flow) creates the
corresponding MPT subscription. No separate Create Order is placed.

A net-new item may carry a single flexible discount code (`flexDiscountCodes`),
enforced (one code per line), preview-confirmed, and recorded on the AirTable
redemptions table exactly like a renewing line.
