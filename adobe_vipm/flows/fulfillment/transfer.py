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
    STATUS_GC_CREATED,
    STATUS_GC_ERROR,
    STATUS_GC_PENDING,
    STATUS_GC_TRANSFERRED,
    STATUS_RUNNING,
    STATUS_SYNCHRONIZED,
    create_gc_agreement_deployments,
    create_gc_main_agreement,
    get_agreement_deployment_view_link,
    get_gc_agreement_deployments_by_main_agreement,
    get_gc_main_agreement,
    get_transfer_by_authorization_membership_or_customer,
)
from adobe_vipm.flows.constants import (
    ERR_ADOBE_MEMBERSHIP_ID,
    ERR_ADOBE_MEMBERSHIP_NOT_FOUND,
    ERR_UPDATING_TRANSFER_ITEMS,
    MARKET_SEGMENT_COMMERCIAL,
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
    send_gc_email_notification,
    switch_order_to_completed,
    switch_order_to_failed,
    switch_order_to_query,
)
from adobe_vipm.flows.helpers import SetupContext
from adobe_vipm.flows.mpt import update_order
from adobe_vipm.flows.pipeline import Pipeline, Step
from adobe_vipm.flows.sync import sync_agreements_by_agreement_ids
from adobe_vipm.flows.utils import (
    are_all_transferring_items_expired,
    exclude_items_with_deployment_id,
    exclude_subscriptions_with_deployment_id,
    get_adobe_customer_id,
    get_adobe_membership_id,
    get_adobe_order_id,
    get_market_segment,
    get_one_time_skus,
    get_order_line_by_sku,
    get_ordering_parameter,
    has_order_line_updated,
    is_transferring_item_expired,
    set_adobe_customer_id,
    set_deployments,
    set_global_customer,
    set_ordering_parameter_error,
)
from adobe_vipm.notifications import Button, FactsSection, send_warning
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
    adobe_client,
    mpt_client,
    order,
    transfer,
    adobe_transfer,
    one_time_skus,
    gc_main_agreement,
    customer_deployments,
):
    authorization_id = order["authorization"]["id"]
    adobe_subscriptions = adobe_client.get_subscriptions(
        authorization_id,
        transfer.customer_id,
    )

    # remove expired items from adobe items
    adobe_items = [
        item
        for item in adobe_subscriptions["items"]
        if not is_transferring_item_expired(item)
    ]

    # If the order items has been updated, the validation order will fail
    if has_order_line_updated(order["lines"], adobe_items, "currentQuantity"):
        logger.error(ERR_UPDATING_TRANSFER_ITEMS.message)
        switch_order_to_failed(mpt_client, order, ERR_UPDATING_TRANSFER_ITEMS.message)
        return

    commitment_date = None
    if not adobe_transfer["lineItems"]:
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

    save_gc_parameters(mpt_client, order, gc_main_agreement, customer_deployments)

    switch_order_to_completed(mpt_client, order, TEMPLATE_NAME_BULK_MIGRATE)
    transfer.status = "synchronized"
    transfer.mpt_order_id = order["id"]
    transfer.synchronized_at = datetime.now()
    transfer.save()
    sync_main_agreement(
        gc_main_agreement,
        order["agreement"]["product"]["id"],
        authorization_id,
        transfer.customer_id,
    )


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
        context.order = save_adobe_order_id_and_customer_data(
            client,
            context.order,
            "",
            context.adobe_customer,
        )
        next_step(client, context)


class SyncGCMainAgreement(Step):
    def __init__(self, transfer, gc_main_agreement, status, customer_deployments):
        self.gc_main_agreement = gc_main_agreement
        self.status = status
        self.transfer = transfer
        self.customer_deployments = customer_deployments

    def __call__(self, client, context, next_step):
        sync_main_agreement(
            self.gc_main_agreement,
            context.order["agreement"]["product"]["id"],
            context.order["authorization"]["id"],
            self.transfer.customer_id,
        )
        save_gc_parameters(
            client, context.order, self.gc_main_agreement, self.customer_deployments
        )
        next_step(client, context)


def _create_new_adobe_order(
    mpt_client, order, transfer, gc_main_agreement, customer_deployments
):
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
        SyncGCMainAgreement(
            transfer, gc_main_agreement, STATUS_GC_CREATED, customer_deployments
        ),
        CompleteOrder(TEMPLATE_NAME_BULK_MIGRATE),
        UpdateTransferStatus(transfer, STATUS_SYNCHRONIZED),
    )

    context = Context(order=order)
    pipeline.run(mpt_client, context)


def _transfer_migrated(
    mpt_client,
    order,
    transfer,
    customer_deployments,
    gc_main_agreement,
    existing_deployments,
):
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
        _create_new_adobe_order(
            mpt_client, order, transfer, gc_main_agreement, customer_deployments
        )
        return

    adobe_client = get_adobe_client()
    authorization_id = order["authorization"]["id"]

    adobe_subscriptions = adobe_client.get_subscriptions(
        authorization_id,
        transfer.customer_id,
    )

    adobe_subscriptions = exclude_subscriptions_with_deployment_id(adobe_subscriptions)

    adobe_transfer = adobe_client.get_transfer(
        authorization_id,
        transfer.membership_id,
        transfer.transfer_id,
    )
    items_with_deployment_id = _get_order_line_items_with_deployment_id(
        adobe_transfer, order
    )
    if items_with_deployment_id:
        _manage_order_with_deployment_id(
            order, adobe_transfer, gc_main_agreement, items_with_deployment_id
        )
        return

    customer_id = adobe_transfer["customerId"]
    customer = adobe_client.get_customer(authorization_id, customer_id)
    if not _check_agreement_deployments(
        adobe_client,
        customer,
        adobe_transfer,
        existing_deployments,
        order,
        gc_main_agreement,
        customer_deployments,
    ):
        return

    adobe_transfer = exclude_items_with_deployment_id(adobe_transfer)

    one_time_skus = get_one_time_skus(mpt_client, order)
    adobe_items_without_one_time_offers = [
        item
        for item in adobe_subscriptions["items"]
        if get_partial_sku(item["offerId"]) not in one_time_skus
    ]

    if (
        are_all_transferring_items_expired(adobe_items_without_one_time_offers)
        or len(adobe_transfer["lineItems"]) == 0
    ) and not gc_main_agreement:
        _create_new_adobe_order(
            mpt_client, order, transfer, gc_main_agreement, customer_deployments
        )
    else:
        _fulfill_transfer_migrated(
            adobe_client,
            mpt_client,
            order,
            transfer,
            adobe_transfer,
            one_time_skus,
            gc_main_agreement,
            customer_deployments,
        )


def get_commitment_date(subscription, commitment_date):
    """
    Gets the commitment date from the subscription if it's not provided.

    Args:
        subscription (dict): The subscription object.
        commitment_date (str): The commitment date.

    Returns:
        str: The commitment date.
    """
    if subscription and not commitment_date:
        # subscription are cotermed so it's ok to take the first created
        commitment_date = subscription["commitmentDate"]
    return commitment_date


def generate_deployments_currency_map(line_items):
    """
    Generates a dictionary mapping deployment IDs to a list of their currency codes.

    Args:
        line_items (dict): The input dictionary containing transfer line items details.

    Returns:
        dict: A dictionary where the keys are deployment IDs and the values are lists of
        currency codes.
    """
    deployment_currency_map = {}

    for item in line_items:
        deployment_id = item.get("deploymentId", "")
        currency_code = item.get("currencyCode", "")

        if deployment_id:
            if deployment_id not in deployment_currency_map:
                deployment_currency_map[deployment_id] = []
            if currency_code not in deployment_currency_map[deployment_id]:
                deployment_currency_map[deployment_id].append(currency_code)

    return deployment_currency_map


def get_new_agreement_deployments(
    existing_deployments,
    customer_deployments,
    adobe_transfer_order,
    product_id,
    order,
):
    """
    Gets the new agreement deployments to be added to Airtable.

    Args:
        existing_deployments (list): The existing deployments in Airtable.
        customer_deployments (dict): The Adobe customer deployments.
        adobe_transfer_order (dict): The Adobe transfer order.
        product_id (str): The product ID.
        order (dict): The MPT order to be fulfilled.

    Returns:
        list: The new agreement deployments to be added to Airtable.
    """
    new_agreement_deployments = []
    deployment_currency_map = generate_deployments_currency_map(
        adobe_transfer_order["lineItems"]
    )

    for deployment in customer_deployments["items"]:
        created_deployment = next(
            (
                gc_deployment
                for gc_deployment in existing_deployments
                if gc_deployment.deployment_id == deployment.get("deploymentId")
            ),
            None,
        )
        if created_deployment:
            logger.info(
                f"Deployment {created_deployment.deployment_id} already exists in Airtable,"
                f" skipping"
            )
            continue

        agreement_deployment = {
            "deployment_id": deployment.get("deploymentId"),
            "status": "pending",
            "customer_id": adobe_transfer_order["customerId"],
            "product_id": product_id,
            "main_agreement_id": order.get("agreement", {}).get("id", ""),
            "account_id": order.get("client", {}).get("id", ""),
            "seller_id": order.get("seller", {}).get("id", ""),
            "membership_id": adobe_transfer_order["membershipId"],
            "transfer_id": adobe_transfer_order["transferId"],
            "deployment_currency": ",".join(
                deployment_currency_map.get(deployment.get("deploymentId"), [])
            ),
            "deployment_country": deployment.get("companyProfile", {})
            .get("address", {})
            .get("country", ""),
        }
        new_agreement_deployments.append(agreement_deployment)
    return new_agreement_deployments


def send_gc_agreement_deployments_notification(
    agreement_id, customer_id, customer_deployments, product_id
):
    """
    Sends a notification to the GC team with the new agreement deployments.

    Args:
        agreement_id (str): The agreement ID.
        customer_id (str): The customer ID.
        customer_deployments (dict): The Adobe customer deployments.
        product_id (str): The product ID.

    Returns:
        None
    """
    facts = {
        f"Deployment ID: {deployment.get("deploymentId")}": f"Country: {
            deployment.get("companyProfile", {}).get("address", {}).get("country", "")}"
        for deployment in customer_deployments["items"]
    }
    agreement_deployment_view_link = get_agreement_deployment_view_link(product_id)
    send_warning(
        f"Adobe Global Customer Deployments created for {agreement_id}",
        f"Following deployments have been created for the customer {customer_id}:",
        facts=FactsSection("Deployments", facts),
        button=Button(
            "Open Agreement Deployments View", agreement_deployment_view_link
        ),
    )


def are_all_deployments_synchronized(existing_deployments, customer_deployments):
    """
    Checks if all deployments are synchronized.

    Args:
        existing_deployments (list): The existing deployments in Airtable.
        customer_deployments (dict): The Adobe customer deployments.

    Returns:
        bool: True if all deployments are synchronized, False otherwise.
    """
    if customer_deployments.get("totalCount", 0) > 0:
        for customer_deployment in customer_deployments["items"]:
            created_deployment = next(
                (
                    gc_deployment
                    for gc_deployment in existing_deployments
                    if gc_deployment.deployment_id
                    == customer_deployment.get("deploymentId")
                ),
                None,
            )
            if not created_deployment:
                logger.info(
                    f"Deployment {customer_deployment.get('deploymentId')} is not created"
                )
                return True
            if created_deployment.status != STATUS_GC_CREATED:
                logger.info(
                    "All deployments are not synchronized, wait for the deployments to be created"
                )
                return False

    logger.info("All deployments are created, proceed to fulfill the transfer order")
    return True


def add_gc_main_agreement(
    order, adobe_transfer_order, status=STATUS_GC_PENDING, error=""
):
    """
    Adds a main agreement to Airtable.

    Args:
        order (dict): The MPT order to be fulfilled.
        adobe_transfer_order (dict): The Adobe transfer order.
        status (str): The status of the main agreement.
        error (str): The error description of the main agreement.

    Returns:
        None
    """
    logger.debug("Main agreement doesn't exist in Airtable, proceed to create it")
    main_agreement = {
        "membership_id": adobe_transfer_order.get("membershipId", ""),
        "authorization_uk": order.get("authorization", {}).get("id", ""),
        "main_agreement_id": order.get("agreement", {}).get("id", ""),
        "transfer_id": adobe_transfer_order.get("transferId", ""),
        "customer_id": adobe_transfer_order.get("customerId", ""),
        "status": status,
        "error_description": error,
    }
    create_gc_main_agreement(order["agreement"]["product"]["id"], main_agreement)


def _check_agreement_deployments(
    adobe_client,
    customer,
    adobe_transfer_order,
    existing_deployments,
    order,
    gc_main_agreement,
    customer_deployments,
):
    """
    Checks if the customer deployments are synchronized and if the main agreement exists
    in Airtable.

    Args:
        adobe_client (AdobeClient): An instance of the Adobe client.
        customer (dict): The Adobe customer.
        adobe_transfer_order (dict): The Adobe transfer order.
        existing_deployments (list): The existing deployments in Airtable.
        order (dict): The MPT order to be fulfilled.
        gc_main_agreement (GCMainAgreement): The main agreement in Airtable.
        customer_deployments (dict): The Adobe customer deployments.

    Returns:
        bool: True if the customer deployments are synchronized and the main agreement
        exists in Airtable, False otherwise.
    """
    product_id = order["agreement"]["product"]["id"]
    if customer.get("globalSalesEnabled", False):
        logger.info(
            "Adobe customer has global sales enabled, proceed to get the customer"
            " deployments"
        )
        if not gc_main_agreement:
            add_gc_main_agreement(order, adobe_transfer_order)

        if not customer_deployments:
            customer_deployments = adobe_client.get_customer_deployments(
                order["authorization"]["id"], adobe_transfer_order["customerId"]
            )
        if customer_deployments.get("totalCount", 0) > 0:
            logger.info(
                f"Adobe customer have {customer_deployments.get("totalCount")} deployments,"
                f" proceed to add agreement deployments to Airtable"
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


def _check_gc_main_agreement(gc_main_agreement, order):
    """
    Checks if the main agreement exists in Airtable and if all deployments are synchronized.

    Args:
        gc_main_agreement (GCMainAgreement): The main agreement in Airtable.
        order (dict): The MPT order to be fulfilled.

    Returns:
        bool: True if the main agreement exists in Airtable and all deployments are synchronized,
        False otherwise.
    """
    if gc_main_agreement:
        if gc_main_agreement.main_agreement_id:
            logger.info(
                f"Main agreement {gc_main_agreement.main_agreement_id} already exists in Airtable"
            )
            if gc_main_agreement.status == STATUS_GC_ERROR:
                logger.info(
                    "Main agreement is in error state, wait for manual intervention"
                )
                return False

        else:
            logger.info(
                "Main agreement exists in Airtable, proceed to save the current agreement ID."
                " Continue with deployment synchronization"
            )
            gc_main_agreement.main_agreement_id = order.get("agreement", {}).get(
                "id", ""
            )
            gc_main_agreement.save()
    return True


def create_agreement_subscriptions(
    adobe_transfer_order, mpt_client, order, adobe_client, customer
):
    """
    Creates subscriptions for the transfer order.

    Args:
        adobe_transfer_order (dict): The Adobe transfer order.
        mpt_client (MPTClient): An instance of the Marketplace platform client.
        order (dict): The MPT order to be fulfilled.
        adobe_client (AdobeClient): An instance of the Adobe client.
        customer (dict): The Adobe customer.

    Returns:
        list: The list of created subscriptions.
    """
    authorization_id = order["authorization"]["id"]
    customer_id = adobe_transfer_order["customerId"]
    one_time_skus = get_one_time_skus(mpt_client, order)
    subscriptions = []

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

        subscriptions.append(
            add_subscription(mpt_client, adobe_subscription, order, item)
        )

    return subscriptions


def sync_main_agreement(
    gc_main_agreement, product_id, authorization_id, customer_id, error=""
):
    """
    Synchronizes the main agreement status in Airtable.

    Args:
        gc_main_agreement (GCMainAgreement): The main agreement in Airtable.
        product_id (str): The product ID associated with the main agreement.
        authorization_id (str): The authorization ID associated with the main agreement.
        customer_id (str): The customer ID associated with the main agreement.
        error (str): The error message to be saved in the main agreement.

    Returns:
        None
    """
    if not gc_main_agreement:
        gc_main_agreement = get_main_agreement(
            product_id, authorization_id, customer_id
        )

    if gc_main_agreement:
        gc_main_agreement.status = STATUS_GC_ERROR if error else STATUS_GC_TRANSFERRED
        gc_main_agreement.error_description = error
        gc_main_agreement.save()


def _check_pending_deployments(
    gc_main_agreement, existing_deployments, customer_deployments
):
    """
    Checks if all deployments are synchronized and the main agreement is in a valid state.

    Args:
        gc_main_agreement (GCMainAgreement): The main agreement in Airtable.
        existing_deployments (list): The existing deployments in Airtable.
        customer_deployments (dict): The Adobe customer deployments.

    Returns:
        bool: True if all deployments are synchronized, False otherwise.

    """
    if gc_main_agreement and not are_all_deployments_synchronized(
        existing_deployments,
        customer_deployments,
    ):
        return False
    return True


def save_gc_parameters(mpt_client, order, gc_main_agreement, customer_deployments):
    """
    Saves the global customer and deployments parameters to the order.

    Args:
        mpt_client (MPTClient): An instance of the Marketplace platform client.
        order (dict): The MPT order to be updated.
        gc_main_agreement (GCMainAgreement): The main agreement in Airtable.
        customer_deployments (dict): The Adobe customer deployments.
    Returns:
        dict: The updated MPT order.

    """
    if not gc_main_agreement:
        return order

    deployments = [
        f'{deployment["deploymentId"]} - {deployment["companyProfile"]["address"]["country"]}'
        for deployment in customer_deployments["items"]
    ]
    order = set_global_customer(order, "Yes")
    order = set_deployments(order, deployments)
    update_order(mpt_client, order["id"], parameters=order["parameters"])
    return order


def _get_order_line_items_with_deployment_id(adobe_transfer_order, order):
    """
    Checks if any order line items contain a deployment ID.

    Args:
        adobe_transfer_order (dict): The Adobe transfer order containing line items.
        order (dict): The MPT order being processed.

    Returns:
        list: The list of items with deployment ID.
    """
    items_with_deployment = []
    for item in adobe_transfer_order["lineItems"]:
        if item.get("deploymentId", ""):
            order_line_item = get_order_line_by_sku(order, item["offerId"])
            if order_line_item:
                items_with_deployment.append(order_line_item["item"]["name"])
    return items_with_deployment


def _manage_order_with_deployment_id(
    order, adobe_transfer_order, gc_main_agreement, items_with_deployment
):
    """
    Manages the order with items that contain deployment ID. A new notification is
     sent to the GC team and the main agreement is set to error status.

    Args:
        order (dict): The MPT order to be fulfilled.
        adobe_transfer_order (dict): The Adobe transfer order.
        gc_main_agreement (GCMainAgreement): The main agreement in Airtable.
        items_with_deployment (list): The items with deployment ID.
    Returns:
        None
    """
    logger.warning(
        "Order contains items with deployment ID, keep in pending to be reviewed"
    )
    send_gc_email_notification(order, items_with_deployment)
    if gc_main_agreement:
        gc_main_agreement.status = STATUS_GC_ERROR
        gc_main_agreement.error_description = "Order contains items with deployment ID"
        gc_main_agreement.save()
    else:
        add_gc_main_agreement(
            order,
            adobe_transfer_order,
            STATUS_GC_ERROR,
            "Order contains items with deployment ID",
        )


def get_main_agreement(product_id, authorization_id, membership_id):
    """
    Gets the main agreement from Airtable based on the provided parameters.

    Args:
        product_id (str): The product ID associated with the main agreement.
        authorization_id (str): The authorization ID associated with the main agreement.
        membership_id (str): The membership ID associated with the main agreement.

    Returns:
        GCMainAgreement or None: The main agreement in Airtable if found, None otherwise.
    """
    if get_market_segment(product_id) == MARKET_SEGMENT_COMMERCIAL:
        return get_gc_main_agreement( product_id, authorization_id, membership_id)
    return None


def get_agreement_deployments(product_id, agreement_id):
    """
    Gets the agreement deployments from Airtable based on the provided parameters.

    Args:
        product_id (str): The product ID associated with the deployments.
        agreement_id (str): The agreement ID associated with the deployments.

    Returns:
        list or None: The agreement deployments in Airtable if found, None otherwise
    """

    if get_market_segment(product_id) == MARKET_SEGMENT_COMMERCIAL:
        return get_gc_agreement_deployments_by_main_agreement(product_id, agreement_id)
    return None


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
    customer_deployments = None
    transfer = get_transfer_by_authorization_membership_or_customer(
        product_id,
        authorization.authorization_id,
        membership_id,
    )
    gc_main_agreement = get_main_agreement(
        product_id,
        authorization.authorization_id,
        membership_id,
    )
    existing_deployments = get_agreement_deployments(
        product_id, order.get("agreement", {}).get("id", "")
    )

    # Check if the main agreement exists in Airtable and if all deployments are synchronized
    if not _check_gc_main_agreement(gc_main_agreement, order):
        return
    if gc_main_agreement:
        customer_deployments = adobe_client.get_customer_deployments(
            authorization_id, gc_main_agreement.customer_id
        )
    if not _check_pending_deployments(
        gc_main_agreement, existing_deployments, customer_deployments
    ):
        return

    if transfer:
        # Adobe account has been transferred in bulk migration
        check_processing_template(mpt_client, order, TEMPLATE_NAME_BULK_MIGRATE)
        _transfer_migrated(
            mpt_client,
            order,
            transfer,
            customer_deployments,
            gc_main_agreement,
            existing_deployments,
        )
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

    items_with_deployment_id = _get_order_line_items_with_deployment_id(
        adobe_transfer_order, order
    )
    if items_with_deployment_id:
        _manage_order_with_deployment_id(
            order, adobe_transfer_order, gc_main_agreement, items_with_deployment_id
        )
        return

    customer_id = adobe_transfer_order["customerId"]
    customer = adobe_client.get_customer(authorization_id, customer_id)

    # Check if the agreement deployments exist in Airtable and if all deployments are synchronized
    if not _check_agreement_deployments(
        adobe_client,
        customer,
        adobe_transfer_order,
        existing_deployments,
        order,
        gc_main_agreement,
        customer_deployments,
    ):
        return

    adobe_transfer_order = exclude_items_with_deployment_id(adobe_transfer_order)
    order = save_adobe_order_id_and_customer_data(
        mpt_client,
        order,
        adobe_order_id,
        customer,
    )

    subscriptions = create_agreement_subscriptions(
        adobe_transfer_order, mpt_client, order, adobe_client, customer
    )

    if not subscriptions:
        error = "No subscriptions found without deployment ID to be added to the main agreement"
        logger.error(error)
        sync_main_agreement(
            gc_main_agreement, product_id, authorization_id, customer_id, error
        )
        return

    commitment_date = None

    for subscription in subscriptions:
        commitment_date = get_commitment_date(subscription, commitment_date)

    if commitment_date:  # pragma: no branch
        order = save_next_sync_and_coterm_dates(mpt_client, order, commitment_date)

    order = save_gc_parameters(
        mpt_client, order, gc_main_agreement, customer_deployments
    )

    switch_order_to_completed(mpt_client, order, TEMPLATE_NAME_TRANSFER)
    sync_agreements_by_agreement_ids(mpt_client, [order["agreement"]["id"]], False)
    sync_main_agreement(gc_main_agreement, product_id, authorization_id, customer_id)
