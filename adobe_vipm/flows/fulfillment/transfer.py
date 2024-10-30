"""
This module contains the logic to implement the transfer fulfillment flow.
It exposes a single function that is the entrypoint for transfer order
processing.
A transfer order is a purchase order for an agreement that will be migrated
from the old Adobe VIP partner program to the new Adobe VIP Marketplace partner
program.
"""

import logging
from datetime import datetime

from adobe_vipm.adobe.client import get_adobe_client
from adobe_vipm.adobe.config import get_config
from adobe_vipm.adobe.constants import (
    STATUS_3YC_COMMITTED,
    STATUS_PENDING,
    STATUS_PROCESSED,
    STATUS_TRANSFER_INVALID_MEMBERSHIP,
    STATUS_TRANSFER_INVALID_MEMBERSHIP_OR_TRANSFER_IDS,
)
from adobe_vipm.adobe.errors import AdobeAPIError, AdobeError, AdobeHttpError
from adobe_vipm.adobe.utils import get_3yc_commitment
from adobe_vipm.flows.airtable import (
    STATUS_RUNNING,
    STATUS_SYNCHRONIZED,
    get_transfer_by_authorization_membership_or_customer,
)
from adobe_vipm.flows.constants import (
    ERR_ADOBE_MEMBERSHIP_ID,
    ERR_ADOBE_MEMBERSHIP_NOT_FOUND,
    ERR_UPDATING_TRANSFER_ITEMS,
    PARAM_MEMBERSHIP_ID,
    TEMPLATE_NAME_BULK_MIGRATE,
    TEMPLATE_NAME_TRANSFER,
)
from adobe_vipm.flows.context import Context
from adobe_vipm.flows.fulfillment.shared import (
    CompleteOrder,
    CreateOrUpdateSubscriptions,
    GetPreviewOrder,
    SetOrUpdateCotermNextSyncDates,
    SubmitNewOrder,
    UpdatePrices,
    add_subscription,
    check_processing_template,
    handle_retries,
    save_adobe_order_id,
    save_adobe_order_id_and_customer_data,
    save_next_sync_and_coterm_dates,
    switch_order_to_completed,
    switch_order_to_failed,
    switch_order_to_query,
)
from adobe_vipm.flows.helpers import SetupContext
from adobe_vipm.flows.pipeline import Pipeline, Step
from adobe_vipm.flows.sync import sync_agreements_by_agreement_ids
from adobe_vipm.flows.utils import (
    are_all_transferring_items_expired,
    get_adobe_customer_id,
    get_adobe_membership_id,
    get_adobe_order_id,
    get_one_time_skus,
    get_ordering_parameter,
    has_order_line_updated,
    is_transferring_item_expired,
    set_adobe_customer_id,
    set_ordering_parameter_error,
)
from adobe_vipm.utils import get_partial_sku

logger = logging.getLogger(__name__)


def _handle_transfer_preview_error(client, order, error):
    if (
        isinstance(error, AdobeAPIError)
        and error.code
        in (
            STATUS_TRANSFER_INVALID_MEMBERSHIP,
            STATUS_TRANSFER_INVALID_MEMBERSHIP_OR_TRANSFER_IDS,
        )
        or isinstance(error, AdobeHttpError)
        and error.status_code == 404
    ):
        error_msg = (
            str(error)
            if isinstance(error, AdobeAPIError)
            else ERR_ADOBE_MEMBERSHIP_NOT_FOUND
        )
        param = get_ordering_parameter(order, PARAM_MEMBERSHIP_ID)
        order = set_ordering_parameter_error(
            order,
            PARAM_MEMBERSHIP_ID,
            ERR_ADOBE_MEMBERSHIP_ID.to_dict(title=param["name"], details=error_msg),
        )
        switch_order_to_query(client, order)
        return

    switch_order_to_failed(client, order, str(error))


def _check_transfer(mpt_client, order, membership_id):
    """
    Checks the validity of a transfer order based on the provided parameters.

    Args:
        mpt_client (MPTClient): An instance of the Marketplace platform client.
        order (dict): The MPT order being processed.
        membership_id (str): The Adobe membership ID associated with the transfer.

    Returns:
        bool: True if the transfer is valid, False otherwise.
    """

    adobe_client = get_adobe_client()
    authorization_id = order["authorization"]["id"]
    transfer_preview = None
    try:
        transfer_preview = adobe_client.preview_transfer(
            authorization_id, membership_id
        )
    except AdobeError as e:
        _handle_transfer_preview_error(mpt_client, order, e)
        logger.warning(f"Transfer order {order['id']} has been failed: {str(e)}.")
        return False

    adobe_lines = sorted(
        [
            (get_partial_sku(item["offerId"]), item["quantity"])
            for item in transfer_preview["items"]
        ],
        key=lambda i: i[0],
    )

    order_lines = sorted(
        [
            (line["item"]["externalIds"]["vendor"], line["quantity"])
            for line in order["lines"]
        ],
        key=lambda i: i[0],
    )
    if adobe_lines != order_lines:
        reason = (
            "The items owned by the given membership don't "
            f"match the order (sku or quantity): {','.join([line[0] for line in adobe_lines])}."
        )
        switch_order_to_failed(mpt_client, order, reason)
        logger.warning(f"Transfer Order {order['id']} has been failed: {reason}.")
        return False
    return True


def _submit_transfer_order(mpt_client, order, membership_id):
    """
    Submits a transfer order to the Adobe API based on the provided parameters.
    In case the Adobe API returns errors, the order will be switched to failed.

    Args:
        mpt_client (MPTClient): An instance of the Marketplace platform client.
        order (dict): The MPT order to be submitted.
        membership_id (str): The Adobe membership ID associated with the transfer.

    Returns:
        dict or None: The Adobe transfer order if successful, None otherwise.
    """
    adobe_client = get_adobe_client()
    authorization_id = order["authorization"]["id"]
    seller_id = order["agreement"]["seller"]["id"]
    adobe_transfer_order = None
    try:
        adobe_transfer_order = adobe_client.create_transfer(
            authorization_id, seller_id, order["id"], membership_id
        )
    except AdobeError as e:
        switch_order_to_failed(mpt_client, order, str(e))
        logger.warning(f"Transfer order {order['id']} has been failed: {str(e)}.")
        return None

    adobe_transfer_order_id = adobe_transfer_order["transferId"]
    return save_adobe_order_id(mpt_client, order, adobe_transfer_order_id)


def _check_adobe_transfer_order_fulfilled(
    mpt_client, order, membership_id, adobe_transfer_id
):
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
    if adobe_order["status"] == STATUS_PENDING:
        handle_retries(mpt_client, order, adobe_transfer_id)
        return
    elif adobe_order["status"] != STATUS_PROCESSED:
        reason = f"Unexpected status ({adobe_order['status']}) received from Adobe."
        switch_order_to_failed(mpt_client, order, reason)
        logger.warning(f"Transfer {order['id']} has been failed: {reason}.")
        return
    return adobe_order


def _fulfill_transfer_migrated(
    adobe_client, mpt_client, order, transfer, adobe_transfer, one_time_skus
):

    authorization_id = order["authorization"]["id"]

    # remove expired items from adobe items
    adobe_items = [
        item
        for item in adobe_transfer["lineItems"]
        if not is_transferring_item_expired(item)
    ]

    # If the order items has been updated, the validation order will fail
    if has_order_line_updated(order["lines"], adobe_items, "quantity"):
        switch_order_to_failed(mpt_client, order, ERR_UPDATING_TRANSFER_ITEMS)
        return

    commitment_date = None
    for line in adobe_transfer["lineItems"]:
        if get_partial_sku(line["offerId"]) in one_time_skus:
            continue

        adobe_subscription = adobe_client.get_subscription(
            authorization_id,
            transfer.customer_id,
            line["subscriptionId"],
        )
        if adobe_subscription["status"] != STATUS_PROCESSED:
            logger.warning(
                f"Subscription {adobe_subscription['subscriptionId']} "
                f"for customer {transfer.customer_id} is in status "
                f"{adobe_subscription['status']}, skip it"
            )
            continue

        if transfer.customer_benefits_3yc_status != STATUS_3YC_COMMITTED:
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
        order = save_next_sync_and_coterm_dates(mpt_client, order, commitment_date)

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
    transfer.synchronized_at = datetime.now()
    transfer.save()


class UpdateTransferStatus(Step):
    def __init__(self, transfer, status):
        self.transfer = transfer
        self.status = status

    def __call__(self, client, context, next_step):

        self.transfer.status = "synchronized"
        self.transfer.mpt_order_id = context.order["id"]
        self.transfer.synchronized_at = datetime.now()
        self.transfer.save()

        next_step(client, context)


class SaveCustomerData(Step):
    def __call__(self, client, context, next_step):

        adobe_client = get_adobe_client()
        context.order = save_adobe_order_id_and_customer_data(
            adobe_client,
            context.order,
            "None",
            context.adobe_customer,
        )
        next_step(client, context)


def _create_new_adobe_order(mpt_client, order, transfer):
    # Create new order on Adobe with the items selected by the client
    adobe_customer_id = get_adobe_customer_id(order)
    if not adobe_customer_id:
        order = set_adobe_customer_id(order, transfer.customer_id)

    pipeline = Pipeline(
        SetupContext(),
        SaveCustomerData(),
        GetPreviewOrder(),
        SubmitNewOrder(),
        CreateOrUpdateSubscriptions(),
        SetOrUpdateCotermNextSyncDates(),
        UpdatePrices(),
        CompleteOrder(TEMPLATE_NAME_BULK_MIGRATE),
        UpdateTransferStatus(transfer, STATUS_SYNCHRONIZED),
    )

    context = Context(order=order)
    pipeline.run(mpt_client, context)


def _transfer_migrated(mpt_client, order, transfer):
    """
    Fulfills a transfer order when the transfer has already been processed
    by the mass migration tool.

    Args:
        mpt_client (MPTClient): The client used to consume the MPT API
        order (dict): The transfer order.
        transfer (Transfer): The AirTable transfer object.
    """
    if transfer.status == STATUS_RUNNING:
        param = get_ordering_parameter(order, PARAM_MEMBERSHIP_ID)
        order = set_ordering_parameter_error(
            order,
            PARAM_MEMBERSHIP_ID,
            ERR_ADOBE_MEMBERSHIP_ID.to_dict(
                title=param["name"], details="Migration in progress, retry later"
            ),
        )

        switch_order_to_query(mpt_client, order)
        return

    if transfer.status == STATUS_SYNCHRONIZED:
        switch_order_to_failed(
            mpt_client, order, "Membership has already been migrated."
        )
        return

    # If the order has order id, it means that new order has been created on Adobe
    # and, it is pending to review the order status
    adobe_order_id = get_adobe_order_id(order)
    if adobe_order_id:
        _create_new_adobe_order(mpt_client, order, transfer)
        return

    adobe_client = get_adobe_client()
    authorization_id = order["authorization"]["id"]

    adobe_subscriptions = adobe_client.get_subscriptions(
        authorization_id,
        transfer.customer_id,
    )

    adobe_transfer = adobe_client.get_transfer(
        authorization_id,
        transfer.membership_id,
        transfer.transfer_id,
    )

    one_time_skus = get_one_time_skus(mpt_client, order)
    adobe_items_without_one_time_offers = [
        item
        for item in adobe_subscriptions["items"]
        if get_partial_sku(item["offerId"]) not in one_time_skus
    ]

    if (
        are_all_transferring_items_expired(adobe_items_without_one_time_offers)
        or len(adobe_transfer["lineItems"]) == 0
    ):
        _create_new_adobe_order(mpt_client, order, transfer)
    else:
        _fulfill_transfer_migrated(
            adobe_client, mpt_client, order, transfer, adobe_transfer, one_time_skus
        )


def get_commitment_date(subscription, commitment_date):
    if subscription and not commitment_date:
        # subscription are cotermed so it's ok to take the first created
        commitment_date = subscription["commitmentDate"]
    return commitment_date


def fulfill_transfer_order(mpt_client, order):
    """
    Fulfills a transfer order by processing the necessary actions based on the provided parameters.

    Args:
        mpt_client (MPTClient): An instance of the Marketplace platform client.
        order (dict): The MPT transfer order to be fulfilled.

    Returns:
        None
    """
    adobe_client = get_adobe_client()
    config = get_config()
    membership_id = get_adobe_membership_id(order)
    authorization_id = order["authorization"]["id"]
    product_id = order["agreement"]["product"]["id"]
    authorization = config.get_authorization(authorization_id)
    transfer = get_transfer_by_authorization_membership_or_customer(
        product_id,
        authorization.authorization_id,
        membership_id,
    )

    if transfer:
        check_processing_template(mpt_client, order, TEMPLATE_NAME_BULK_MIGRATE)
        _transfer_migrated(mpt_client, order, transfer)
        return

    check_processing_template(mpt_client, order, TEMPLATE_NAME_TRANSFER)

    adobe_order_id = get_adobe_order_id(order)
    if not adobe_order_id:
        if not _check_transfer(mpt_client, order, membership_id):
            return

        order = _submit_transfer_order(mpt_client, order, membership_id)
        if not order:
            return

        adobe_order_id = order["externalIds"]["vendor"]

    adobe_transfer_order = _check_adobe_transfer_order_fulfilled(
        mpt_client, order, membership_id, adobe_order_id
    )
    if not adobe_transfer_order:
        return

    customer_id = adobe_transfer_order["customerId"]
    customer = adobe_client.get_customer(authorization_id, customer_id)

    order = save_adobe_order_id_and_customer_data(
        mpt_client,
        order,
        adobe_order_id,
        customer,
    )
    commitment_date = None

    one_time_skus = get_one_time_skus(mpt_client, order)

    for item in adobe_transfer_order["lineItems"]:
        if get_partial_sku(item["offerId"]) in one_time_skus:
            continue

        adobe_subscription = adobe_client.get_subscription(
            authorization_id,
            customer_id,
            item["subscriptionId"],
        )
        if adobe_subscription["status"] != STATUS_PROCESSED:
            logger.warning(
                f"Subscription {adobe_subscription['subscriptionId']} "
                f"for customer {customer_id} is in status "
                f"{adobe_subscription['status']}, skip it"
            )
            continue

        commitment = get_3yc_commitment(customer)
        if commitment.get("status", "") != STATUS_3YC_COMMITTED:
            adobe_subscription = adobe_client.update_subscription(
                authorization_id,
                customer_id,
                item["subscriptionId"],
                auto_renewal=True,
            )

        subscription = add_subscription(mpt_client, adobe_subscription, order, item)
        commitment_date = get_commitment_date(subscription, commitment_date)

    if commitment_date:  # pragma: no branch
        order = save_next_sync_and_coterm_dates(mpt_client, order, commitment_date)

    switch_order_to_completed(mpt_client, order, TEMPLATE_NAME_TRANSFER)
    sync_agreements_by_agreement_ids(mpt_client, [order["agreement"]["id"]], False)
