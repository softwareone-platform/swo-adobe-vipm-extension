import logging
import sys
import traceback
from datetime import date, datetime, timedelta

from mpt_extension_sdk.mpt_http.base import MPTClient
from mpt_extension_sdk.mpt_http.mpt import (
    get_agreement_subscription,
    get_agreements_by_customer_deployments,
    get_agreements_by_ids,
    get_agreements_by_next_sync,
    get_agreements_by_query,
    get_all_agreements,
    update_agreement,
    update_agreement_subscription,
)

from adobe_vipm.adobe.client import get_adobe_client
from adobe_vipm.adobe.constants import (
    STATUS_3YC_ACCEPTED,
    STATUS_3YC_ACTIVE,
    STATUS_3YC_COMMITTED,
    STATUS_3YC_REQUESTED,
    STATUS_SUBSCRIPTION_TERMINATED,
)
from adobe_vipm.adobe.errors import AuthorizationNotFoundError, CustomerDiscountsNotFoundError
from adobe_vipm.adobe.utils import get_3yc_commitment
from adobe_vipm.airtable.models import (
    get_adobe_product_by_marketplace_sku,
    get_sku_price,
)
from adobe_vipm.flows.constants import (
    PARAM_3YC_END_DATE,
    PARAM_3YC_ENROLL_STATUS,
    PARAM_ADOBE_SKU,
    PARAM_COTERM_DATE,
    PARAM_CURRENT_QUANTITY,
    PARAM_DEPLOYMENT_ID,
    PARAM_LAST_SYNC_DATE,
    PARAM_NEXT_SYNC_DATE,
    PARAM_PHASE_FULFILLMENT,
    PARAM_RENEWAL_DATE,
    PARAM_RENEWAL_QUANTITY,
)
from adobe_vipm.flows.mpt import get_agreements_by_3yc_enroll_status
from adobe_vipm.flows.utils import (
    get_3yc_fulfillment_parameters,
    get_adobe_customer_id,
    get_deployments,
    get_global_customer,
    get_sku_with_discount_level,
    notify_agreement_unhandled_exception_in_teams,
    notify_missing_prices,
)

TEMP_3YC_STATUSES = (STATUS_3YC_REQUESTED, STATUS_3YC_ACCEPTED)

logger = logging.getLogger(__name__)


def sync_agreement_prices(mpt_client, agreement, dry_run, adobe_client, customer):
    """
    Updates the purchase prices of an Agreement (subscriptions and One-Time items)
    based on the customer discount level and customer benefits (3yc).

    Args:
        mpt_client (MPTClient): The client used to consume the MPT API.
        agreement (dict): The agreement to update.
        dry_run (bool): if True, it just simulate the prices update but doesn't
        perform it.
        adobe_client (AdobeClient): The client used to consume the Adobe API.
        customer (dict): The Adobe customer information.

    Returns:
        str: Returns the customer coterm date.
    """
    agreement_id = agreement["id"]
    missing_prices_skus = []

    authorization_id = agreement["authorization"]["id"]
    customer_id = get_adobe_customer_id(agreement)
    currency = agreement["listing"]["priceList"]["currency"]
    product_id = agreement["product"]["id"]
    subscriptions = agreement["subscriptions"]

    commitment = get_3yc_commitment(customer)
    commitment_start_date = None
    if (
        commitment
        and commitment["status"] in (STATUS_3YC_COMMITTED, STATUS_3YC_ACTIVE)
        and date.fromisoformat(commitment["endDate"]) >= date.today()
    ):
        commitment_start_date = date.fromisoformat(commitment["startDate"])

    coterm_date = customer["cotermDate"]

    to_update = []

    for subscription in subscriptions:
        if subscription["status"] == "Terminated":
            continue

        subscription = get_agreement_subscription(mpt_client, subscription["id"])
        adobe_subscription_id = subscription["externalIds"]["vendor"]

        adobe_subscription = adobe_client.get_subscription(
            authorization_id,
            customer_id,
            adobe_subscription_id,
        )

        if adobe_subscription["status"] == STATUS_SUBSCRIPTION_TERMINATED:
            logger.info(f"Skipping subscription {subscription['id']}. It is terminated by Adobe.")

        actual_sku = adobe_subscription["offerId"]

        to_update.append(
            (subscription, adobe_subscription, get_sku_with_discount_level(actual_sku, customer))
        )

    skus = [item[2] for item in to_update]

    prices = get_sku_price(customer, skus, product_id, currency)

    last_sync_date = datetime.now().date().isoformat()

    for subscription, adobe_subscription, actual_sku in to_update:
        if actual_sku not in prices:
            logger.error(
                f"Skipping subscription {subscription['id']} "
                f"because the sku {actual_sku} is not in the prices"
            )
            missing_prices_skus.append(actual_sku)
            continue

        line_id = subscription["lines"][0]["id"]
        lines = [
            {
                "price": {"unitPP": prices[actual_sku]},
                "id": line_id,
            }
        ]

        parameters = {
            "fulfillment": [
                {
                    "externalId": PARAM_ADOBE_SKU,
                    "value": actual_sku,
                },
                {
                    "externalId": PARAM_CURRENT_QUANTITY,
                    "value": str(adobe_subscription["currentQuantity"]),
                },
                {
                    "externalId": PARAM_RENEWAL_QUANTITY,
                    "value": str(adobe_subscription["autoRenewal"]["renewalQuantity"]),
                },
                {
                    "externalId": PARAM_RENEWAL_DATE,
                    "value": str(adobe_subscription["renewalDate"]),
                },
                {"externalId": "lastSyncDate", "value": last_sync_date},
            ],
        }

        if not dry_run:
            update_agreement_subscription(
                mpt_client,
                subscription["id"],
                lines=lines,
                parameters=parameters,
                commitmentDate=coterm_date,
                autoRenew=adobe_subscription["autoRenewal"]["enabled"],
            )
            logger.info(f"Subscription: {subscription['id']} ({line_id}): sku={actual_sku}")
        else:
            current_price = subscription["lines"][0]["price"]["unitPP"]
            sys.stdout.write(
                f"Subscription: {subscription['id']} ({line_id}): "
                f"sku={actual_sku}, "
                f"current_price={current_price}, "
                f"new_price={prices[actual_sku]}, "
                f"auto_renew={adobe_subscription['autoRenewal']['enabled']}, "
                f"current_quantity={adobe_subscription['currentQuantity']}, "
                f"renewal_quantity={adobe_subscription['autoRenewal']['renewalQuantity']}, "
                f"renewal_date={str(adobe_subscription['renewalDate'])}, "
                f"commitment_date={coterm_date}\n"
            )

    to_update = []
    for line in agreement["lines"]:
        actual_sku = get_adobe_product_by_marketplace_sku(line["item"]["externalIds"]["vendor"]).sku
        to_update.append((line, get_sku_with_discount_level(actual_sku, customer)))

    skus = [item[1] for item in to_update]

    prices = get_sku_price(customer, skus, product_id, currency)

    for line, actual_sku in to_update:
        current_price = line["price"]["unitPP"]
        line["price"]["unitPP"] = prices[actual_sku]

        if dry_run:
            sys.stdout.write(
                f"OneTime item: {line['id']}: "
                f"sku={actual_sku}, "
                f"current_price={current_price}, "
                f"new_price={prices[actual_sku]}\n",
            )
        else:
            logger.info(f"OneTime item: {line['id']}: sku={actual_sku}\n")

    next_sync = (datetime.fromisoformat(coterm_date) + timedelta(days=1)).date().isoformat()
    if not dry_run:
        update_agreement(
            mpt_client,
            agreement["id"],
            lines=agreement["lines"],
            parameters={"fulfillment": [{"externalId": "nextSync", "value": next_sync}]},
        )

    if missing_prices_skus:
        notify_missing_prices(
            agreement_id,
            missing_prices_skus,
            product_id,
            currency,
            commitment_start_date,
        )

    logger.info(f"agreement updated {agreement['id']}")
    return coterm_date


def sync_agreements_by_next_sync(mpt_client, dry_run):
    """
    Get all the agreements which nextSync date fullfilment parameter
    has passed to update the prices for them.

    Args:
        mpt_client (MPTClient): The client used to consume the MPT API.
        dry_run (bool): if True, it just simulate the prices update but doesn't
        perform it.
    """
    agreements = get_agreements_by_next_sync(mpt_client, PARAM_NEXT_SYNC_DATE)
    for agreement in agreements:
        sync_agreement(mpt_client, agreement, dry_run)


def sync_agreements_by_3yc_end_date(mpt_client: MPTClient, dry_run: bool):
    """
    Synchronizes agreements by their active subscriptions renewed yesterday.
    """
    logger.info("Syncing agreements by 3yc End Date...")
    _sync_agreements_by_param(mpt_client, PARAM_3YC_END_DATE, dry_run)


def sync_agreements_by_coterm_date(mpt_client: MPTClient, dry_run: bool):
    """
    Synchronizes agreements by their active subscriptions renewed yesterday.
    """
    logger.info("Synchronizing agreements by cotermDate...")
    _sync_agreements_by_param(mpt_client, PARAM_COTERM_DATE, dry_run)


def _sync_agreements_by_param(mpt_client: MPTClient, param, dry_run: bool):
    today = datetime.now().date().isoformat()
    yesterday = (datetime.now() - timedelta(days=1)).date().isoformat()
    rql_query = (
        "eq(status,Active)&"
        f"any(parameters.fulfillment,and(eq(externalId,{param}),eq(displayValue,{yesterday})))&"
        f"any(parameters.fulfillment,and(eq(externalId,{PARAM_LAST_SYNC_DATE}),ne(displayValue,{today})))&"
        # Let's get only what we need
        "select=subscriptions,authorization,parameters,listing,lines,"
        "-template,-name,-status,-authorization,-vendor,-client,-price,-licensee,-buyer,-seller,"
        "-externalIds"
    )
    for agreement in get_agreements_by_query(mpt_client, rql_query):
        logger.debug(f"Syncing {agreement=}")
        sync_agreement(mpt_client, agreement, dry_run)


def sync_agreements_by_renewal_date(mpt_client: MPTClient, dry_run: bool):
    """
    Synchronizes agreements by their active subscriptions renewed yesterday.
    """
    logger.info("Synchronizing agreements by renewal date...")
    today = datetime.now().date().isoformat()
    yesterday = (datetime.now() - timedelta(days=1)).date().isoformat()
    rql_query = (
        "eq(status,Active)&"
        f"any(subscriptions,any(parameters.fulfillment,and(eq(externalId,renewalDate),eq(displayValue,{yesterday})))&"
        f"any(parameters.fulfillment,and(eq(externalId,{PARAM_LAST_SYNC_DATE}),ne(displayValue,{today})))&"
        # Let's get only what we need
        "select=subscriptions,authorization,parameters,listing,lines,"
        "-template,-name,-status,-authorization,-vendor,-client,-price,-licensee,-buyer,-seller,"
        "-externalIds"
    )
    for agreement in get_agreements_by_query(mpt_client, rql_query):
        logger.debug(f"Syncing {agreement=}")
        sync_agreement(mpt_client, agreement, dry_run)


def sync_agreements_by_agreement_ids(mpt_client, ids, dry_run=False):
    """
    Get the agreements given a list of agreement IDs
    to update the prices for them.

    Args:
        mpt_client (MPTClient): The client used to consume the MPT API.
        ids (list): List of agreement IDs.
        dry_run (bool): if True, it just simulate the prices update but doesn't
        perform it.
    """
    agreements = get_agreements_by_ids(mpt_client, ids)
    for agreement in agreements:
        sync_agreement(mpt_client, agreement, dry_run)


def sync_agreements_by_3yc_enroll_status(mpt_client: MPTClient, dry_run: bool = True) -> None:
    """
    This function retrieves agreements filtered by their 3YC enrollment status and synchronizes
    their corresponding statuses.
    """
    try:
        agreements = get_agreements_by_3yc_enroll_status(mpt_client, TEMP_3YC_STATUSES)
    except Exception as e:
        logger.exception(f"Unknown exception getting agreements by 3YC enroll status: {e}")
        raise
    for agreement in agreements:
        try:
            logger.info(f"Checking 3YC enroll status for agreement {agreement['id']}")
            _sync_3yc_enroll_status(mpt_client, agreement, dry_run)
        except AuthorizationNotFoundError as e:
            logger.error(
                f"AuthorizationNotFoundError synchronizing 3YC enroll status for agreement"
                f" {agreement['id']}: {e}"
            )
        except Exception as e:
            logger.exception(
                f"Unknown exception synchronizing 3YC enroll status for agreement"
                f" {agreement['id']}: {e}"
            )


def _sync_3yc_enroll_status(mpt_client: MPTClient, agreement: dict, dry_run: bool) -> None:
    adobe_client = get_adobe_client()
    customer = adobe_client.get_customer(
        authorization_id=agreement["authorization"]["id"],
        customer_id=get_adobe_customer_id(agreement),
    )
    commitment = get_3yc_commitment(customer)
    enroll_status = commitment["status"]
    logger.debug(
        f"Commitment Status for Adobe customer {customer['customerId']} is {enroll_status}"
    )

    if enroll_status in TEMP_3YC_STATUSES:
        logger.info(f"Updating 3YC enroll status for agreement {agreement['id']}")
        if not dry_run:
            update_agreement(
                mpt_client,
                agreement["id"],
                parameters={
                    PARAM_PHASE_FULFILLMENT: [
                        {"externalId": PARAM_3YC_ENROLL_STATUS, "value": enroll_status}
                    ]
                },
            )
    else:
        sync_agreement(mpt_client, agreement, dry_run)


def sync_global_customer_parameters(mpt_client, customer_deployments, agreement):
    try:
        parameters = {PARAM_PHASE_FULFILLMENT: []}
        global_customer_enabled = get_global_customer(agreement)
        if global_customer_enabled != ["Yes"]:
            logger.info(f"Setting global customer for agreement {agreement["id"]}")
            parameters[PARAM_PHASE_FULFILLMENT].append(
                {"externalId": "globalCustomer", "value": ["Yes"]}
            )

        deployments = [
            f'{deployment["deploymentId"]} - {deployment["companyProfile"]["address"]["country"]}'
            for deployment in customer_deployments
        ]
        agreement_deployments = get_deployments(agreement)
        if deployments != agreement_deployments:
            parameters[PARAM_PHASE_FULFILLMENT].append(
                {"externalId": "deployments", "value": ",".join(deployments)}
            )
            logger.info(f"Setting deployments for agreement {agreement["id"]}")
        if parameters[PARAM_PHASE_FULFILLMENT]:
            update_agreement(mpt_client, agreement["id"], parameters=parameters)
    except Exception as e:
        logger.exception(
            f"Error setting global customer parameters for agreement {agreement["id"]}: {e}"
        )
        notify_agreement_unhandled_exception_in_teams(agreement["id"], traceback.format_exc())


def sync_agreement(mpt_client, agreement, dry_run):
    try:
        logger.debug(f"Syncing {agreement=}")
        customer_id = get_adobe_customer_id(agreement)
        adobe_client = get_adobe_client()
        logger.info(f"Synchronizing agreement {agreement["id"]}...")

        processing_subscriptions = list(
            filter(
                lambda sub: sub["status"] in ("Updating", "Terminating"),
                agreement["subscriptions"],
            ),
        )

        if len(processing_subscriptions) > 0:
            logger.info(f"Agreement {agreement["id"]} has processing subscriptions, skip it")
            return

        customer = adobe_client.get_customer(agreement["authorization"]["id"], customer_id)

        if not customer.get("discounts", []):
            raise CustomerDiscountsNotFoundError(
                f"Customer {customer_id} does not have discounts information. "
                f"Cannot proceed with price synchronization for the agreement {agreement['id']}."
            )

        sync_agreement_prices(mpt_client, agreement, dry_run, adobe_client, customer)

        if customer.get("globalSalesEnabled", False):
            authorization_id = agreement["authorization"]["id"]
            customer_deployments = adobe_client.get_customer_deployments_active_status(
                authorization_id, customer_id
            )
            sync_global_customer_parameters(mpt_client, customer_deployments, agreement)
            sync_deployments_prices(
                mpt_client,
                adobe_client,
                agreement,
                customer,
                customer_deployments,
                dry_run,
            )

    except Exception as e:
        logger.exception(f"Error synchronizing agreement {agreement["id"]}: {e}")
        notify_agreement_unhandled_exception_in_teams(agreement["id"], traceback.format_exc())
    else:
        if not dry_run:
            _update_last_sync_date(mpt_client, agreement)


def _update_last_sync_date(mpt_client: MPTClient, agreement: dict) -> None:
    logger.info(f"Updating Last Sync Date for agreement {agreement['id']}")
    update_agreement(
        mpt_client,
        agreement["id"],
        parameters={
            "fulfillment": [
                {"externalId": "lastSyncDate", "value": datetime.now().date().isoformat()}
            ]
        },
    )


def sync_deployments_prices(
    mpt_client, adobe_client, main_agreement, customer, customer_deployments, dry_run
):
    if not customer_deployments:
        return

    deployment_agreements = get_agreements_by_customer_deployments(
        mpt_client,
        PARAM_DEPLOYMENT_ID,
        [deployment["deploymentId"] for deployment in customer_deployments],
    )

    for deployment_agreement in deployment_agreements:
        sync_agreement_prices(mpt_client, deployment_agreement, dry_run, adobe_client, customer)
        sync_gc_3yc_agreements(
            mpt_client,
            main_agreement,
            deployment_agreement,
            dry_run,
        )


def sync_gc_3yc_agreements(mpt_client, main_agreement, deployment_agreement, dry_run):
    parameters_3yc = get_3yc_fulfillment_parameters(main_agreement)

    if not dry_run:
        update_agreement(
            mpt_client,
            deployment_agreement["id"],
            parameters={
                "fulfillment": parameters_3yc,
            },
        )


def sync_all_agreements(mpt_client, dry_run):
    """
    Get all the active agreements to update the prices for them.

    Args:
        mpt_client (MPTClient): The client used to consume the MPT API.
        dry_run (bool): if True, it just simulate the prices update but doesn't
        perform it.
    """
    agreements = get_all_agreements(mpt_client)
    for agreement in agreements:
        sync_agreement(mpt_client, agreement, dry_run)
