import logging
import sys
from datetime import date, datetime, timedelta

from adobe_vipm.adobe.client import get_adobe_client
from adobe_vipm.adobe.config import get_config
from adobe_vipm.adobe.constants import STATUS_3YC_ACTIVE, STATUS_3YC_COMMITTED
from adobe_vipm.adobe.utils import get_3yc_commitment
from adobe_vipm.flows.airtable import get_prices_for_3yc_skus, get_prices_for_skus
from adobe_vipm.flows.constants import PARAM_ADOBE_SKU
from adobe_vipm.flows.mpt import (
    get_agreement_subscription,
    get_agreements_by_ids,
    get_agreements_by_next_sync,
    get_all_agreements,
    update_agreement,
    update_agreement_subscription,
)
from adobe_vipm.flows.utils import (
    get_adobe_customer_id,
    get_customer_consumables_discount_level,
    get_customer_licenses_discount_level,
    is_consumables_sku,
)

logger = logging.getLogger(__name__)


def sync_agreement_prices(
    mpt_client,
    agreement,
    dry_run,
):
    try:
        adobe_client = get_adobe_client()
        adobe_config = get_config()
        agreement_id = agreement["id"]
        authorization_id = agreement["authorization"]["id"]
        customer_id = get_adobe_customer_id(agreement)
        currency = agreement["listing"]["priceList"]["currency"]
        product_id = agreement["product"]["id"]
        subscriptions = agreement["subscriptions"]

        logger.info(f"Synchronizing agreement {agreement_id}...")

        processing_subscriptions = list(
            filter(
                lambda sub: sub["status"] in ("Updating", "Terminating"), subscriptions
            ),
        )

        if len(processing_subscriptions) > 0:
            logger.info(
                f"Agreement {agreement_id} has processing subscriptions, skip it"
            )
            return

        customer = adobe_client.get_customer(authorization_id, customer_id)
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

            actual_sku = adobe_subscription["offerId"]

            discount_level = (
                get_customer_licenses_discount_level(customer)
                if not is_consumables_sku(actual_sku)
                else get_customer_consumables_discount_level(customer)
            )

            actual_sku = f"{actual_sku[0:10]}{discount_level}{actual_sku[12:]}"
            to_update.append((subscription, actual_sku))

        skus = [item[1] for item in to_update]

        if commitment_start_date:
            prices = get_prices_for_3yc_skus(product_id, currency, commitment_start_date, skus)
        else:
            prices = get_prices_for_skus(product_id, currency, skus)


        for subscription, actual_sku in to_update:
            line_id = subscription["lines"][0]["id"]
            lines = [
                {
                    "price": {
                        "unitPP": prices[actual_sku]
                    },
                    "id": line_id,
                }
            ]

            parameters = {
                "fulfillment": [
                    {
                        "externalId": PARAM_ADOBE_SKU,
                        "value": actual_sku,
                    },
                ],
            }

            if not dry_run:
                update_agreement_subscription(
                    mpt_client,
                    subscription["id"],
                    lines=lines,
                    parameters=parameters,
                    commitmentDate=coterm_date,
                )
                logger.info(
                    f"Subscription: {subscription['id']} ({line_id}): "
                    f"sku={actual_sku}"
                )
            else:
                current_price = subscription["lines"][0]["price"]["unitPP"]
                sys.stdout.write(
                    f"Subscription: {subscription['id']} ({line_id}): "
                    f"sku={actual_sku}, "
                    f"current_price={current_price}, "
                    f"new_price={prices[actual_sku]}\n"
                )

        to_update = []
        for line in agreement["lines"]:
            actual_sku = adobe_config.get_adobe_product(
                line["item"]["externalIds"]["vendor"]
            ).sku
            discount_level = (
                get_customer_licenses_discount_level(customer)
                if not is_consumables_sku(actual_sku)
                else get_customer_consumables_discount_level(customer)
            )
            actual_sku = f"{actual_sku[0:10]}{discount_level}{actual_sku[12:]}"

            to_update.append((line, actual_sku))

        skus = [item[1] for item in to_update]

        if commitment_start_date:
            prices = get_prices_for_3yc_skus(product_id, currency, commitment_start_date, skus)
        else:
            prices = get_prices_for_skus(product_id, currency, skus)

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
                logger.info(
                    f"OneTime item: {line['id']}: "
                    f"sku={actual_sku}\n"
                )

        next_sync = (
            (datetime.fromisoformat(coterm_date) + timedelta(days=1)).date().isoformat()
        )
        if not dry_run:
            update_agreement(
                mpt_client,
                agreement["id"],
                lines=agreement["lines"],
                parameters={
                    "fulfillment": [{"externalId": "nextSync", "value": next_sync}]
                },
            )

        logger.info(f"agreement updated {agreement['id']}")
        return coterm_date

    except Exception:
        logger.exception(f"Cannot sync agreement {agreement_id}")


def sync_agreements_by_next_sync(mpt_client, dry_run):
    agreements = get_agreements_by_next_sync(mpt_client)
    for agreement in agreements:
        sync_agreement_prices(
            mpt_client,
            agreement,
            dry_run,
        )


def sync_agreements_by_agreement_ids(mpt_client, ids, dry_run):
    agreements = get_agreements_by_ids(mpt_client, ids)
    for agreement in agreements:
        sync_agreement_prices(
            mpt_client,
            agreement,
            dry_run,
        )


def sync_all_agreements(mpt_client, dry_run):
    agreements = get_all_agreements(mpt_client)
    for agreement in agreements:
        sync_agreement_prices(
            mpt_client,
            agreement,
            dry_run,
        )
