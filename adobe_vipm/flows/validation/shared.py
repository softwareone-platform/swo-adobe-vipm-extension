import datetime as dt
import logging
from collections import Counter

from adobe_vipm.adobe.client import get_adobe_client
from adobe_vipm.adobe.constants import (
    ORDER_TYPE_RENEWAL,
    AdobeOrderStatus,
    AdobeSubscriptionStatus,
)
from adobe_vipm.adobe.errors import AdobeAPIError, AdobeProductNotFoundError
from adobe_vipm.adobe.mixins.errors import AdobeCreatePreviewError
from adobe_vipm.flows.constants import (
    EARLY_RENEWAL_LOOKBACK_DAYS,
    ERR_ADOBE_ERROR,
    ERR_DUPLICATED_ITEMS,
    ERR_EARLY_RENEWAL_IN_PROGRESS,
    ERR_EXISTING_ITEMS,
    ERR_RENEWAL_STAGED,
)
from adobe_vipm.flows.pipeline import Step
from adobe_vipm.flows.utils import (
    set_order_error,
)
from adobe_vipm.flows.utils.validation import is_renewal_order

logger = logging.getLogger(__name__)

LAST_DAY_OF_FEBRUARY_NON_LEAP = 28


class ValidateDuplicateLines(Step):
    """
    Validates if there are duplicated lines.

    Lines with the same item ID within this order or new lines that are not duplicated
    within this order but that have already a subscription.
    """

    def __call__(self, client, context, next_step):
        """Validates if there are duplicated lines."""
        if not context.order["lines"]:
            next_step(client, context)
            return

        items = [line["item"]["id"] for line in context.order["lines"]]
        duplicates = [item for item, count in Counter(items).items() if count > 1]
        if duplicates:
            message = ERR_DUPLICATED_ITEMS.to_dict(duplicates=",".join(duplicates))
            context.order = set_order_error(context.order, message)
            logger.info("%s: %s", context, message)
            context.validation_succeeded = False
            return

        items = []
        for subscription in context.order["agreement"]["subscriptions"]:
            for line in subscription["lines"]:
                items.append(line["item"]["id"])

        items.extend([
            line["item"]["id"] for line in context.order["lines"] if line["oldQuantity"] == 0
        ])
        duplicates = [item for item, count in Counter(items).items() if count > 1]
        if duplicates:
            message = ERR_EXISTING_ITEMS.to_dict(duplicates=",".join(duplicates))
            context.order = set_order_error(
                context.order,
                message,
            )
            logger.info("%s: %s", context, message)
            context.validation_succeeded = False
            return
        next_step(client, context)


class ValidateNoEarlyRenewal(Step):
    """
    Reject native orders while an early renewal placed for the agreement is pending effect.

    An early ("renew now") renewal commits an Adobe RENEWAL order before the
    anniversary date and rolls the customer cotermDate forward immediately, so
    a native Change / Configuration / Termination order processed before the
    original anniversary would silently fork the already renewed term. Such an
    order is recognized because it was created strictly before the anniversary
    of the term it renews (the current cotermDate minus one year): the RENEWAL
    orders Adobe itself generates at the anniversary are created on that very
    day, and the late/manual ones after it. An OPEN RENEWAL order blocks too:
    the commit is in flight and the cotermDate has not rolled forward yet.
    """

    def __call__(self, client, context, next_step):
        """Reject the order when an early renewal is pending effect for the agreement."""
        if is_renewal_order(context.order):
            next_step(client, context)
            return

        coterm_date = (context.adobe_customer or {}).get("cotermDate")
        if not context.adobe_customer_id or not coterm_date:
            next_step(client, context)
            return

        early_renewal = self._get_pending_early_renewal(context, dt.date.fromisoformat(coterm_date))
        if early_renewal:
            logger.info(
                "%s: the early renewal order %s placed on %s is pending effect",
                context,
                early_renewal["orderId"],
                early_renewal["creationDate"],
            )
            context.validation_succeeded = False
            context.order = set_order_error(
                context.order,
                ERR_EARLY_RENEWAL_IN_PROGRESS.to_dict(),
            )
            return

        next_step(client, context)

    def _get_pending_early_renewal(self, context, coterm_date):
        anniversary = self._previous_anniversary(coterm_date)
        today = dt.datetime.now(tz=dt.UTC).date()
        adobe_client = get_adobe_client()
        renewal_orders = adobe_client.get_orders(
            context.authorization_id,
            context.adobe_customer_id,
            filters={"order-type": ORDER_TYPE_RENEWAL},
        )
        for order in renewal_orders:
            creation_date = (
                dt.datetime.fromisoformat(order["creationDate"]).replace(tzinfo=dt.UTC).date()
            )
            if creation_date < today - dt.timedelta(days=EARLY_RENEWAL_LOOKBACK_DAYS):
                continue
            if order["status"] == AdobeOrderStatus.OPEN:
                return order
            is_pending_early_renewal = (
                order["status"] == AdobeOrderStatus.COMPLETE
                and creation_date < anniversary
                and today <= anniversary
            )
            if is_pending_early_renewal:
                return order
        return None

    def _previous_anniversary(self, coterm_date):
        try:
            return coterm_date.replace(year=coterm_date.year - 1)
        except ValueError:  # Feb 29 on a non-leap target year
            return coterm_date.replace(year=coterm_date.year - 1, day=LAST_DAY_OF_FEBRUARY_NON_LEAP)


class ValidateNoStagedRenewal(Step):
    """
    Reject native orders while an at-anniversary renewal is staged for the agreement.

    An at-anniversary ("renew at anniversary") renewal completes its MPT order
    immediately but places no Adobe order: the plan is applied to Adobe as deferred
    auto-renewal preferences that only take effect at the coterm date. It therefore
    leaves no Adobe RENEWAL order for ``ValidateNoEarlyRenewal`` to detect, so a
    native Change / Configuration / Termination order placed before the anniversary
    would silently fork the staged renewal.

    The staged state is instead derived live from the customer's Adobe subscriptions,
    which carry the deferred effect: a net-new item staged for the renewal appears as
    a SCHEDULED subscription, and a staged quantity increase appears as an existing
    subscription whose ``autoRenewal.renewalQuantity`` exceeds its ``currentQuantity``.
    Only staged upsizes and additions are treated as blocking: a staged downsize
    (``renewalQuantity`` below ``currentQuantity``) is the ordinary renewal-reduction
    mechanism and does not lock native orders. The divergence self-clears once the
    renewal takes effect at the anniversary, lifting the block without any bookkeeping.
    """

    def __call__(self, client, context, next_step):
        """Reject the order when a renewal is staged and pending effect for the agreement."""
        if self._is_staged_renewal_pending(context):
            logger.info(
                "%s: a renewal is staged and pending effect for the agreement",
                context,
            )
            context.validation_succeeded = False
            context.order = set_order_error(
                context.order,
                ERR_RENEWAL_STAGED.to_dict(),
            )
            return

        next_step(client, context)

    def _is_staged_renewal_pending(self, context):
        if is_renewal_order(context.order):
            return False

        coterm_date = (context.adobe_customer or {}).get("cotermDate")
        if not context.adobe_customer_id or not coterm_date:
            return False

        if dt.datetime.now(tz=dt.UTC).date() > dt.date.fromisoformat(coterm_date):
            return False

        return self._has_staged_renewal(context)

    def _has_staged_renewal(self, context):
        adobe_client = get_adobe_client()
        subscriptions = adobe_client.get_subscriptions(
            context.authorization_id,
            context.adobe_customer_id,
        )
        for subscription in subscriptions.get("items", []):
            if subscription.get("status") == AdobeSubscriptionStatus.SCHEDULED:
                return True
            auto_renewal = subscription.get("autoRenewal") or {}
            renewal_quantity = auto_renewal.get("renewalQuantity")
            current_quantity = subscription.get("currentQuantity")
            if (
                renewal_quantity is not None
                and current_quantity is not None
                and renewal_quantity > current_quantity
            ):
                return True
        return False


class GetPreviewOrder(Step):
    """
    Retrieve a preview order for the upsize/new lines.

    If there are incompatible SKUs within the PREVIEW order an error will be thrown by the
    Adobe API the draft validation fails, otherwise the draft order validation
    pipeline will continue.
    """

    def __call__(self, mpt_client, context, next_step):
        """Retrieve a preview order for the upsize/new lines."""
        if not (context.upsize_lines or context.new_lines):
            next_step(mpt_client, context)
            return

        adobe_client = get_adobe_client()
        try:
            context.adobe_preview_order = adobe_client.create_preview_order(context)
        except (AdobeAPIError, AdobeProductNotFoundError, AdobeCreatePreviewError) as error:
            context.validation_succeeded = False
            context.order = set_order_error(
                context.order, ERR_ADOBE_ERROR.to_dict(details=str(error))
            )
            return

        next_step(mpt_client, context)
