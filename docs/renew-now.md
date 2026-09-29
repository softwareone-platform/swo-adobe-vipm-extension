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
`RENEWAL` order, invoiced immediately. After the commit, previous renewal lines
are returned, the MPT subscriptions for net-new items are created, renewed
subscriptions have their auto-renewal normalised, lapsing subscriptions have
their auto-renewal disabled, and the MPT order is completed. After completion,
the redeemed flex discount codes are persisted to the Airtable Discount Codes
table (`RecordClientDiscountCodes`, first-successful-use backfill for previously
unknown codes) and recorded on the Airtable Discount Redemptions table
(`RecordDiscountRedemptions`).

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
mutation has been made in Adobe, so there is nothing to reverse.

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
seat check). A `RETURN` still open stops the pipeline with the MPT order in
Processing, and the next fulfilment attempt carries on from there, so each
hand-over re-reads the state from Adobe and survives a restart. A removal of
several early renewals therefore takes one fulfilment attempt per `RETURN`.

`RETURN` orders created by an earlier attempt of the same MPT order are matched
to the `RENEWAL` order and line they reference, reused as-is whatever the window
says today, and their seats count towards the total, so retries neither return a
line twice nor fail the seat check.

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

## Discount code persistence and redemption tracking

After the order completes, two steps run to persist discount code data to
Airtable (both are best-effort: failures are logged and notified, not failed,
since the order is already completed):

1. **`RecordClientDiscountCodes`** (runs first, before redemption recording): For
   each discount code the order successfully redeemed, checks whether it already
   exists in the Airtable Discount Codes table. Previously unknown codes (typed
   by the client in the renewal wizard, not pre-loaded from the store) are
   fetched from Adobe by code (`get_flex_discounts_by_code`) and written to the
   table with source "Client", so they become available for future orders. This
   first-successful-use backfill ensures that redemption rows always point at a
   known code.

2. **`RecordDiscountRedemptions`** (runs second, after the codes are persisted):
   Records only the codes confirmed (result `SUCCESS`) on the committed `RENEWAL`
   order, for both renewing and net-new lines. A requested code the preview
   dropped is not recorded, so it does not wrongly consume the customer's
   once-per-customer eligibility. Each unique code redeemed by the order gets one
   row on the Discount Redemptions table, carrying the customer ID, order ID, and
   redemption timestamp. A code the subscription already held before this order
   (inherited, auto-applied reusable discount) is not recorded as a fresh
   redemption.

Note: The at-anniversary flow (`renewal.py`, `fulfill_renewal_order`) also runs
these same two steps after completing its order. That flow places no `RENEWAL`
order (its codes ride `create_customer_subscription` / `update_subscription`,
which Adobe validates on the spot), so its requested codes are the applied ones
and no committed-order confirmation filter applies.

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
