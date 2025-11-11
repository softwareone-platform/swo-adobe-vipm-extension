import datetime as dt
import logging

from dateutil.relativedelta import relativedelta
from mpt_extension_sdk.mpt_http import mpt
from mpt_extension_sdk.mpt_http.base import MPTClient

from adobe_vipm import notifications
from adobe_vipm.adobe.client import AdobeClient
from adobe_vipm.adobe.constants import THREE_YC_TEMP_3YC_STATUSES, AdobeStatus
from adobe_vipm.adobe.errors import AdobeAPIError, AuthorizationNotFoundError
from adobe_vipm.flows.constants import Param, SubscriptionStatus
from adobe_vipm.flows.mpt import get_agreements_by_3yc_commitment_request_invitation
from adobe_vipm.flows.sync.agreement import AgreementsSyncer
from adobe_vipm.flows.utils import get_adobe_customer_id

logger = logging.getLogger(__name__)


def sync_agreements_by_3yc_end_date(
    mpt_client: MPTClient, adobe_client: AdobeClient, *, dry_run: bool
) -> None:
    """
    Synchronizes agreements by their active subscriptions renewed yesterday.

    Args:
        adobe_client: Adobe Client
        mpt_client: MPT API client.
        dry_run: Run in dry run mode.
    """
    logger.info("Syncing agreements by 3yc End Date...")
    _sync_agreements_by_param(
        mpt_client, adobe_client, Param.THREE_YC_END_DATE.value, dry_run=dry_run, sync_prices=True
    )


def sync_agreements_by_coterm_date(
    mpt_client: MPTClient, adobe_client: AdobeClient, *, dry_run: bool
) -> None:
    """
    Synchronizes agreements by their active subscriptions renewed yesterday.

    Args:
        adobe_client: Adobe API client.
        mpt_client: MPT API client.
        dry_run: Run in dry run mode.
    """
    logger.info("Synchronizing agreements by cotermDate...")
    _sync_agreements_by_param(
        mpt_client, adobe_client, Param.COTERM_DATE.value, dry_run=dry_run, sync_prices=True
    )


def _sync_agreements_by_param(
    mpt_client: MPTClient,
    adobe_client: AdobeClient,
    param: Param,
    *,
    dry_run: bool,
    sync_prices: bool,
) -> None:
    today = dt.datetime.now(tz=dt.UTC).date()
    today_iso = today.isoformat()
    yesterday = (today - dt.timedelta(days=1)).isoformat()
    rql_query = (
        "eq(status,Active)&"
        f"any(parameters.fulfillment,and(eq(externalId,{param}),eq(displayValue,{yesterday})))&"
        f"any(parameters.fulfillment,and(eq(externalId,{Param.LAST_SYNC_DATE.value}),ne(displayValue,{today_iso})))&"
        # Let's get only what we need
        "select=lines,parameters,subscriptions,product,listing"
    )
    for agreement in mpt.get_agreements_by_query(mpt_client, rql_query):
        sync_agreement(
            mpt_client, adobe_client, agreement, dry_run=dry_run, sync_prices=sync_prices
        )


def sync_agreements_by_renewal_date(
    mpt_client: MPTClient, adobe_client: AdobeClient, *, dry_run: bool
) -> None:
    """
    Synchronizes agreements by their active subscriptions renewed yesterday.

    Args:
        adobe_client: Adobe API client used for API operations.
        mpt_client: MPT API client.
        dry_run: Run in dry run mode.
    """
    logger.info("Synchronizing agreements by renewal date...")
    today_plus_1_year = dt.datetime.now(tz=dt.UTC).date() + relativedelta(years=1)
    today_iso = dt.datetime.now(tz=dt.UTC).date().isoformat()
    yesterday_every_month = (
        (today_plus_1_year - dt.timedelta(days=1) - relativedelta(months=month)).isoformat()
        for month in range(24)
    )

    rql_query = (
        "eq(status,Active)&"
        f"any(subscriptions,any(parameters.fulfillment,and(eq(externalId,renewalDate),in(displayValue,({','.join(yesterday_every_month)}))))&"
        f"any(parameters.fulfillment,and(eq(externalId,{Param.LAST_SYNC_DATE.value}),ne(displayValue,{today_iso})))&"
        # Let's get only what we need
        "select=lines,parameters,subscriptions,product,listing"
    )
    for agreement in mpt.get_agreements_by_query(mpt_client, rql_query):
        sync_agreement(mpt_client, adobe_client, agreement, dry_run=dry_run, sync_prices=True)


def sync_agreements_by_agreement_ids(
    mpt_client: MPTClient,
    adobe_client: AdobeClient,
    ids: list[str],
    *,
    dry_run: bool,
    sync_prices: bool,
) -> None:
    """
    Get the agreements given a list of agreement IDs to update the prices for them.

    Args:
        adobe_client: Adobe Client
        mpt_client: The client used to consume the MPT API.
        ids: List of agreement IDs.
        dry_run: if True, it just simulate the prices update but doesn't
        perform it.
        sync_prices: if True also sync prices.
    """
    agreements = mpt.get_agreements_by_ids(mpt_client, ids)
    for agreement in agreements:
        sync_agreement(
            mpt_client, adobe_client, agreement, dry_run=dry_run, sync_prices=sync_prices
        )


def sync_agreements_by_3yc_enroll_status(
    mpt_client: MPTClient, adobe_client: AdobeClient, *, dry_run: bool
) -> None:
    """
    This function retrieves agreements filtered by their 3YC enrollment status.

    Synchronizes their corresponding statuses.

    Args:
        adobe_client: Adobe Client
        mpt_client: MPT API client.
        dry_run: if True, it just simulate parameters update.
    """
    try:
        agreements = get_agreements_by_3yc_commitment_request_invitation(
            mpt_client, THREE_YC_TEMP_3YC_STATUSES
        )
    except Exception:
        logger.exception("Unknown exception getting agreements by 3YC enroll status.")
        raise
    for agreement in agreements:
        try:
            sync_agreement(mpt_client, adobe_client, agreement, dry_run=dry_run, sync_prices=True)
        except AuthorizationNotFoundError:
            logger.exception(
                "AuthorizationNotFoundError synchronizing 3YC enroll status for agreement %s",
                agreement["id"],
            )
        except Exception:
            logger.exception(
                "Unknown exception synchronizing 3YC enroll status for agreement %s",
                agreement["id"],
            )


def sync_all_agreements(mpt_client: MPTClient, adobe_client: AdobeClient, *, dry_run: bool) -> None:
    """
    Get all the active agreements to update the prices for them.

    Args:
        mpt_client: The client used to consume the MPT API.
        adobe_client: The Adobe API client.
        dry_run: if True, it just simulate the prices update but doesn't
        perform it.
    """
    agreements = mpt.get_all_agreements(mpt_client)
    for agreement in agreements:
        sync_agreement(mpt_client, adobe_client, agreement, dry_run=dry_run, sync_prices=False)


# REFACTOR: Split this method to separate the get and process responsibilities.
def get_customer_or_process_lost_customer(
    mpt_client: MPTClient,
    adobe_client: AdobeClient,
    agreement: dict,
    customer_id: str,
    *,
    dry_run: bool,
) -> dict | None:
    """
    Attempts to retrieve the customer using Adobe Client.

    Args:
        mpt_client: An instance of MPTClient used for managing lost customer processes.
        adobe_client: An instance of AdobeClient used for retrieving customer information.
        agreement: A dictionary containing the agreement details, including authorization
            information necessary for fetching customer data.
        customer_id: The unique identifier of the customer to be retrieved.
        dry_run: if True, it just simulates the process

    Returns:
        dict | None: Returns the customer details as a dictionary if successful. Returns
        None if the customer is determined to be invalid and the lost customer procedure
        is initiated.

    Raises:
        AdobeAPIError: If an error occurs during the customer retrieval process that is
        not related to invalid customer status.
    """
    try:
        return adobe_client.get_customer(agreement["authorization"]["id"], customer_id)
    # TODO: add AuthorizationNotFoundError error
    except AdobeAPIError as error:
        if error.code == AdobeStatus.INVALID_CUSTOMER:
            logger.info(
                "Received Adobe error %s - %s, assuming lost customer "
                "and proceeding with lost customer procedure.",
                error.code,
                error.message,
            )
            if dry_run:
                logger.info("Dry run mode: skipping processing lost customer %s.", customer_id)
                return None

            notifications.send_warning(
                "Executing Lost Customer Procedure.",
                f"Received Adobe error {error.code} - {error.message},"
                " assuming lost customer and proceeding with lost customer procedure.",
            )
            _process_lost_customer(mpt_client, adobe_client, agreement, customer_id)
            return None
        raise


def sync_agreement(
    mpt_client: MPTClient,
    adobe_client: AdobeClient,
    agreement: dict,
    *,
    dry_run: bool,
    sync_prices: bool,
):
    """
    Synchronizes a specific agreement with Adobe and MPT clients based on the given parameters.

    Args:
        mpt_client (MPTClient): Client interface to work with MPT data and services.
        adobe_client (AdobeClient): Client interface to interact with Adobe services.
        agreement (dict): A dictionary representing the agreement details to synchronize.
        dry_run (bool): Flag indicating whether to execute in dry-run mode (no actual changes).
        sync_prices (bool): Flag indicating whether to synchronize subscription prices.
    """
    adobe_customer_id = get_adobe_customer_id(agreement)
    customer = get_customer_or_process_lost_customer(
        mpt_client, adobe_client, agreement, adobe_customer_id, dry_run=dry_run
    )
    if not customer:
        return

    authorization_id: str = agreement["authorization"]["id"]
    adobe_subscriptions = adobe_client.get_subscriptions(authorization_id, adobe_customer_id)[
        "items"
    ]

    AgreementsSyncer(
        mpt_client, adobe_client, agreement, customer, adobe_subscriptions, dry_run=dry_run
    ).sync(sync_prices=sync_prices)


def _process_lost_customer(  # noqa: C901
    mpt_client: MPTClient,
    adobe_client: AdobeClient,
    agreement: dict,
    customer_id: str,
) -> None:
    """
    Process lost customer exception from Adobe API.

    If agreement exists in MPT, but doesn't exist in Adobe API it should terminate all agreement
    subscriptions. Agreement itself is terminated automatically after all subscriptions
    are terminated.

    Args:
        mpt_client: MPT API client.
        adobe_client: Adobe API client.
        agreement: MPT agreement.
        customer_id: Adobe customer id.
    """
    for subscription_id in [
        sub["id"]
        for sub in agreement["subscriptions"]
        if sub["status"] != SubscriptionStatus.TERMINATED
    ]:
        logger.info("> Suspected Lost Customer: Terminating subscription %s.", subscription_id)
        try:
            mpt.terminate_subscription(
                mpt_client,
                subscription_id,
                "Suspected Lost Customer",
            )
        except Exception as error:
            logger.exception(
                "> Suspected Lost Customer: Error terminating subscription %s.",
                subscription_id,
            )
            notifications.send_exception(
                f"> Suspected Lost Customer: Error terminating subscription {subscription_id}",
                f"{error}",
            )

    adobe_deployments = adobe_client.get_customer_deployments_active_status(
        agreement["authorization"]["id"], customer_id
    )
    if adobe_deployments:
        deployment_agreements = mpt.get_agreements_by_customer_deployments(
            mpt_client,
            Param.DEPLOYMENT_ID.value,
            [deployment["deploymentId"] for deployment in adobe_deployments],
        )

        for deployment_agreement in deployment_agreements:
            for subscription_id in [
                sub["id"]
                for sub in deployment_agreement["subscriptions"]
                if sub["status"] != SubscriptionStatus.TERMINATED
            ]:
                try:
                    mpt.terminate_subscription(
                        mpt_client, subscription_id, "Suspected Lost Customer"
                    )
                except Exception as error:
                    logger.exception(
                        "> Suspected Lost Customer: Error terminating subscription %s.",
                        subscription_id,
                    )
                    notifications.send_exception(
                        "> Suspected Lost Customer: Error terminating subscription"
                        f" {subscription_id}",
                        f"{error}",
                    )
