import copy
import datetime as dt
import logging
import sys
import traceback
from collections.abc import Sequence
from functools import partial

from dateutil.relativedelta import relativedelta
from mpt_extension_sdk.mpt_http.base import MPTClient
from mpt_extension_sdk.mpt_http.mpt import (
    create_agreement_subscription,
    get_agreement_subscription,
    get_agreements_by_customer_deployments,
    get_agreements_by_ids,
    get_agreements_by_query,
    get_all_agreements,
    get_product_items_by_period,
    get_product_items_by_skus,
    terminate_subscription,
    update_agreement,
    update_agreement_subscription,
)
from mpt_extension_sdk.mpt_http.utils import find_first

from adobe_vipm.adobe.client import AdobeClient, get_adobe_client
from adobe_vipm.adobe.constants import THREE_YC_TEMP_3YC_STATUSES, AdobeStatus
from adobe_vipm.adobe.errors import (
    AdobeAPIError,
    AuthorizationNotFoundError,
    CustomerDiscountsNotFoundError,
)
from adobe_vipm.adobe.utils import get_3yc_commitment_request
from adobe_vipm.airtable import models
from adobe_vipm.flows.constants import AgreementStatus, Param, SubscriptionStatus, TeamsColorCode
from adobe_vipm.flows.mpt import get_agreements_by_3yc_enroll_status
from adobe_vipm.flows.utils import (
    get_3yc_fulfillment_parameters,
    get_adobe_customer_id,
    get_deployment_id,
    get_deployments,
    get_fulfillment_parameter,
    get_global_customer,
    get_parameter,
    get_sku_with_discount_level,
    notify_agreement_unhandled_exception_in_teams,
    notify_missing_prices,
)
from adobe_vipm.notifications import send_exception, send_notification
from adobe_vipm.utils import get_3yc_commitment, get_commitment_start_date, get_partial_sku

logger = logging.getLogger(__name__)


def _add_missing_subscriptions(
    mpt_client: MPTClient,
    adobe_client: AdobeClient,
    customer: dict,
    agreement: dict,
    adobe_subscriptions,
) -> None:
    deployment_id = get_deployment_id(agreement) or ""
    logger.info(
        "Checking missing subscriptions for agreement=%s, deployment=%s",
        agreement["id"],
        deployment_id,
    )
    adobe_subscriptions = tuple(
        a_s for a_s in adobe_subscriptions if a_s.get("deploymentId", "") == deployment_id
    )
    skus = {get_partial_sku(item["offerId"]) for item in adobe_subscriptions}
    one_time_skus = get_one_time_skus(
        mpt_client, agreement["product"]["id"], vendor_external_ids=skus
    )
    mpt_subscriptions_external_ids = {
        subscription["externalIds"]["vendor"] for subscription in agreement["subscriptions"]
    }
    missing_subscriptions = tuple(
        subsc
        for subsc in adobe_subscriptions
        if subsc["subscriptionId"] not in mpt_subscriptions_external_ids
        and subsc["status"] == AdobeStatus.SUBSCRIPTION_ACTIVE.value
        and get_partial_sku(subsc["offerId"]) not in one_time_skus
    )
    skus = {sku for sku in skus if sku not in one_time_skus}

    if missing_subscriptions:
        logger.warning("> Found missing subscriptions")
    else:
        logger.info("> No missing subscriptions found")
        return
    items_map = {
        item["externalIds"]["vendor"]: item
        for item in get_product_items_by_skus(mpt_client, agreement["product"]["id"], skus)
    }
    offer_ids = [
        get_sku_with_discount_level(adobe_subscription["offerId"], customer)
        for adobe_subscription in missing_subscriptions
    ]

    for adobe_subscription in missing_subscriptions:
        logger.info(">> Adding missing subscription %s", adobe_subscription["subscriptionId"])

        if adobe_subscription["currencyCode"] != agreement["listing"]["priceList"]["currency"]:
            logger.warning(
                "Skipping adobe subscription %s due to  currency mismatch.",
                adobe_subscription["subscriptionId"],
            )
            adobe_client.update_subscription(
                agreement["authorization"]["id"],
                customer["customerId"],
                adobe_subscription["subscriptionId"],
                auto_renewal=False,
            )

            send_exception(title="Price currency mismatch detected!", text=f"{adobe_subscription}")
            continue

        item = items_map[get_partial_sku(adobe_subscription["offerId"])]
        prices = models.get_sku_price(
            customer,
            offer_ids,
            agreement["product"]["id"],
            agreement["listing"]["priceList"]["currency"],
        )
        sku_discount_level = get_sku_with_discount_level(adobe_subscription["offerId"], customer)
        price_component = {"price": {"unitPP": prices[sku_discount_level]}}
        create_agreement_subscription(
            mpt_client,
            {
                "status": SubscriptionStatus.ACTIVE.value,
                "commitmentDate": adobe_subscription["renewalDate"],
                "price": {"unitPP": prices},
                "parameters": {
                    "fulfillment": [
                        {
                            "externalId": Param.ADOBE_SKU.value,
                            "value": sku_discount_level,
                        },
                        {
                            "externalId": Param.CURRENT_QUANTITY.value,
                            "value": str(adobe_subscription[Param.CURRENT_QUANTITY.value]),
                        },
                        {
                            "externalId": Param.RENEWAL_QUANTITY.value,
                            "value": str(
                                adobe_subscription["autoRenewal"][Param.RENEWAL_QUANTITY.value]
                            ),
                        },
                        {
                            "externalId": Param.RENEWAL_DATE.value,
                            "value": str(adobe_subscription["renewalDate"]),
                        },
                    ]
                },
                "agreement": {"id": agreement["id"]},
                "buyer": {"id": agreement["buyer"]["id"]},
                "licensee": {"id": agreement["licensee"]["id"]},
                "seller": {"id": agreement["seller"]["id"]},
                "lines": [
                    {
                        "quantity": adobe_subscription[Param.CURRENT_QUANTITY.value],
                        "item": item,
                        **price_component,
                    }
                ],
                "name": f"Subscription for {item.get('name')}",
                "startDate": adobe_subscription["creationDate"],
                "externalIds": {"vendor": adobe_subscription["subscriptionId"]},
                "product": {"id": agreement["product"]["id"]},
                "autoRenew": adobe_subscription["autoRenewal"]["enabled"],
            },
        )


def sync_agreement_prices(
    mpt_client: MPTClient,
    adobe_client: AdobeClient,
    agreement: dict,
    customer: dict,
    subscriptions_for_update: Sequence[dict],
    *,
    dry_run: bool,
) -> None:
    """
    Updates the purchase prices of an Agreement (subscriptions and One-Time items).

    Based on the customer discount level and customer benefits (3yc).

    Args:
        subscriptions_for_update: subscriptions for update
        mpt_client: MPT API client.
        adobe_client: Adobe API client.
        agreement: MPT agreement.
        customer: Adobe customer.
        dry_run: Run command in a dry run mode
    """
    commitment_start_date = get_commitment_start_date(customer)

    product_id = agreement["product"]["id"]
    currency = agreement["listing"]["priceList"]["currency"]

    _update_subscriptions(
        mpt_client,
        customer,
        currency,
        product_id,
        agreement_id=agreement["id"],
        commitment_start_date=commitment_start_date,
        subscriptions_for_update=subscriptions_for_update,
        dry_run=dry_run,
    )

    _log_agreement_lines(agreement, currency, customer, product_id, dry_run=dry_run)


def _update_agreement(
    mpt_client: MPTClient,
    customer: dict,
    agreement: dict,
    *,
    dry_run: bool,
) -> None:
    parameters = {}
    commitment_info = get_3yc_commitment(customer)
    if commitment_info:
        parameters = _add_3yc_fulfillment_params(agreement, commitment_info, customer, parameters)
        for mq in commitment_info.get("minimumQuantities", ()):
            if mq["offerType"] == "LICENSE":
                parameters.setdefault(Param.PHASE_ORDERING.value, [])
                parameters[Param.PHASE_ORDERING.value].append({
                    "externalId": Param.THREE_YC_LICENSES.value,
                    "value": str(mq.get("quantity")),
                })
            if mq["offerType"] == "CONSUMABLES":
                parameters.setdefault(Param.PHASE_ORDERING.value, [])
                parameters[Param.PHASE_ORDERING.value].append({
                    "externalId": Param.THREE_YC_CONSUMABLES.value,
                    "value": str(mq.get("quantity")),
                })

    parameters.setdefault(Param.PHASE_FULFILLMENT.value, [])
    parameters[Param.PHASE_FULFILLMENT.value].append({
        "externalId": Param.COTERM_DATE.value,
        "value": customer.get("cotermDate", ""),
    })
    if not dry_run:
        update_agreement(
            mpt_client,
            agreement["id"],
            lines=agreement["lines"],
            parameters=parameters,
        )
    logger.info("Agreement updated %s", agreement["id"])


def _add_3yc_fulfillment_params(
    agreement: dict,
    commitment_info: dict,
    customer: dict,
    parameters: list[dict],
) -> list[dict]:
    new_parameters = copy.deepcopy(parameters)
    new_parameters.setdefault(Param.PHASE_FULFILLMENT.value, [])
    three_yc_recommitment_par = get_parameter(
        Param.PHASE_FULFILLMENT.value, agreement, Param.THREE_YC_RECOMMITMENT.value
    )
    is_recommitment = bool(three_yc_recommitment_par)
    status_param_ext_id = (
        Param.THREE_YC_COMMITMENT_REQUEST_STATUS.value
        if not is_recommitment
        else Param.THREE_YC_RECOMMITMENT_REQUEST_STATUS.value
    )
    request_type_param_ext_id = (
        Param.THREE_YC.value if not is_recommitment else Param.THREE_YC_RECOMMITMENT.value
    )
    request_type_param_phase = (
        Param.PHASE_ORDERING.value if not is_recommitment else Param.PHASE_FULFILLMENT.value
    )
    request_info = get_3yc_commitment_request(customer, is_recommitment=is_recommitment)
    new_parameters[Param.PHASE_FULFILLMENT.value].append({
        "externalId": status_param_ext_id,
        "value": request_info.get("status"),
    })
    new_parameters.setdefault(request_type_param_phase, [])
    new_parameters[request_type_param_phase].append(
        {"externalId": request_type_param_ext_id, "value": None},
    )
    new_parameters[Param.PHASE_FULFILLMENT.value] += [
        {
            "externalId": Param.THREE_YC_ENROLL_STATUS.value,
            "value": commitment_info.get("status"),
        },
        {
            "externalId": Param.THREE_YC_START_DATE.value,
            "value": commitment_info.get("startDate"),
        },
        {
            "externalId": Param.THREE_YC_END_DATE.value,
            "value": commitment_info.get("endDate"),
        },
    ]

    return new_parameters


def _log_agreement_lines(
    agreement: dict,
    currency: str,
    customer: dict,
    product_id: str,
    *,
    dry_run: bool,
) -> None:
    agreement_lines = []
    for line in agreement["lines"]:
        if line["item"]["externalIds"]["vendor"] != "adobe-reseller-transfer":
            actual_sku = models.get_adobe_sku(line["item"]["externalIds"]["vendor"])
            agreement_lines.append((line, get_sku_with_discount_level(actual_sku, customer)))

    skus = [item[1] for item in agreement_lines]
    prices = models.get_sku_price(customer, skus, product_id, currency)
    for line, actual_sku in agreement_lines:
        current_price = line["price"]["unitPP"]
        line["price"]["unitPP"] = prices[actual_sku]

        if dry_run:
            sys.stdout.write(
                f"OneTime item: {line['id']}: sku={actual_sku}, current_price={current_price}, "
                f"new_price={prices[actual_sku]}\n",
            )
        else:
            logger.info("OneTime item: %s: sku=%s\n", line["id"], actual_sku)


def _update_subscriptions(
    mpt_client: MPTClient,
    customer: dict,
    currency: str,
    product_id: str,
    agreement_id: str,
    commitment_start_date: dt.date,
    subscriptions_for_update: list[tuple[dict, dict, str]],
    *,
    dry_run: bool,
) -> None:
    skus = [item[2] for item in subscriptions_for_update]
    prices = models.get_sku_price(customer, skus, product_id, currency)
    missing_prices_skus = []
    coterm_date = customer["cotermDate"]

    for subscription, adobe_subscription, actual_sku in subscriptions_for_update:
        if actual_sku not in prices:
            logger.error(
                "Skipping subscription %s because the sku %s is not in the prices",
                subscription["id"],
                actual_sku,
            )
            missing_prices_skus.append(actual_sku)
            continue

        line_id = subscription["lines"][0]["id"]
        lines = [
            {
                "price": {"unitPP": prices[actual_sku]},
                "id": line_id,
                "quantity": adobe_subscription["autoRenewal"][Param.RENEWAL_QUANTITY.value],
            }
        ]

        parameters = {
            "fulfillment": [
                {"externalId": Param.ADOBE_SKU.value, "value": actual_sku},
                {
                    "externalId": Param.CURRENT_QUANTITY.value,
                    "value": str(adobe_subscription[Param.CURRENT_QUANTITY.value]),
                },
                {
                    "externalId": Param.RENEWAL_QUANTITY.value,
                    "value": str(adobe_subscription["autoRenewal"][Param.RENEWAL_QUANTITY.value]),
                },
                {
                    "externalId": Param.RENEWAL_DATE.value,
                    "value": str(adobe_subscription["renewalDate"]),
                },
                {
                    "externalId": Param.LAST_SYNC_DATE.value,
                    "value": dt.datetime.now(tz=dt.UTC).date().isoformat(),
                },
            ],
        }

        if not dry_run:
            logger.info(
                "Updating subscription: %s (%s): sku=%s",
                subscription["id"],
                line_id,
                actual_sku,
            )
            update_agreement_subscription(
                mpt_client,
                subscription["id"],
                lines=lines,
                parameters=parameters,
                commitmentDate=coterm_date,
                autoRenew=adobe_subscription["autoRenewal"]["enabled"],
            )
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
                f"renewal_date={adobe_subscription['renewalDate']}, "
                f"commitment_date={coterm_date}\n"
            )

    if missing_prices_skus:
        notify_missing_prices(
            agreement_id,
            missing_prices_skus,
            product_id,
            currency,
            commitment_start_date,
        )


def _check_adobe_subscription_id(subscription_id, adobe_subscription):
    return adobe_subscription.get("subscriptionId", "") == subscription_id


def _get_subscriptions_for_update(
    mpt_client: MPTClient, agreement: dict, customer: dict, adobe_subscriptions: Sequence[dict]
) -> list[tuple[dict, dict, str]]:
    logger.info("Getting subscriptions for update for agreement %s", agreement["id"])
    for_update = []

    for subscription in agreement["subscriptions"]:
        if subscription["status"] in {SubscriptionStatus.TERMINATED, SubscriptionStatus.EXPIRED}:
            continue

        mpt_subscription = get_agreement_subscription(mpt_client, subscription["id"])
        adobe_subscription_id = mpt_subscription["externalIds"]["vendor"]

        adobe_subscription = find_first(
            partial(_check_adobe_subscription_id, adobe_subscription_id),
            adobe_subscriptions,
        )

        if not adobe_subscription:
            logger.error("No subscription found in Adobe customer data!")
            continue

        actual_sku = adobe_subscription["offerId"]

        if adobe_subscription["status"] == AdobeStatus.SUBSCRIPTION_TERMINATED:
            logger.info("Processing terminated Adobe subscription %s.", adobe_subscription_id)
            terminate_subscription(
                mpt_client,
                mpt_subscription["id"],
                f"Adobe subscription status {AdobeStatus.SUBSCRIPTION_TERMINATED}.",
            )
            continue

        for_update.append((
            mpt_subscription,
            adobe_subscription,
            get_sku_with_discount_level(actual_sku, customer),
        ))

    return for_update


def sync_agreements_by_3yc_end_date(mpt_client: MPTClient, *, dry_run: bool) -> None:
    """
    Synchronizes agreements by their active subscriptions renewed yesterday.

    Args:
        mpt_client: MPT API client.
        dry_run: Run in dry run mode.
    """
    logger.info("Syncing agreements by 3yc End Date...")
    _sync_agreements_by_param(
        mpt_client, Param.THREE_YC_END_DATE.value, dry_run=dry_run, sync_prices=True
    )


def sync_agreements_by_coterm_date(mpt_client: MPTClient, *, dry_run: bool) -> None:
    """
    Synchronizes agreements by their active subscriptions renewed yesterday.

    Args:
        mpt_client: MPT API client.
        dry_run: Run in dry run mode.
    """
    logger.info("Synchronizing agreements by cotermDate...")
    _sync_agreements_by_param(
        mpt_client, Param.COTERM_DATE.value, dry_run=dry_run, sync_prices=True
    )


def _sync_agreements_by_param(
    mpt_client: MPTClient, param: Param, *, dry_run: bool, sync_prices: bool
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
    for agreement in get_agreements_by_query(mpt_client, rql_query):
        logger.debug("Syncing agreement %s", agreement)
        sync_agreement(mpt_client, agreement, dry_run=dry_run, sync_prices=sync_prices)


def sync_agreements_by_renewal_date(mpt_client: MPTClient, *, dry_run: bool) -> None:
    """
    Synchronizes agreements by their active subscriptions renewed yesterday.

    Args:
        mpt_client: MPT API client.
        dry_run: Run in dry run mode.
    """
    logger.info("Synchronizing agreements by renewal date...")
    today_plus_1_year = dt.datetime.now(tz=dt.UTC).date() + relativedelta(years=1)
    today_iso = dt.datetime.now(tz=dt.UTC).date().isoformat()
    yesterday_every_month = (
        (today_plus_1_year - dt.timedelta(days=1) - relativedelta(months=m)).isoformat()
        for m in range(24)
    )

    rql_query = (
        "eq(status,Active)&"
        f"any(subscriptions,any(parameters.fulfillment,and(eq(externalId,renewalDate),in(displayValue,({','.join(yesterday_every_month)}))))&"
        f"any(parameters.fulfillment,and(eq(externalId,{Param.LAST_SYNC_DATE.value}),ne(displayValue,{today_iso})))&"
        # Let's get only what we need
        "select=lines,parameters,subscriptions,product,listing"
    )
    for agreement in get_agreements_by_query(mpt_client, rql_query):
        logger.debug("Syncing agreement %s", agreement)
        sync_agreement(mpt_client, agreement, dry_run=dry_run, sync_prices=True)


def sync_agreements_by_agreement_ids(
    mpt_client: MPTClient,
    ids: list[str],
    *,
    dry_run: bool,
    sync_prices: bool,
) -> None:
    """
    Get the agreements given a list of agreement IDs to update the prices for them.

    Args:
        mpt_client: The client used to consume the MPT API.
        ids: List of agreement IDs.
        dry_run: if True, it just simulate the prices update but doesn't
        perform it.
        sync_prices: if True also sync prices.
    """
    agreements = get_agreements_by_ids(mpt_client, ids)
    for agreement in agreements:
        sync_agreement(mpt_client, agreement, dry_run=dry_run, sync_prices=sync_prices)


def sync_agreements_by_3yc_enroll_status(mpt_client: MPTClient, *, dry_run: bool) -> None:
    """
    This function retrieves agreements filtered by their 3YC enrollment status.

    Synchronizes their corresponding statuses.

    Args:
        mpt_client: MPT API client.
        dry_run: if True, it just simulate parameters update.
    """
    try:
        agreements = get_agreements_by_3yc_enroll_status(mpt_client, THREE_YC_TEMP_3YC_STATUSES)
    except Exception:
        logger.exception("Unknown exception getting agreements by 3YC enroll status.")
        raise
    for agreement in agreements:
        try:
            logger.info("Checking 3YC enroll status for agreement %s", agreement["id"])
            _sync_3yc_enroll_status(mpt_client, agreement, dry_run=dry_run)
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


def _sync_3yc_enroll_status(mpt_client: MPTClient, agreement: dict, *, dry_run: bool) -> None:
    adobe_client = get_adobe_client()
    customer = _get_customer_or_process_lost_customer(
        mpt_client, adobe_client, agreement, customer_id=get_adobe_customer_id(agreement)
    )
    if not customer:
        return

    commitment = get_3yc_commitment(customer)
    enroll_status = commitment.get("status")
    logger.debug(
        "Commitment Status for Adobe customer %s is %s",
        customer["customerId"],
        enroll_status,
    )
    sync_agreement(mpt_client, agreement, dry_run=dry_run, sync_prices=True)


def _is_deployment_matched(missing_deployment_id: str, subscription: dict) -> bool:
    return subscription.get("deploymentId") == missing_deployment_id


def _check_adobe_deployment_id(deployment_id: str, adobe_deployment: dict) -> bool:
    return adobe_deployment.get("deploymentId", "") == deployment_id


def _check_update_airtable_missing_deployments(
    agreement: dict, adobe_deployments: list[dict], adobe_subscriptions: Sequence[dict]
) -> None:
    agreement_id = agreement["id"]
    product_id = agreement["product"]["id"]
    logger.info("Checking airtable for missing deployments for agreement %s", agreement_id)
    customer_deployment_ids = {cd["deploymentId"] for cd in adobe_deployments}
    airtable_deployment_ids = {
        ad.deployment_id
        for ad in models.get_gc_agreement_deployments_by_main_agreement(product_id, agreement_id)
    }
    missing_deployment_ids = customer_deployment_ids - airtable_deployment_ids
    if not missing_deployment_ids:
        return
    logger.info("Found missing deployments: %s", missing_deployment_ids)
    missing_deployments_data = []
    for missing_deployment_id in sorted(missing_deployment_ids):
        transfer = models.get_transfer_by_authorization_membership_or_customer(
            product_id, agreement["authorization"]["id"], get_adobe_customer_id(agreement)
        )
        if not transfer:
            logger.info("No transfer found for missing deployment %s", missing_deployment_id)
            continue

        is_deployment_matched = partial(_is_deployment_matched, missing_deployment_id)
        deployment_currency = (find_first(is_deployment_matched, adobe_subscriptions, {})).get(
            "currency"
        )
        missing_deployments_data.append({
            "deployment": find_first(
                partial(_check_adobe_deployment_id, missing_deployment_id), adobe_deployments
            ),
            "transfer": transfer,
            "deployment_currency": deployment_currency,
        })

    if missing_deployments_data:
        deployment_model = models.get_gc_agreement_deployment_model(
            models.AirTableBaseInfo.for_migrations(product_id)
        )
        missing_deployments = []
        for missing_deployment_data in missing_deployments_data:
            logger.info(
                "> Adding missing deployment to Airtable: %s",
                missing_deployment_data["deployment"]["deploymentId"],
            )
            missing_deployments.append(
                deployment_model(
                    deployment_id=missing_deployment_data["deployment"]["deploymentId"],
                    main_agreement_id=agreement_id,
                    account_id=agreement["client"]["id"],
                    seller_id=agreement["seller"]["id"],
                    product_id=product_id,
                    membership_id=missing_deployment_data["transfer"].membership_id,
                    transfer_id=missing_deployment_data["transfer"].transfer_id,
                    status="pending",
                    customer_id=get_adobe_customer_id(agreement),
                    deployment_currency=missing_deployment_data["deployment_currency"],
                    deployment_country=missing_deployment_data["deployment"]["companyProfile"][
                        "address"
                    ]["country"],
                    licensee_id=agreement["licensee"]["id"],
                )
            )
        models.create_gc_agreement_deployments(product_id, missing_deployments)
        send_notification(
            "Missing deployments added to Airtable",
            f"agreement {agreement_id}, deployments: {missing_deployment_ids}.",
            TeamsColorCode.ORANGE.value,
        )


def sync_global_customer_parameters(
    mpt_client: MPTClient,
    adobe_deployments: list[dict],
    adobe_subscriptions: Sequence[dict],
    agreement: dict,
) -> None:
    """
    Sync global customer parameters for the agreement.

    Args:
        adobe_subscriptions: adobe subscriptions
        mpt_client: MPT API client.
        adobe_deployments: Adobe customer deployments.
        agreement: main customer agreement.
    """
    try:
        parameters = {Param.PHASE_FULFILLMENT.value: []}
        global_customer_enabled = get_global_customer(agreement)
        if global_customer_enabled != ["Yes"]:
            logger.info("Setting global customer for agreement %s", agreement["id"])
            parameters[Param.PHASE_FULFILLMENT.value].append({
                "externalId": "globalCustomer",
                "value": ["Yes"],
            })

        deployments = [
            f"{deployment['deploymentId']} - {deployment['companyProfile']['address']['country']}"
            for deployment in adobe_deployments
        ]
        agreement_deployments = get_deployments(agreement)
        if deployments != agreement_deployments:
            logger.info("Setting deployments for agreement %s", agreement["id"])
            parameters[Param.PHASE_FULFILLMENT.value].append({
                "externalId": "deployments",
                "value": ",".join(deployments),
            })
            _check_update_airtable_missing_deployments(
                agreement, adobe_deployments, adobe_subscriptions
            )
        if parameters[Param.PHASE_FULFILLMENT.value]:
            update_agreement(mpt_client, agreement["id"], parameters=parameters)
    except Exception:
        logger.exception(
            "Error setting global customer parameters for agreement %s.",
            agreement["id"],
        )
        notify_agreement_unhandled_exception_in_teams(agreement["id"], traceback.format_exc())


def process_lost_customer(  # noqa: C901
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
            terminate_subscription(
                mpt_client,
                subscription_id,
                "Suspected Lost Customer",
            )
        except Exception as e:
            logger.exception(
                "> Suspected Lost Customer: Error terminating subscription %s.",
                subscription_id,
            )
            send_exception(
                f"> Suspected Lost Customer: Error terminating subscription {subscription_id}",
                f"{e}",
            )

    adobe_deployments = adobe_client.get_customer_deployments_active_status(
        agreement["authorization"]["id"], customer_id
    )
    if adobe_deployments:
        deployment_agreements = get_agreements_by_customer_deployments(
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
                    terminate_subscription(mpt_client, subscription_id, "Suspected Lost Customer")
                except Exception as e:
                    logger.exception(
                        "> Suspected Lost Customer: Error terminating subscription %s.",
                        subscription_id,
                    )
                    send_exception(
                        "> Suspected Lost Customer: Error terminating subscription"
                        f" {subscription_id}",
                        f"{e}",
                    )


def sync_agreement(  # noqa: C901
    mpt_client: MPTClient,
    agreement: dict,
    *,
    dry_run: bool,
    sync_prices: bool,
) -> None:
    """
    Sync agreement with parameters, prices from Adobe API, airtable to MPT agreement.

    Args:
        mpt_client: MPT API client.
        agreement: MPT agreement.
        dry_run: If True do not update agreement.
        sync_prices: If true sync prices. Keep in mind dry_run parameter.
    """
    logger.debug("Syncing agreement %s", agreement)
    if agreement["status"] != AgreementStatus.ACTIVE:
        logger.info("Skipping agreement %s because it is not in Active status", agreement["id"])
        return
    try:
        customer_id = get_adobe_customer_id(agreement)
        adobe_client = get_adobe_client()
        logger.info("Synchronizing agreement %s...", agreement["id"])

        processing_subscriptions = list(
            filter(
                lambda sub: sub["status"] in {"Updating", "Terminating"},
                agreement["subscriptions"],
            ),
        )

        if len(processing_subscriptions) > 0:
            logger.info("Agreement %s has processing subscriptions, skip it", agreement["id"])
            return

        customer = _get_customer_or_process_lost_customer(
            mpt_client, adobe_client, agreement, customer_id
        )
        if not customer:
            return

        adobe_subscriptions = adobe_client.get_subscriptions(
            agreement["authorization"]["id"], customer["customerId"]
        )["items"]

        if not adobe_subscriptions:
            logger.info(
                "Skipping price sync - no subscriptions found for the customer %s", customer_id
            )
            return

        if not customer.get("discounts", []):
            raise CustomerDiscountsNotFoundError(  # noqa: TRY301
                f"Customer {customer_id} does not have discounts information. "
                f"Cannot proceed with price synchronization for the agreement {agreement['id']}."
            )

        subscriptions_for_update = _get_subscriptions_for_update(
            mpt_client, agreement, customer, adobe_subscriptions
        )

        _add_missing_subscriptions(
            mpt_client, adobe_client, customer, agreement, adobe_subscriptions=adobe_subscriptions
        )

        if sync_prices:
            sync_agreement_prices(
                mpt_client,
                adobe_client,
                agreement,
                customer,
                subscriptions_for_update,
                dry_run=dry_run,
            )
        else:
            logger.info("Skipping price sync - sync_prices %s.", sync_prices)

        _update_agreement(mpt_client, customer, agreement, dry_run=dry_run)

        if customer.get("globalSalesEnabled", False):
            authorization_id = agreement["authorization"]["id"]
            adobe_deployments = adobe_client.get_customer_deployments_active_status(
                authorization_id, customer_id
            )
            sync_global_customer_parameters(
                mpt_client, adobe_deployments, adobe_subscriptions, agreement
            )
            sync_deployments_prices(
                mpt_client,
                adobe_client,
                agreement,
                customer,
                adobe_deployments,
                adobe_subscriptions,
                dry_run=dry_run,
                sync_prices=sync_prices,
            )

    except AuthorizationNotFoundError:
        logger.exception("AuthorizationNotFoundError synchronizing agreement %s.", agreement["id"])
    except Exception:
        logger.exception("Error synchronizing agreement %s.", agreement["id"])
        notify_agreement_unhandled_exception_in_teams(agreement["id"], traceback.format_exc())
    else:
        if not dry_run:
            _update_last_sync_date(mpt_client, agreement)


def _get_customer_or_process_lost_customer(mpt_client, adobe_client, agreement, customer_id):
    try:
        return adobe_client.get_customer(agreement["authorization"]["id"], customer_id)
    except AdobeAPIError as e:
        if e.code == AdobeStatus.INVALID_CUSTOMER:
            logger.info(
                "Received Adobe error %s - %s, assuming lost customer "
                "and proceeding with lost customer procedure.",
                e.code,
                e.message,
            )
            send_notification(
                "Executing Lost Customer Procedure.",
                f"Received Adobe error {e.code} - {e.message},"
                " assuming lost customer and proceeding with lost customer procedure.",
                TeamsColorCode.ORANGE.value,
            )
            process_lost_customer(mpt_client, adobe_client, agreement, customer_id)
            return None
        raise


def _update_last_sync_date(mpt_client: MPTClient, agreement: dict) -> None:
    logger.info("Updating Last Sync Date for agreement %s", agreement["id"])
    update_agreement(
        mpt_client,
        agreement["id"],
        parameters={
            "fulfillment": [
                {
                    "externalId": Param.LAST_SYNC_DATE.value,
                    "value": dt.datetime.now(tz=dt.UTC).date().isoformat(),
                },
            ]
        },
    )


def _is_subscription_in_set(subscription_ids: set, subscription: dict) -> bool:
    return subscription["subscriptionId"] in subscription_ids


def _process_orphaned_deployment_subscriptions(
    adobe_client: AdobeClient,
    authorization_id: str,
    customer_id: str,
    deployment_agreements: list[dict],
    adobe_subscriptions: Sequence[dict],
) -> None:
    logger.info("Looking for orphaned deployment subscriptions in Adobe.")
    mpt_subscription_ids = {
        get_fulfillment_parameter(subscription, Param.ADOBE_SKU)["value"]
        for agreement in deployment_agreements
        for subscription in agreement["subscriptions"]
    }
    adobe_subscription_ids = {
        subscription["subscriptionId"]
        for subscription in adobe_subscriptions
        if subscription.get("deploymentId")
    }
    orphaned_subscription_ids = adobe_subscription_ids - mpt_subscription_ids

    for subscription in filter(
        partial(_is_subscription_in_set, orphaned_subscription_ids), adobe_subscriptions
    ):
        logger.warning("> Disabling auto-renewal for orphaned subscription %s", subscription)
        try:
            adobe_client.update_subscription(
                authorization_id,
                customer_id,
                subscription["subscriptionId"],
                auto_renewal=False,
            )
        except Exception as e:
            send_exception(
                "Error disabling auto-renewal for orphaned Adobe subscription"
                f" {subscription['subscriptionId']}.",
                f"{e}",
            )


def sync_deployments_prices(
    mpt_client: MPTClient,
    adobe_client: AdobeClient,
    main_agreement: dict,
    customer: dict,
    adobe_deployments: list[dict],
    adobe_subscriptions: Sequence[dict],
    *,
    dry_run: bool,
    sync_prices: bool,
) -> None:
    """
    Sync deployment agreements prices.

    Args:
        mpt_client: MPT API client.
        adobe_client: Adobe API client.
        main_agreement: Main MPT agreement.
        customer: Adobe customer.
        adobe_deployments: Adobe customer deployments.
        adobe_subscriptions: list of subscriptions for customer from Adobe.
        dry_run: Run command in a dry run mode.
        sync_prices: If True also sync prices.
    """
    if not adobe_deployments:
        return

    deployment_agreements = get_agreements_by_customer_deployments(
        mpt_client,
        Param.DEPLOYMENT_ID.value,
        [deployment["deploymentId"] for deployment in adobe_deployments],
    )

    _process_orphaned_deployment_subscriptions(
        adobe_client,
        main_agreement["authorization"]["id"],
        customer["customerId"],
        deployment_agreements,
        adobe_subscriptions,
    )

    for deployment_agreement in deployment_agreements:
        subscriptions_for_update = _get_subscriptions_for_update(
            mpt_client, deployment_agreement, customer, adobe_subscriptions
        )

        if sync_prices:
            sync_agreement_prices(
                mpt_client,
                adobe_client,
                deployment_agreement,
                customer,
                subscriptions_for_update,
                dry_run=dry_run,
            )
        else:
            logger.info("Skipping price sync - sync_prices %s.", sync_prices)

        _update_agreement(mpt_client, customer, deployment_agreement, dry_run=dry_run)

        sync_gc_3yc_agreements(
            mpt_client,
            main_agreement,
            deployment_agreement,
            dry_run=dry_run,
        )


def sync_gc_3yc_agreements(
    mpt_client: MPTClient,
    main_agreement: dict,
    deployment_agreement: list[dict],
    *,
    dry_run: bool,
) -> None:
    """
    Sync 3YC parameters from main agreement to provided deployment agreement.

    Args:
        mpt_client: MPT API client.
        main_agreement: MPT main agreement. Retrieves 3YC parameters from here.
        deployment_agreement: MPT deployment agreement.
        dry_run: If True do not update agreement. Only simulate sync.
    """
    parameters_3yc = get_3yc_fulfillment_parameters(main_agreement)

    if not dry_run:
        update_agreement(
            mpt_client,
            deployment_agreement["id"],
            parameters={
                "fulfillment": parameters_3yc,
            },
        )


def sync_all_agreements(mpt_client: MPTClient, *, dry_run: bool) -> None:
    """
    Get all the active agreements to update the prices for them.

    Args:
        mpt_client: The client used to consume the MPT API.
        dry_run: if True, it just simulate the prices update but doesn't
        perform it.
    """
    agreements = get_all_agreements(mpt_client)
    for agreement in agreements:
        sync_agreement(mpt_client, agreement, dry_run=dry_run, sync_prices=False)


def get_one_time_skus(mpt_client: MPTClient, product_id: str, vendor_external_ids) -> set[str]:
    """
    Returns all one-time SKUs associated with a specific product.

    Args:
        vendor_external_ids: vendors to filter
        mpt_client: An instance of MPTClient.
        product_id: product id.

    Returns:
        A tuple of product ids.
    """
    return {
        item["externalIds"]["vendor"]
        for item in get_product_items_by_period(
            mpt_client, product_id, "one-time", vendor_external_ids
        )
    }
