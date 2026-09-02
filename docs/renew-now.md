# Renew-now renewals

This document describes the renew-now fulfilment flow
(`adobe_vipm/flows/fulfillment/renewal_now.py`). It covers change orders that
carry a `renewalPayload` ordering parameter with `renewalPath: "now"`. For the
at-anniversary path see `renewal.py`. For the surrounding layers and routing see
[architecture.md](architecture.md).

## Flow summary

The resulting renewing aggregate of the plan is first validated against the 3YC
committed minimum, then the renewing subscriptions are validated with an Adobe
`PREVIEW_RENEWAL` order and committed as an actual Adobe `RENEWAL` order,
invoiced immediately. After the commit, previous renewal lines are returned,
renewed subscriptions have their auto-renewal normalised, lapsing subscriptions
have their auto-renewal disabled, and the redeemed flex discount codes are
recorded on the AirTable redemptions table.

## 3YC committed minimum floor (VIPM0034)

`Validate3YCRenewalFloor(include_net_new_items=False)`, shared with the
at-anniversary flow, runs **before** return resolution and before any Adobe
preview or commit operation. It projects the plan onto the customer's Adobe
subscriptions snapshotted by `SetupRenewalPlan` and validates the resulting
licenses and consumables aggregate with the same 3YC guard used by the other
order types. Net-new items are excluded here because this flow does not create
them.

The floor is enforced only for a 3YC renewal, that is a customer with a
`COMMITTED`/`ACTIVE` commitment that does not end before the coterm date;
otherwise the step is a no-op. A breach fails the MPT order with
`ERR_COMMITMENT_3YC_VALIDATION` (`VIPM0034`) and processing stops before any
mutation has been made in Adobe, so there is nothing to reverse.

## 14-day return window (VIPM0053)

A lapsing subscription (`renew = false`) whose pre-mutation snapshot carries a
`renewedQuantity` was already committed in a previous `RENEWAL` order. That
order's line has to be returned, so the customer is not left paying for a
renewal that is being toggled off.

Adobe only accepts a `RETURN` within `CANCELLATION_WINDOW_DAYS` (14 days) of the
original order placement. The `ResolvePreviousRenewalReturns` step therefore
locates the previous renewal line and checks its creation date against that
window **before anything is committed**. Two outcomes fail the MPT order at that
point, while nothing has been mutated in Adobe:

- the previous renewal order cannot be found, which fails with
  `ERR_RENEWAL_RETURN_FAILED` (`VIPM0050`);
- the previous renewal order was placed outside the 14-day window, which fails
  with `ERR_RENEWAL_RETURN_WINDOW_CLOSED` (`VIPM0053`).

Failing up front is deliberate. Committing the new `RENEWAL` first and only then
discovering that the old one cannot be returned would leave a committed and
invoiced Adobe order behind a Failed MPT order, with no way to reverse it.

A `RETURN` order created by an earlier attempt of the same MPT order is detected
by its external reference prefix and reused as-is, whatever the window says
today, so retries stay idempotent.

## Flex discount codes committed

Only a discount code that the renewal plan **explicitly selected** for a line,
and that the `PREVIEW_RENEWAL` response then **confirmed** with result
`SUCCESS`, is submitted on the real `RENEWAL` order.

- Requested codes the preview did not apply successfully are dropped and logged.
- Reusable discounts the customer already holds are auto-applied by Adobe at
  renewal without any opt-in. The preview reports them alongside the requested
  ones, but they are never echoed back on the commit, so they are not
  double-applied. An explicitly selected code takes precedence over them.
- Adobe accepts at most one code per line and rejects more with error `2147`, so
  a single surviving code is submitted per line.

## Known limitations

Net-new items are not handled by this flow yet.
