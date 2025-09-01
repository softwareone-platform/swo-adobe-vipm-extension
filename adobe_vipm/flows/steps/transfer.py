import datetime as dt
import logging

from adobe_vipm.adobe.client import get_adobe_client
from adobe_vipm.adobe.constants import AdobeStatus, ThreeYearCommitmentStatus
from adobe_vipm.adobe.errors import AdobeError
from adobe_vipm.airtable.models import (
    create_gc_agreement_deployments,
)
from adobe_vipm.flows.constants import (
    ERR_ADOBE_MEMBERSHIP_PROCESSING,
    ERR_UNEXPECTED_ADOBE_ERROR_STATUS,
    ERR_UPDATING_TRANSFER_ITEMS,
    TEMPLATE_NAME_BULK_MIGRATE,
    TEMPLATE_NAME_TRANSFER,
    Param,
)
from adobe_vipm.flows.fulfillment.shared import (
    add_subscription,
    check_processing_template,
    handle_retries,
    save_coterm_dates,
    switch_order_to_completed,
    switch_order_to_failed,
)
from adobe_vipm.flows.fulfillment.transfer import (
    add_gc_main_agreement,
    create_agreement_subscriptions,
    get_new_agreement_deployments,
    send_gc_agreement_deployments_notification,
    sync_main_agreement,
)
from adobe_vipm.flows.pipeline import Step
from adobe_vipm.flows.sync import sync_agreements_by_agreement_ids
from adobe_vipm.flows.utils.deployment import (
    exclude_items_with_deployment_id,
    exclude_subscriptions_with_deployment_id,
)
from adobe_vipm.flows.utils.order import (
    has_order_line_updated,
    save_adobe_order_id_and_customer_data,
    validate_transfer_not_migrated,
)
from adobe_vipm.flows.utils.parameter import set_ordering_parameter_error
from adobe_vipm.flows.utils.subscription import (
    is_transferring_item_expired,
)
from adobe_vipm.utils import get_partial_sku

logger = logging.getLogger(__name__)


def _check_adobe_transfer_order_fulfilled(mpt_client, order, membership_id, adobe_transfer_id):
    """
    Checks the fulfillment status of an Adobe transfer order.

    Args:
        mpt_client (MPTClient): An instance of the Marketplace platform client.
        order (dict): The MPT order being processed.
        membership_id (str): The Adobe membership ID associated with the transfer.
        adobe_transfer_id (str): The Adobe transfer order ID.

    Returns:
        dict or None: The Adobe transfer order if fulfilled, None otherwise.
    """
    adobe_client = get_adobe_client()
    authorization_id = order["authorization"]["id"]
    adobe_order = adobe_client.get_transfer(
        authorization_id,
        membership_id,
        adobe_transfer_id,
    )
    if adobe_order["status"] == AdobeStatus.PENDING:
        handle_retries(mpt_client, order, adobe_transfer_id)
        return None
    if adobe_order["status"] != AdobeStatus.PROCESSED:
        error = ERR_UNEXPECTED_ADOBE_ERROR_STATUS.to_dict(status=adobe_order["status"])
        switch_order_to_failed(mpt_client, order, error)
        logger.warning("Transfer %s has been failed: %s.", order["id"], error["message"])
        return None
    return adobe_order


def check_agreement_deployments(
    adobe_client,
    customer,
    adobe_transfer_order,
    existing_deployments,
    order,
    gc_main_agreement,
    customer_deployments,
):
    """
    Checks if the customer deployments are synchronized and the main agreement exists in Airtable.

    Args:
        adobe_client (AdobeClient): An instance of the Adobe client.
        customer (dict): The Adobe customer.
        adobe_transfer_order (dict): The Adobe transfer order.
        existing_deployments (list): The existing deployments in Airtable.
        order (dict): The MPT order to be fulfilled.
        gc_main_agreement (GCMainAgreement): The main agreement in Airtable.
        customer_deployments (list): The Adobe customer deployments.

    Returns:
        bool: True if the customer deployments are synchronized and the main agreement
        exists in Airtable, False otherwise.
    """
    product_id = order["agreement"]["product"]["id"]
    if customer.get("globalSalesEnabled", False):
        logger.info(
            "Adobe customer has global sales enabled, proceed to get the customer deployments"
        )
        if not gc_main_agreement:
            add_gc_main_agreement(order, adobe_transfer_order)

        if not customer_deployments:
            customer_deployments = adobe_client.get_customer_deployments_active_status(
                order["authorization"]["id"], adobe_transfer_order["customerId"]
            )
        if len(customer_deployments) > 0:
            logger.info(
                "Adobe customer have %s deployments,"
                " proceed to add agreement deployments to Airtable",
                len(customer_deployments),
            )
            new_agreement_deployments = get_new_agreement_deployments(
                existing_deployments,
                customer_deployments,
                adobe_transfer_order,
                product_id,
                order,
            )
            if new_agreement_deployments:
                create_gc_agreement_deployments(product_id, new_agreement_deployments)
                send_gc_agreement_deployments_notification(
                    order.get("agreement", {}).get("id", ""),
                    adobe_transfer_order.get("customerId", ""),
                    customer_deployments,
                    product_id,
                )
                return False

        else:
            logger.info(
                "Adobe customer doesn't have deployments, proceed to fulfill the transfer order"
            )
    return True


def _fulfill_transfer_migrated(  # noqa: C901
    adobe_client,
    mpt_client,
    order,
    transfer,
    one_time_skus,
    gc_main_agreement,
    adobe_subscriptions,
):
    authorization_id = order["authorization"]["id"]

    # remove expired items from adobe items
    adobe_items = [
        item
        for item in adobe_subscriptions["items"]
        if not is_transferring_item_expired(item)
        and get_partial_sku(item["offerId"]) not in one_time_skus
    ]
    # If the order items has been updated, the validation order will fail
    if has_order_line_updated(order["lines"], adobe_items, Param.CURRENT_QUANTITY.value):
        logger.error(ERR_UPDATING_TRANSFER_ITEMS.message)
        switch_order_to_failed(mpt_client, order, ERR_UPDATING_TRANSFER_ITEMS.to_dict())
        return

    commitment_date = None
    if not adobe_items:
        error = "No subscriptions found without deployment ID to be added to the main agreement"
        logger.error(error)
        sync_main_agreement(
            gc_main_agreement,
            order["agreement"]["product"]["id"],
            authorization_id,
            transfer.customer_id,
            error,
        )
        return
    for line in adobe_items:
        adobe_subscription = adobe_client.get_subscription(
            authorization_id,
            transfer.customer_id,
            line["subscriptionId"],
        )
        if adobe_subscription["status"] != AdobeStatus.PROCESSED:
            logger.warning(
                "Subscription %s for customer %s is in status %s, skip it",
                adobe_subscription["subscriptionId"],
                transfer.customer_id,
                adobe_subscription["status"],
            )
            continue

        if transfer.customer_benefits_3yc_status != ThreeYearCommitmentStatus.COMMITTED:
            adobe_subscription = adobe_client.update_subscription(
                authorization_id,
                transfer.customer_id,
                line["subscriptionId"],
                auto_renewal=True,
            )
        subscription = add_subscription(mpt_client, adobe_subscription, order, line)
        if subscription and not commitment_date:  # pragma: no branch
            # subscription are cotermed so it's ok to take the first created
            commitment_date = subscription["commitmentDate"]

    if commitment_date:  # pragma: no branch
        order = save_coterm_dates(mpt_client, order, commitment_date)

    # Fulfills order with active items
    customer = adobe_client.get_customer(authorization_id, transfer.customer_id)
    order = save_adobe_order_id_and_customer_data(
        mpt_client,
        order,
        transfer.transfer_id,
        customer,
    )

    switch_order_to_completed(mpt_client, order, TEMPLATE_NAME_BULK_MIGRATE)
    transfer.status = "synchronized"
    transfer.mpt_order_id = order["id"]
    transfer.synchronized_at = dt.datetime.now(tz=dt.UTC)
    transfer.save()
    sync_main_agreement(
        gc_main_agreement,
        order["agreement"]["product"]["id"],
        authorization_id,
        transfer.customer_id,
    )


class CheckTransferTemplate(Step):
    """Checks the processing template for transfer orders."""

    def __call__(self, client, context, next_step):
        """Checks the processing template for transfer orders."""
        check_processing_template(client, context.order, TEMPLATE_NAME_TRANSFER)
        next_step(client, context)


class CheckAdobeTransferOrder(Step):
    """Checks if the Adobe transfer order has been fulfilled."""

    def __call__(self, client, context, next_step):
        """Checks if the Adobe transfer order has been fulfilled."""
        context.adobe_transfer_order = _check_adobe_transfer_order_fulfilled(
            client, context.order, context.membership_id, context.adobe_order_id
        )
        if not context.adobe_transfer_order:
            return

        next_step(client, context)


class ProcessTransferOrder(Step):
    """Processes the transfer order by excluding deployment items and saving customer data."""

    def __call__(self, client, context, next_step):
        """Updates order id and customer data to MPT order."""
        context.adobe_transfer_order = exclude_items_with_deployment_id(
            context.adobe_transfer_order
        )
        context.order = save_adobe_order_id_and_customer_data(
            client,
            context.order,
            context.adobe_order_id,
            context.adobe_customer,
        )
        next_step(client, context)


class CreateTransferSubscriptions(Step):
    """Creates subscriptions for the transfer order."""

    def __call__(self, client, context, next_step):
        """Create transfer subscriptions."""
        adobe_client = get_adobe_client()

        context.subscriptions = create_agreement_subscriptions(
            context.adobe_transfer_order,
            client,
            context.order,
            adobe_client,
            context.adobe_customer,
        )

        if not context.subscriptions:
            error = "No subscriptions found without deployment ID to be added to the main agreement"
            logger.error(error)
            sync_main_agreement(
                context.gc_main_agreement,
                context.product_id,
                context.authorization_id,
                context.customer_id,
                error,
            )
            return

        next_step(client, context)


class CompleteTransferOrder(Step):
    """Completes the transfer order processing."""

    def __call__(self, client, context, next_step):
        """Completes transfer order with TEMPLATE_NAME_TRANSFER or default Transfer template."""
        switch_order_to_completed(client, context.order, TEMPLATE_NAME_TRANSFER)
        sync_agreements_by_agreement_ids(
            client,
            [context.order["agreement"]["id"]],
            dry_run=False,
            sync_prices=False,
        )
        sync_main_agreement(
            context.gc_main_agreement,
            context.product_id,
            context.authorization_id,
            context.customer_id,
        )
        next_step(client, context)


class FetchTransferData(Step):
    """Fetches transfer data from Adobe."""

    def __call__(self, mpt_client, context, next_step):
        """Fetches transfer data from Adobe."""
        if not context.transfer:
            has_error, order = validate_transfer_not_migrated(mpt_client, context.order)
            context.order = order
            context.validation_succeeded = not has_error
            return

        try:
            adobe_client = get_adobe_client()
            subscriptions = adobe_client.get_subscriptions(
                context.order["authorization"]["id"],
                context.transfer.customer_id,
            )
            subscriptions = exclude_subscriptions_with_deployment_id(subscriptions)
            adobe_transfer = adobe_client.get_transfer(
                context.order["authorization"]["id"],
                context.transfer.membership_id,
                context.transfer.transfer_id,
            )
        except AdobeError as e:
            context.order = set_ordering_parameter_error(
                context.order,
                Param.MEMBERSHIP_ID.value,
                ERR_ADOBE_MEMBERSHIP_PROCESSING.to_dict(
                    membership_id=context.transfer.membership_id,
                    error=str(e),
                ),
            )
            context.validation_succeeded = False
            return

        context.subscriptions = subscriptions
        context.adobe_transfer = exclude_items_with_deployment_id(adobe_transfer)

        next_step(mpt_client, context)
