"""
This module contains the logic to implement the transfer fulfillment flow.

It exposes a single function that is the entrypoint for transfer order
processing.
A transfer order is a purchase order for an agreement that will be migrated
from the old Adobe VIP partner program to the new Adobe VIP Marketplace partner
program.
"""

import datetime as dt
import logging
from operator import itemgetter

from mpt_extension_sdk.mpt_http.mpt import (
    get_product_items_by_skus,
    update_order,
)

from adobe_vipm.adobe.client import get_adobe_client
from adobe_vipm.adobe.constants import AdobeStatus, ThreeYearCommitmentStatus
from adobe_vipm.adobe.errors import AdobeAPIError, AdobeError, AdobeHttpError
from adobe_vipm.airtable.models import (
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
    ERR_ADOBE_GOVERNMENT_VALIDATE_IS_LGA,
    ERR_ADOBE_GOVERNMENT_VALIDATE_IS_NOT_LGA,
    ERR_ADOBE_MEMBERSHIP_ID,
    ERR_ADOBE_MEMBERSHIP_NOT_FOUND,
    ERR_ADOBE_TRANSFER_PREVIEW,
    ERR_MEMBERSHIP_HAS_BEEN_TRANSFERED,
    ERR_MEMBERSHIP_ITEMS_DONT_MATCH,
    ERR_UNEXPECTED_ADOBE_ERROR_STATUS,
    ERR_UPDATING_TRANSFER_ITEMS,
    ERR_VIPM_UNHANDLED_EXCEPTION,
    MARKET_SEGMENT_COMMERCIAL,
    TEMPLATE_NAME_BULK_MIGRATE,
    TEMPLATE_NAME_TRANSFER,
    ItemTermsModel,
    Param,
)
from adobe_vipm.flows.context import Context
from adobe_vipm.flows.errors import GovernmentLGANotValidOrderError, GovernmentNotValidOrderError
from adobe_vipm.flows.fulfillment.shared import (
    CompleteOrder,
    CreateOrUpdateAssets,
    CreateOrUpdateSubscriptions,
    GetPreviewOrder,
    SetOrUpdateCotermDate,
    SetupDueDate,
    SubmitNewOrder,
    add_asset,
    add_subscription,
    check_processing_template,
    handle_retries,
    save_adobe_order_id,
    save_adobe_order_id_and_customer_data,
    save_coterm_dates,
    send_gc_mpt_notification,
    switch_order_to_completed,
    switch_order_to_failed,
    switch_order_to_query,
)
from adobe_vipm.flows.helpers import SetupContext, UpdatePrices
from adobe_vipm.flows.pipeline import Pipeline, Step
from adobe_vipm.flows.sync import sync_agreements_by_agreement_ids
from adobe_vipm.flows.utils import (
    are_all_transferring_items_expired,
    exclude_items_with_deployment_id,
    exclude_subscriptions_with_deployment_id,
    get_adobe_customer_id,
    get_adobe_membership_id,
    get_adobe_order_id,
    get_global_customer,
    get_market_segment,
    get_one_time_skus,
    get_ordering_parameter,
    has_order_line_updated,
    is_transferring_item_expired,
    set_adobe_customer_id,
    set_deployments,
    set_global_customer,
    set_ordering_parameter_error,
)
from adobe_vipm.flows.utils.validation import validate_government_lga_data
from adobe_vipm.notifications import Button, FactsSection, send_warning
from adobe_vipm.utils import get_3yc_commitment, get_partial_sku

logger = logging.getLogger(__name__)


SUBSCRIPTION_SKIP_LOG = "Subscription %s for customer %s is in status %s, skip it"


def _handle_transfer_preview_error(client, order, error):
    if (
        isinstance(error, AdobeAPIError)
        and error.code
        in {
            AdobeStatus.TRANSFER_INVALID_MEMBERSHIP,
            AdobeStatus.TRANSFER_INVALID_MEMBERSHIP_OR_TRANSFER_IDS,
        }
    ) or (isinstance(error, AdobeHttpError) and error.status_code == 404):
        error_msg = (
            str(error) if isinstance(error, AdobeAPIError) else ERR_ADOBE_MEMBERSHIP_NOT_FOUND
        )
        param = get_ordering_parameter(order, Param.MEMBERSHIP_ID.value)
        order = set_ordering_parameter_error(
            order,
            Param.MEMBERSHIP_ID.value,
            ERR_ADOBE_MEMBERSHIP_ID.to_dict(title=param["name"], details=error_msg),
        )
        switch_order_to_query(client, order)
        return

    switch_order_to_failed(
        client,
        order,
        ERR_ADOBE_TRANSFER_PREVIEW.to_dict(error=str(error)),
    )


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
        transfer_preview = adobe_client.preview_transfer(authorization_id, membership_id)
    except AdobeError as error:
        _handle_transfer_preview_error(mpt_client, order, error)
        logger.warning("Transfer order %s has been failed: %s.", order["id"], str(error))
        return False

    try:
        validate_government_lga_data(order, transfer_preview)
    except GovernmentLGANotValidOrderError:
        switch_order_to_failed(
            mpt_client, order, ERR_ADOBE_GOVERNMENT_VALIDATE_IS_NOT_LGA.to_dict()
        )
        return False
    except GovernmentNotValidOrderError:
        switch_order_to_failed(mpt_client, order, ERR_ADOBE_GOVERNMENT_VALIDATE_IS_LGA.to_dict())
        return False

    adobe_lines = sorted(
        [
            (get_partial_sku(item["offerId"]), item["quantity"])
            for item in transfer_preview["items"]
        ],
        key=itemgetter(0),
    )

    order_lines = sorted(
        [(line["item"]["externalIds"]["vendor"], line["quantity"]) for line in order["lines"]],
        key=itemgetter(0),
    )
    if adobe_lines != order_lines:
        error = ERR_MEMBERSHIP_ITEMS_DONT_MATCH.to_dict(
            lines=",".join([line[0] for line in adobe_lines]),
        )
        switch_order_to_failed(mpt_client, order, error)
        logger.warning("Transfer %s has been failed: %s.", order["id"], error["message"])
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
    except AdobeError as error:
        error = ERR_VIPM_UNHANDLED_EXCEPTION.to_dict(error=str(error))
        switch_order_to_failed(mpt_client, order, error)
        logger.warning("Transfer %s has been failed: %s.", order["id"], error["message"])
        return None

    adobe_transfer_order_id = adobe_transfer_order["transferId"]
    return save_adobe_order_id(mpt_client, order, adobe_transfer_order_id)


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
        if not is_transferring_item_expired(item) and get_partial_sku(item["offerId"])
    ]
    # If the order items has been updated, the validation order will fail
    if has_order_line_updated(order["lines"], adobe_items, Param.CURRENT_QUANTITY.value):
        logger.error(ERR_UPDATING_TRANSFER_ITEMS.message)
        switch_order_to_failed(mpt_client, order, ERR_UPDATING_TRANSFER_ITEMS.to_dict())
        return

    customer = adobe_client.get_customer(authorization_id, transfer.customer_id)
    order = save_adobe_order_id_and_customer_data(
        mpt_client,
        order,
        transfer.transfer_id,
        customer,
    )

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
            authorization_id, transfer.customer_id, line["subscriptionId"]
        )
        if adobe_subscription["status"] != AdobeStatus.PROCESSED:
            logger.info(
                SUBSCRIPTION_SKIP_LOG,
                adobe_subscription["subscriptionId"],
                transfer.customer_id,
                adobe_subscription["status"],
            )
            continue

        if get_partial_sku(line["offerId"]) in one_time_skus:  # pragma: no cover
            add_asset(mpt_client, adobe_subscription, order, line)
        else:
            subscription = _sync_subscription_order(
                adobe_client,
                mpt_client,
                adobe_subscription,
                authorization_id,
                transfer.customer_benefits_3yc_status,
                transfer.customer_id,
                order,
                line,
            )
            if subscription and not commitment_date:  # pragma: no branch
                # subscription are cotermed so it's ok to take the first created
                commitment_date = subscription["commitmentDate"]

    if commitment_date:  # pragma: no branch
        order = save_coterm_dates(mpt_client, order, commitment_date)

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


def _sync_subscription_order(
    adobe_client,
    mpt_client,
    adobe_subscription,
    authorization_id,
    status,
    customer_id,
    order,
    line,
):
    """
    Updates subscription auto-renewal if needed and adds it to the order.

    Args:
        adobe_client: The Adobe client instance
        mpt_client: The MPT client instance
        adobe_subscription: The Adobe subscription object
        authorization_id (str): The authorization ID
        status (str): The status of the customer benefits 3YC
        customer_id (str): The customer ID
        order (dict): The MPT order
        line (dict): The subscription line item

    Returns:
        dict or None: The added subscription if successful, None otherwise
    """
    if status != ThreeYearCommitmentStatus.COMMITTED:
        renewal_quantity = adobe_subscription.get("autoRenewal", {}).get("renewalQuantity")
        line_quantity = line.get("quantity") or line.get("currentQuantity")
        new_renewal_quantity = min(line_quantity, renewal_quantity)
        try:
            adobe_subscription = adobe_client.update_subscription(
                authorization_id,
                customer_id,
                line["subscriptionId"],
                auto_renewal=True,
                quantity=new_renewal_quantity,
            )
        except AdobeAPIError:
            logger.exception(
                "Error updating subscription agreement transferred %s",
                line["subscriptionId"],
            )

    return add_subscription(mpt_client, adobe_subscription, order, line)


class UpdateTransferStatus(Step):
    """Step to update transfer status in Airtable."""

    # TODO: Why transfer not in the context???
    def __init__(self, transfer, status):
        self.transfer = transfer
        self.status = status

    def __call__(self, client, context, next_step):
        """Step to update transfer status in Airtable."""
        self.transfer.status = self.status
        self.transfer.mpt_order_id = context.order["id"]
        self.transfer.synchronized_at = dt.datetime.now(tz=dt.UTC)
        self.transfer.save()

        next_step(client, context)


class SaveCustomerData(Step):
    """Save customer data and order id to the MPT order."""

    def __call__(self, client, context, next_step):
        """Save customer data and order id to the MPT order."""
        context.order = save_adobe_order_id_and_customer_data(
            client,
            context.order,
            "",
            context.adobe_customer,
        )
        next_step(client, context)


class SyncGCMainAgreement(Step):
    """Sync Global Customer Main Agreement."""

    def __init__(self, transfer, gc_main_agreement):
        self.gc_main_agreement = gc_main_agreement
        self.transfer = transfer

    def __call__(self, client, context, next_step):
        """Sync global customer main agreement."""
        sync_main_agreement(
            self.gc_main_agreement,
            context.order["agreement"]["product"]["id"],
            context.order["authorization"]["id"],
            self.transfer.customer_id,
        )
        next_step(client, context)


def _create_new_adobe_order(mpt_client, order, transfer, gc_main_agreement):
    # Create new order on Adobe with the items selected by the client
    adobe_customer_id = get_adobe_customer_id(order)
    if not adobe_customer_id:
        order = set_adobe_customer_id(order, transfer.customer_id)

    pipeline = Pipeline(
        SetupContext(),
        SaveCustomerData(),
        GetPreviewOrder(),
        SubmitNewOrder(),
        CreateOrUpdateAssets(),
        CreateOrUpdateSubscriptions(),
        SetOrUpdateCotermDate(),
        UpdatePrices(),
        SyncGCMainAgreement(transfer, gc_main_agreement),
        CompleteOrder(TEMPLATE_NAME_BULK_MIGRATE),
        UpdateTransferStatus(transfer, STATUS_SYNCHRONIZED),
    )

    context = Context(order=order)
    pipeline.run(mpt_client, context)


def _transfer_migrated(  # noqa: C901
    mpt_client,
    order,
    transfer,
    customer_deployments,
    gc_main_agreement,
    existing_deployments,
):
    """
    Fulfills a transfer order when the transfer is processed by the mass migration tool.

    Args:
        mpt_client (MPTClient): The client used to consume the MPT API
        order (dict): The transfer order.
        transfer (Transfer): The AirTable transfer object.
        customer_deployments (list[dict]): Adobe Global customer deployments.
        gc_main_agreement (dict): GC agreement deployment.
        existing_deployments (list[dict]): existing created deployments to filter out.
    """
    if transfer.status == STATUS_RUNNING:
        param = get_ordering_parameter(order, Param.MEMBERSHIP_ID.value)
        order = set_ordering_parameter_error(
            order,
            Param.MEMBERSHIP_ID.value,
            ERR_ADOBE_MEMBERSHIP_ID.to_dict(
                title=param["name"], details="Migration in progress, retry later"
            ),
        )

        switch_order_to_query(mpt_client, order)
        return
    if transfer.status == STATUS_SYNCHRONIZED:
        switch_order_to_failed(
            mpt_client,
            order,
            ERR_MEMBERSHIP_HAS_BEEN_TRANSFERED.to_dict(),
        )
        return

    # If the order has order id, it means that new order has been created on Adobe
    # and, it is pending to review the order status
    adobe_order_id = get_adobe_order_id(order)
    if adobe_order_id:
        _create_new_adobe_order(mpt_client, order, transfer, gc_main_agreement)
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
    items_with_deployment_id = _get_order_line_items_with_deployment_id(adobe_transfer, order)
    if items_with_deployment_id:
        _manage_order_with_deployment_id(
            mpt_client, order, adobe_transfer, gc_main_agreement, items_with_deployment_id
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
    returned_skus = [get_partial_sku(item["offerId"]) for item in adobe_subscriptions["items"]]

    items = []
    if returned_skus:
        items = get_product_items_by_skus(
            mpt_client, order["agreement"]["product"]["id"], returned_skus
        )

    one_time_skus = [
        item["externalIds"]["vendor"]
        for item in items
        if item["terms"]["period"] == ItemTermsModel.ONE_TIME
    ]
    adobe_items_without_one_time_offers = [
        item
        for item in adobe_subscriptions["items"]
        if get_partial_sku(item["offerId"]) not in one_time_skus
    ]

    if (
        are_all_transferring_items_expired(adobe_items_without_one_time_offers)
        or len(adobe_transfer["lineItems"]) == 0
    ) and not gc_main_agreement:
        _create_new_adobe_order(mpt_client, order, transfer, gc_main_agreement)
    else:
        _fulfill_transfer_migrated(
            adobe_client,
            mpt_client,
            order,
            transfer,
            one_time_skus,
            gc_main_agreement,
            adobe_subscriptions,
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
        customer_deployments (list): The Adobe customer deployments.
        adobe_transfer_order (dict): The Adobe transfer order.
        product_id (str): The product ID.
        order (dict): The MPT order to be fulfilled.

    Returns:
        list: The new agreement deployments to be added to Airtable.
    """
    new_agreement_deployments = []
    deployment_currency_map = generate_deployments_currency_map(adobe_transfer_order["lineItems"])

    for deployment in customer_deployments:
        # TODO: find_first?
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
                "Deployment %s already exists in Airtable, skipping",
                created_deployment.deployment_id,
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
        customer_deployments (list): The Adobe customer deployments.
        product_id (str): The product ID.

    Returns:
        None
    """
    facts = {
        f"Deployment ID: {deployment.get('deploymentId')}": f"Country: {
            deployment.get('companyProfile', {}).get('address', {}).get('country', '')
        }"
        for deployment in customer_deployments
    }
    agreement_deployment_view_link = get_agreement_deployment_view_link(product_id)
    send_warning(
        f"Adobe Global Customer Deployments created for {agreement_id}",
        f"Following deployments have been created for the customer {customer_id}:",
        facts=FactsSection("Deployments", facts),
        button=Button("Open Agreement Deployments View", agreement_deployment_view_link),
    )


def are_all_deployments_synchronized(existing_deployments, customer_deployments):
    """
    Checks if all deployments are synchronized.

    Args:
        existing_deployments (list): The existing deployments in Airtable.
        customer_deployments (list): The Adobe customer deployments.

    Returns:
        bool: True if all deployments are synchronized, False otherwise.
    """
    for customer_deployment in customer_deployments:
        created_deployment = next(
            (
                gc_deployment
                for gc_deployment in existing_deployments
                if gc_deployment.deployment_id == customer_deployment.get("deploymentId")
            ),
            None,
        )
        if not created_deployment:
            logger.info("Deployment %s is not created", customer_deployment.get("deploymentId"))
            return True
        if created_deployment.status != STATUS_GC_CREATED:
            logger.info(
                "All deployments are not synchronized, wait for the deployments to be created"
            )
            return False

    logger.info("All deployments are created, proceed to fulfill the transfer order")
    return True


def add_gc_main_agreement(order, adobe_transfer_order, status=STATUS_GC_PENDING, error=""):
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
                "Main agreement %s already exists in Airtable",
                gc_main_agreement.main_agreement_id,
            )
            if gc_main_agreement.status == STATUS_GC_ERROR:
                logger.info("Main agreement is in error state, wait for manual intervention")
                return False

        else:
            logger.info(
                "Main agreement exists in Airtable, proceed to save the current agreement ID."
                " Continue with deployment synchronization"
            )
            gc_main_agreement.main_agreement_id = order.get("agreement", {}).get("id", "")
            gc_main_agreement.save()
    return True


def create_agreement_subscriptions(adobe_transfer_order, mpt_client, order, adobe_client, customer):
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
        if adobe_subscription["status"] != AdobeStatus.PROCESSED:
            logger.info(
                SUBSCRIPTION_SKIP_LOG,
                adobe_subscription["subscriptionId"],
                customer_id,
                adobe_subscription["status"],
            )
            continue

        commitment = get_3yc_commitment(customer)
        subscription = _sync_subscription_order(
            adobe_client,
            mpt_client,
            adobe_subscription,
            authorization_id,
            commitment.get("status", ""),
            customer_id,
            order,
            item,
        )
        subscriptions.append(subscription)

    return subscriptions


def sync_main_agreement(gc_main_agreement, product_id, authorization_id, customer_id, error=""):
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
        gc_main_agreement = get_main_agreement(product_id, authorization_id, customer_id)

    if gc_main_agreement:
        gc_main_agreement.status = STATUS_GC_ERROR if error else STATUS_GC_TRANSFERRED
        gc_main_agreement.error_description = error
        gc_main_agreement.save()


def _check_pending_deployments(gc_main_agreement, existing_deployments, customer_deployments):
    """
    Checks if all deployments are synchronized and the main agreement is in a valid state.

    Args:
        gc_main_agreement (GCMainAgreement): The main agreement in Airtable.
        existing_deployments (list): The existing deployments in Airtable.
        customer_deployments (list): The Adobe customer deployments.

    Returns:
        bool: True if all deployments are synchronized, False otherwise.

    """
    return not gc_main_agreement or are_all_deployments_synchronized(
        existing_deployments,
        customer_deployments,
    )


def save_gc_parameters(mpt_client, order, customer_deployments):
    """
    Saves the global customer and deployments parameters to the order.

    Args:
        mpt_client (MPTClient): An instance of the Marketplace platform client.
        order (dict): The MPT order to be updated.
        gc_main_agreement (GCMainAgreement): The main agreement in Airtable.
        customer_deployments (list): The Adobe customer deployments.

    Returns:
        dict: The updated MPT order.

    """
    global_customer_enabled = get_global_customer(order)
    if global_customer_enabled == ["Yes"]:
        return order

    deployments = [
        f"{deployment['deploymentId']} - {deployment['companyProfile']['address']['country']}"
        for deployment in customer_deployments
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

    for line in order["lines"]:
        adobe_items_with_same_offer_id = [
            item
            for item in adobe_transfer_order["lineItems"]
            if line["item"]["externalIds"]["vendor"] in item["offerId"]
        ]
        if adobe_items_with_same_offer_id:
            items_without_deployment = [
                item for item in adobe_items_with_same_offer_id if not item.get("deploymentId", "")
            ]
            if not items_without_deployment:
                items_with_deployment.append(line["item"]["name"])
    return items_with_deployment


def _manage_order_with_deployment_id(
    mpt_client, order, adobe_transfer_order, gc_main_agreement, items_with_deployment
):
    """
    Manages the order with items that contain deployment ID.

    A new notification is sent to the GC team and the main agreement is set to error status.

    Args:
        mpt_client (MPTClient): The Marketplace API client
        order (dict): The MPT order to be fulfilled.
        adobe_transfer_order (dict): The Adobe transfer order.
        gc_main_agreement (GCMainAgreement): The main agreement in Airtable.
        items_with_deployment (list): The items with deployment ID.

    Returns:
        None
    """
    logger.warning("Order contains items with deployment ID, keep in pending to be reviewed")
    send_gc_mpt_notification(mpt_client, order, items_with_deployment)
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
        return get_gc_main_agreement(product_id, authorization_id, membership_id)
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


class SetupTransferContext(Step):
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


class ValidateGCMainAgreement(Step):
    """Validates if the main agreement exists in Airtable and all deployments are synchronized."""

    def __call__(self, client, context, next_step):
        """Validates if the main agreement exists in Airtable."""
        if not _check_gc_main_agreement(context.gc_main_agreement, context.order):
            return

        if context.gc_main_agreement:
            adobe_client = get_adobe_client()
            context.customer_deployments = adobe_client.get_customer_deployments_active_status(
                context.authorization_id, context.gc_main_agreement.customer_id
            )
            context.order = save_gc_parameters(client, context.order, context.customer_deployments)

        if not _check_pending_deployments(
            context.gc_main_agreement, context.existing_deployments, context.customer_deployments
        ):
            return

        next_step(client, context)


class HandleMigratedTransfer(Step):
    """Handles transfer orders that have already been processed by the mass migration tool."""

    def __call__(self, client, context, next_step):
        """Handles transfer orders that have already been processed by the mass migration tool."""
        if not context.transfer:
            next_step(client, context)
            return

        check_processing_template(client, context.order, TEMPLATE_NAME_BULK_MIGRATE)

        if not self._validate_government_transfer(client, context):
            return

        _transfer_migrated(
            client,
            context.order,
            context.transfer,
            context.customer_deployments,
            context.gc_main_agreement,
            context.existing_deployments,
        )

    def _validate_government_transfer(self, client, context):
        adobe_client = get_adobe_client()
        adobe_customer = adobe_client.get_customer(
            context.authorization_id, context.transfer.customer_id
        )
        try:
            validate_government_lga_data(context.order, adobe_customer)
        except GovernmentLGANotValidOrderError:
            switch_order_to_failed(
                client, context.order, ERR_ADOBE_GOVERNMENT_VALIDATE_IS_NOT_LGA.to_dict()
            )
            return False
        except GovernmentNotValidOrderError:
            switch_order_to_failed(
                client, context.order, ERR_ADOBE_GOVERNMENT_VALIDATE_IS_LGA.to_dict()
            )
            return False

        return True


class CheckTransferTemplate(Step):
    """Checks the processing template for transfer orders."""

    def __call__(self, client, context, next_step):
        """Checks the processing template for transfer orders."""
        check_processing_template(client, context.order, TEMPLATE_NAME_TRANSFER)
        next_step(client, context)


class ValidateTransfer(Step):
    """Validates the transfer order by checking membership and items."""

    def __call__(self, client, context, next_step):
        """Validates the transfer order by checking membership and items."""
        context.adobe_new_order_id = get_adobe_order_id(context.order)
        if context.adobe_new_order_id:
            next_step(client, context)
            return

        if not _check_transfer(client, context.order, context.membership_id):
            return

        context.order = _submit_transfer_order(client, context.order, context.membership_id)
        if not context.order:
            return

        context.adobe_new_order_id = context.order["externalIds"]["vendor"]
        next_step(client, context)


class CheckAdobeTransferOrder(Step):
    """Checks if the Adobe transfer order has been fulfilled."""

    def __call__(self, client, context, next_step):
        """Checks if the Adobe transfer order has been fulfilled."""
        context.adobe_transfer_order = _check_adobe_transfer_order_fulfilled(
            client, context.order, context.membership_id, context.adobe_new_order_id
        )
        if not context.adobe_transfer_order:
            return

        next_step(client, context)


class ValidateDeploymentItems(Step):
    """Validates if order line items contain deployment IDs."""

    def __call__(self, client, context, next_step):
        """Validates if order line items contain deployment IDs."""
        context.items_with_deployment_id = _get_order_line_items_with_deployment_id(
            context.adobe_transfer_order, context.order
        )
        if context.items_with_deployment_id:
            _manage_order_with_deployment_id(
                client,
                context.order,
                context.adobe_transfer_order,
                context.gc_main_agreement,
                context.items_with_deployment_id,
            )
            return

        next_step(client, context)


class GetAdobeCustomer(Step):
    """Retrieves the Adobe customer information."""

    def __call__(self, client, context, next_step):
        """Get Adobe customer and saves it to the context."""
        adobe_client = get_adobe_client()
        context.customer_id = context.adobe_transfer_order["customerId"]
        context.adobe_customer = adobe_client.get_customer(
            context.authorization_id, context.customer_id
        )

        context.order = save_adobe_order_id_and_customer_data(
            client,
            context.order,
            context.adobe_new_order_id,
            context.adobe_customer,
        )

        next_step(client, context)


class ValidateAgreementDeployments(Step):
    """Validates if the deployments exist in Airtable and if deployments are synchronized."""

    def __call__(self, client, context, next_step):
        """Checks if deployments exists in Airtable."""
        adobe_client = get_adobe_client()

        if not _check_agreement_deployments(
            adobe_client,
            context.adobe_customer,
            context.adobe_transfer_order,
            context.existing_deployments,
            context.order,
            context.gc_main_agreement,
            context.customer_deployments,
        ):
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
            context.adobe_new_order_id,
            context.adobe_customer,
        )
        next_step(client, context)


class CreateTransferAssets(Step):
    """Create assets for the transfer order."""

    def __call__(self, client, context, next_step):
        """Create transfer assets."""
        adobe_client = get_adobe_client()
        adobe_transfer_order = context.adobe_transfer_order
        customer_id = adobe_transfer_order["customerId"]
        one_time_skus = get_one_time_skus(client, context.order)
        assets = []
        for item in adobe_transfer_order["lineItems"]:
            if get_partial_sku(item["offerId"]) not in one_time_skus:
                continue

            adobe_subscription = adobe_client.get_subscription(
                context.order["authorization"]["id"], customer_id, item["subscriptionId"]
            )
            if adobe_subscription["status"] != AdobeStatus.PROCESSED:
                logger.info(
                    SUBSCRIPTION_SKIP_LOG,
                    adobe_subscription["subscriptionId"],
                    customer_id,
                    adobe_subscription["status"],
                )
                continue

            assets.append(add_asset(client, adobe_subscription, context.order, item))

        context.assets = assets
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
            logger.info(
                "No subscriptions found without deployment ID to be added to the main agreement"
            )

        next_step(client, context)


class SetCommitmentDates(Step):
    """Sets commitment dates for the subscriptions."""

    def __call__(self, client, context, next_step):
        """Update commitments dates in context."""
        context.commitment_date = None

        for subscription in context.subscriptions:
            context.commitment_date = get_commitment_date(subscription, context.commitment_date)

        if context.commitment_date:  # pragma: no branch
            context.order = save_coterm_dates(client, context.order, context.commitment_date)

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


def fulfill_transfer_order(mpt_client, order):
    """
    Fulfill transfer order pipeline.

    Args:
        mpt_client (MPTClient): Marketplace API client
        order (dict): Marketplace order
    """
    pipeline = Pipeline(
        SetupContext(),
        SetupDueDate(),
        SetupTransferContext(),
        ValidateGCMainAgreement(),
        HandleMigratedTransfer(),
        CheckTransferTemplate(),
        ValidateTransfer(),
        CheckAdobeTransferOrder(),
        ValidateDeploymentItems(),
        GetAdobeCustomer(),
        ValidateAgreementDeployments(),
        ProcessTransferOrder(),
        CreateTransferAssets(),
        CreateTransferSubscriptions(),
        SetCommitmentDates(),
        CompleteTransferOrder(),
    )

    context = Context(order=order)
    pipeline.run(mpt_client, context)
