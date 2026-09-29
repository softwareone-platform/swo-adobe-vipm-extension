"""
Whether a renewal is in place for the agreement, so orders must not fork it.

An early renewal pending effect or an at-anniversary renewal staged for the
anniversary locks the agreement: native Change, Configuration and Termination
orders are refused at validation, and mid-term upgrade (SWITCH) orders at
fulfilment, from the same two reads.
"""

import datetime as dt

from adobe_vipm.adobe.client import get_adobe_client
from adobe_vipm.adobe.constants import (
    ORDER_TYPE_RENEWAL,
    AdobeOrderStatus,
    AdobeSubscriptionStatus,
)
from adobe_vipm.flows.constants import EARLY_RENEWAL_LOOKBACK_DAYS

LAST_DAY_OF_FEBRUARY_NON_LEAP = 28


def get_pending_early_renewal(context):
    """
    Return the early renewal placed for the agreement that is still pending effect, if any.

    An early ("renew now") renewal commits an Adobe RENEWAL order before the
    anniversary date and rolls the customer cotermDate forward immediately. Such an
    order is recognized because it was created strictly before the anniversary of
    the term it renews (the current cotermDate minus one year): the RENEWAL orders
    Adobe itself generates at the anniversary are created on that very day, and the
    late/manual ones after it. An OPEN RENEWAL order counts too: the commit is in
    flight and the cotermDate has not rolled forward yet.
    """
    coterm_date = (context.adobe_customer or {}).get("cotermDate")
    if not context.adobe_customer_id or not coterm_date:
        return None
    anniversary = _previous_anniversary(dt.date.fromisoformat(coterm_date))
    today = dt.datetime.now(tz=dt.UTC).date()
    renewal_orders = get_adobe_client().get_orders(
        context.authorization_id,
        context.adobe_customer_id,
        filters={"order-type": ORDER_TYPE_RENEWAL},
    )
    return next(
        (order for order in renewal_orders if _is_pending_early_renewal(order, anniversary, today)),
        None,
    )


def has_pending_staged_renewal(context):
    """
    Return whether an at-anniversary renewal is staged for the agreement and pending effect.

    An at-anniversary ("renew at anniversary") renewal completes its MPT order
    immediately but places no Adobe order: the plan is applied to Adobe as deferred
    auto-renewal preferences that only take effect at the coterm date. It therefore
    leaves no Adobe RENEWAL order for ``get_pending_early_renewal`` to detect.

    The staged state is instead derived live from the customer's Adobe subscriptions,
    which carry the deferred effect: a net-new item staged for the renewal appears as
    a SCHEDULED subscription, and a staged quantity increase appears as an existing
    subscription whose ``autoRenewal.renewalQuantity`` exceeds its ``currentQuantity``.
    Only staged upsizes and additions are treated as blocking: a staged downsize
    (``renewalQuantity`` below ``currentQuantity``) is the ordinary renewal-reduction
    mechanism and does not lock native orders. The divergence self-clears once the
    renewal takes effect at the anniversary, lifting the block without any bookkeeping.

    Only live subscriptions can carry a pending renewal, so the derivation ignores
    every subscription that is not ACTIVE for the upsize signal: an INACTIVE (expired
    or transferred-in) subscription keeps stale ``renewalQuantity`` values that never
    describe a pending renewal. A SCHEDULED net-new subscription blocks only while it
    is still armed (``autoRenewal.enabled``); the renewal rollback path neutralises a
    scheduled subscription by disabling its auto-renewal instead of deleting it, and a
    neutralised subscription will never activate, so it must not lock native orders.
    """
    coterm_date = (context.adobe_customer or {}).get("cotermDate")
    if not context.adobe_customer_id or not coterm_date:
        return False
    today = dt.datetime.now(tz=dt.UTC).date()
    if today > dt.date.fromisoformat(coterm_date):
        return False
    subscriptions = get_adobe_client().get_subscriptions(
        context.authorization_id,
        context.adobe_customer_id,
    )
    return any(
        _subscription_stages_renewal(subscription)
        for subscription in subscriptions.get("items", [])
    )


def _is_pending_early_renewal(order, anniversary, today):
    created_at = dt.datetime.fromisoformat(order["creationDate"])
    creation_date = created_at.replace(tzinfo=dt.UTC).date()
    if creation_date < today - dt.timedelta(days=EARLY_RENEWAL_LOOKBACK_DAYS):
        return False
    if order["status"] == AdobeOrderStatus.OPEN:
        return True
    return (
        order["status"] == AdobeOrderStatus.COMPLETE
        and creation_date < anniversary
        and today <= anniversary
    )


def _previous_anniversary(coterm_date):
    try:
        return coterm_date.replace(year=coterm_date.year - 1)
    except ValueError:  # Feb 29 on a non-leap target year
        return coterm_date.replace(year=coterm_date.year - 1, day=LAST_DAY_OF_FEBRUARY_NON_LEAP)


def _subscription_stages_renewal(subscription):
    status = subscription.get("status")
    auto_renewal = subscription.get("autoRenewal") or {}
    if status == AdobeSubscriptionStatus.SCHEDULED:
        # A neutralised (rolled-back) scheduled subscription keeps its SCHEDULED
        # status but will not activate, so it does not lock native orders.
        return bool(auto_renewal.get("enabled"))
    if status != AdobeSubscriptionStatus.ACTIVE:
        # Only a live subscription can carry a pending renewal; INACTIVE rows keep
        # stale renewalQuantity values that never describe a real renewal.
        return False
    renewal_quantity = auto_renewal.get("renewalQuantity")
    current_quantity = subscription.get("currentQuantity")
    return (
        renewal_quantity is not None
        and current_quantity is not None
        and renewal_quantity > current_quantity
    )
