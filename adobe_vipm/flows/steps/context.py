import datetime as dt
import logging

from django.conf import settings
from mpt_extension_sdk.mpt_http.mpt import (
    get_agreement,
    get_licensee,
)

from adobe_vipm.adobe.client import get_adobe_client
from adobe_vipm.adobe.errors import AdobeAPIError
from adobe_vipm.airtable.models import get_transfer_by_authorization_membership_or_customer
from adobe_vipm.flows.fulfillment.transfer import get_agreement_deployments, get_main_agreement
from adobe_vipm.flows.pipeline import Step
from adobe_vipm.flows.utils.customer import get_adobe_customer_id, get_customer_data
from adobe_vipm.flows.utils.date import get_due_date
from adobe_vipm.flows.utils.market_segment import get_market_segment
from adobe_vipm.flows.utils.order import (
    get_adobe_order_id,
    reset_order_error,
    split_downsizes_upsizes_new,
)
from adobe_vipm.flows.utils.parameter import (
    get_adobe_membership_id,
    get_retry_count,
    reset_ordering_parameters_error,
)
from adobe_vipm.flows.utils.validation import is_migrate_customer

logger = logging.getLogger(__name__)


class SetupContext(Step):
    """
    Initialize the processing context.

    Enrich the order with the full representations of the agreement and the licensee
    retrieving them.
    If the Adobe customerId fulfillment parameter is set, then retrieve the customer
    object from adobe and set it.
    """

    def __call__(self, client, context, next_step):
        """Initialize the processing context."""
        adobe_client = get_adobe_client()
        context.order = reset_order_error(context.order)
        context.order = reset_ordering_parameters_error(context.order)
        context.order["agreement"] = get_agreement(client, context.order["agreement"]["id"])
        context.order["agreement"]["licensee"] = get_licensee(
            client, context.order["agreement"]["licensee"]["id"]
        )
        context.downsize_lines, context.upsize_lines, context.new_lines = (
            split_downsizes_upsizes_new(
                context.order,
            )
        )

        retry_count = get_retry_count(context.order)
        if retry_count and int(retry_count) > 0:
            # when due date parameter is created and new code to process it
            # is released, it may happen
            # that there are order in processing, that don't have
            # due date parameter. If such orders were processed at least once
            # means retry_count is set and it is > 0
            # just setup due date to not to send email, like new order was
            # created
            context.due_date = dt.datetime.now(tz=dt.UTC).date() + dt.timedelta(
                days=int(settings.EXTENSION_CONFIG.get("DUE_DATE_DAYS"))
            )
        else:
            # usual due date processing for new orders
            # or when order was in processing when due date parameter
            # was added, but extension didn't try to process it still
            # means process it like usual order and send email notification
            context.due_date = get_due_date(context.order)

        context.order_id = context.order["id"]
        context.type = context.order["type"]
        context.agreement_id = context.order["agreement"]["id"]
        context.authorization_id = context.order["authorization"]["id"]
        context.product_id = context.order["agreement"]["product"]["id"]
        context.seller_id = context.order["agreement"]["seller"]["id"]
        context.currency = context.order["agreement"]["listing"]["priceList"]["currency"]
        context.customer_data = get_customer_data(context.order)
        context.market_segment = get_market_segment(context.product_id)
        context.adobe_customer_id = get_adobe_customer_id(context.order)
        if context.adobe_customer_id:
            try:
                context.adobe_customer = adobe_client.get_customer(
                    context.authorization_id,
                    context.adobe_customer_id,
                )
            except AdobeAPIError:
                logger.exception("%s: failed to retrieve Adobe customer.", context)
                return
        context.adobe_new_order_id = get_adobe_order_id(context.order)
        logger.info("%s: initialization completed.", context)
        next_step(client, context)


class SetupTransferOrderContext(Step):
    """Sets up the initial context for transfer order processing."""

    def __call__(self, client, context, next_step):
        """Sets up the initial context for transfer order processing."""
        context.membership_id = get_adobe_membership_id(context.order)
        context.customer_deployments = None

        context.transfer = get_transfer_by_authorization_membership_or_customer(
            context.product_id,
            context.authorization_id,
            context.membership_id,
        )

        context.gc_main_agreement = get_main_agreement(
            context.product_id,
            context.authorization_id,
            context.membership_id,
        )

        context.existing_deployments = get_agreement_deployments(
            context.product_id, context.order.get("agreement", {}).get("id", "")
        )

        next_step(client, context)


class SetupTransferContext(Step):
    """Setups Transfer context."""

    def __call__(self, mpt_client, context, next_step):
        """Setups Transfer context."""
        context.validation_succeeded = True
        context.order["agreement"] = get_agreement(mpt_client, context.order["agreement"]["id"])

        product_id = context.order["agreement"]["product"]["id"]
        authorization_id = context.order["authorization"]["id"]
        context.membership_id = get_adobe_membership_id(context.order)

        if is_migrate_customer(context.order):
            context.transfer = get_transfer_by_authorization_membership_or_customer(
                product_id,
                authorization_id,
                context.membership_id,
            )
        next_step(mpt_client, context)
