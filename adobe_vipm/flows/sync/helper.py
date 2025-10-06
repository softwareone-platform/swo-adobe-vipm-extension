import datetime as dt
import logging

from dateutil.relativedelta import relativedelta
from mpt_extension_sdk.mpt_http import mpt
from mpt_extension_sdk.mpt_http.base import MPTClient

from adobe_vipm.adobe.client import AdobeClient
from adobe_vipm.adobe.constants import THREE_YC_TEMP_3YC_STATUSES
from adobe_vipm.adobe.errors import (
    AuthorizationNotFoundError,
)
from adobe_vipm.flows.constants import (
    Param,
)
from adobe_vipm.flows.mpt import get_agreements_by_3yc_commitment_request_invitation
from adobe_vipm.flows.sync.agreement import AgreementSyncer

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
        AgreementSyncer(mpt_client, adobe_client, agreement).sync(
            dry_run=dry_run, sync_prices=sync_prices
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
        AgreementSyncer(mpt_client, adobe_client, agreement).sync(dry_run=dry_run, sync_prices=True)


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
        AgreementSyncer(mpt_client, adobe_client, agreement).sync(
            dry_run=dry_run, sync_prices=sync_prices
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
            AgreementSyncer(mpt_client, adobe_client, agreement).sync(
                dry_run=dry_run, sync_prices=True
            )
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
        AgreementSyncer(mpt_client, adobe_client, agreement).sync(
            dry_run=dry_run, sync_prices=False
        )
