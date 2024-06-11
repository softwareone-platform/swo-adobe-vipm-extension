import logging
import sys
from datetime import datetime, timedelta

from adobe_vipm.adobe.client import get_adobe_client
from adobe_vipm.adobe.config import get_config
from adobe_vipm.adobe.constants import STATUS_3YC_COMMITTED
from adobe_vipm.adobe.utils import get_3yc_commitment
from adobe_vipm.flows.constants import PARAM_ADOBE_SKU
from adobe_vipm.flows.mpt import (
    get_agreement_subscription,
    get_agreements_by_ids,
    get_agreements_by_next_sync,
    get_all_agreements,
    get_pricelist_items_by_product_items,
    get_product_items_by_skus,
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
    allow_3yc,
    dry_run,
):
    try:
        adobe_client = get_adobe_client()
        adobe_config = get_config()
        agreement_id = agreement["id"]
        authorization_id = agreement["authorization"]["id"]
        customer_id = get_adobe_customer_id(agreement)
        pricelist_id = agreement["listing"]["priceList"]["id"]
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
        if (
            commitment
            and commitment["status"] == STATUS_3YC_COMMITTED
            and not allow_3yc
        ):
            logger.info(
                f"Customer of agreement {agreement_id} has commited for 3y, skip it"
            )
            return

        coterm_date = customer["cotermDate"]

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
            prod_item = get_product_items_by_skus(mpt_client, product_id, [actual_sku])[
                0
            ]
            price_item = get_pricelist_items_by_product_items(
                mpt_client, pricelist_id, [prod_item["id"]]
            )[0]

            line_id = subscription["lines"][0]["id"]
            lines = [
                {
                    "price": {
                        "unitPP": price_item["unitPP"],
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
                )
                logger.info(
                    f"Subscription: {subscription['id']} ({line_id}): "
                    f"sku={actual_sku} ({prod_item['id']} - {price_item['id']})"
                )
            else:
                current_price = subscription["lines"][0]["price"]["unitPP"]
                sys.stdout.write(
                    f"Subscription: {subscription['id']} ({line_id}): "
                    f"sku={actual_sku} ({prod_item['id']}), "
                    f"current_price={current_price}, "
                    f"new_price={price_item['unitPP']} ({price_item['id']})\n"
                )

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
            prod_item = get_product_items_by_skus(mpt_client, product_id, [actual_sku])[
                0
            ]
            price_item = get_pricelist_items_by_product_items(
                mpt_client, pricelist_id, [prod_item["id"]]
            )[0]
            current_price = line["price"]["unitPP"]
            line["price"]["unitPP"] = price_item["unitPP"]

            if dry_run:
                sys.stdout.write(
                    f"OneTime item: {line['id']}: "
                    f"sku={actual_sku} ({prod_item['id']}), "
                    f"current_price={current_price}, "
                    f"new_price={price_item['unitPP']} ({price_item['id']})\n",
                )
            else:
                logger.info(
                    f"OneTime item: {line['id']}: "
                    f"sku={actual_sku} ({prod_item['id']} - {price_item['id']})"
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


def sync_agreements_by_next_sync(mpt_client, allow_3yc, dry_run):
    agreements = get_agreements_by_next_sync(mpt_client)
    for agreement in agreements:
        sync_agreement_prices(
            mpt_client,
            agreement,
            allow_3yc,
            dry_run,
        )


def sync_agreements_by_agreement_ids(mpt_client, ids, allow_3yc, dry_run):
    agreements = get_agreements_by_ids(mpt_client, ids)
    for agreement in agreements:
        sync_agreement_prices(
            mpt_client,
            agreement,
            allow_3yc,
            dry_run,
        )


def sync_all_agreements(mpt_client, allow_3yc, dry_run):
    agreements = get_all_agreements(mpt_client)
    for agreement in agreements:
        sync_agreement_prices(
            mpt_client,
            agreement,
            allow_3yc,
            dry_run,
        )
