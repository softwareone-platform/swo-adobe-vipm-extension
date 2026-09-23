import logging
from collections import Counter

from adobe_vipm.adobe.client import get_adobe_client
from adobe_vipm.adobe.errors import AdobeError
from adobe_vipm.adobe.mixins.errors import AdobeCreatePreviewError
from adobe_vipm.flows.constants import (
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
from adobe_vipm.flows.utils.renewal_lock import (
    get_pending_early_renewal,
    has_pending_staged_renewal,
)
from adobe_vipm.flows.utils.validation import is_renewal_order

logger = logging.getLogger(__name__)


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

    A native Change / Configuration / Termination order processed before the original
    anniversary would silently fork the already renewed term (see
    ``get_pending_early_renewal``).
    """

    def __call__(self, client, context, next_step):
        """Reject the order when an early renewal is pending effect for the agreement."""
        if is_renewal_order(context.order):
            next_step(client, context)
            return

        early_renewal = get_pending_early_renewal(context)
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


class ValidateNoStagedRenewal(Step):
    """
    Reject native orders while an at-anniversary renewal is staged for the agreement.

    A native Change / Configuration / Termination order placed before the anniversary
    would silently fork the staged renewal (see ``has_pending_staged_renewal``).
    """

    def __call__(self, client, context, next_step):
        """Reject the order when a renewal is staged and pending effect for the agreement."""
        if not is_renewal_order(context.order) and has_pending_staged_renewal(context):
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
        except (AdobeError, AdobeCreatePreviewError) as error:
            context.validation_succeeded = False
            context.order = set_order_error(
                context.order, ERR_ADOBE_ERROR.to_dict(details=str(error))
            )
            return

        next_step(mpt_client, context)
