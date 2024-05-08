import logging
from datetime import datetime, timedelta

from adobe_vipm.adobe.client import get_adobe_client
from adobe_vipm.flows.constants import PARAM_ADOBE_SKU
from adobe_vipm.flows.mpt import (
    get_agreement_subscription,
    get_agreements_by_next_sync,
    get_pricelist_items_by_product_items,
    get_product_items_by_skus,
    update_agreement,
    update_agreement_subscription,
)
from adobe_vipm.flows.utils import get_adobe_customer_id

logger = logging.getLogger(__name__)


def sync_prices(mpt_client):
    adobe_client = get_adobe_client()
    agreements = get_agreements_by_next_sync(mpt_client)

    for agreement in agreements:
        agreement_id = agreement["id"]
        authorization_id = agreement["authorization"]["id"]
        customer_id = get_adobe_customer_id(agreement)
        pricelist_id = agreement["listing"]["priceList"]["id"]
        product_id = agreement["product"]["id"]
        subscriptions = agreement["subscriptions"]

        logger.info(f"Processing renewal for agreement {agreement_id}...")

        processing_subscriptions = list(
            filter(
                lambda sub: sub["status"] in ("Updating", "Terminating"), subscriptions
            ),
        )

        if len(processing_subscriptions) > 0:
            logger.info(
                f"Agreement {agreement_id} has processing subscriptions, skip it"
            )
            continue

        commitment_date = None

        try:
            for subscription in subscriptions:
                if subscription["status"] == "Terminated":
                    continue

                subscription = get_agreement_subscription(
                    mpt_client, subscription["id"]
                )
                commitment_date = subscription["commitmentDate"]
                adobe_subscription_id = subscription["externalIds"]["vendor"]

                adobe_subscription = adobe_client.get_subscription(
                    authorization_id,
                    customer_id,
                    adobe_subscription_id,
                )

                actual_sku = adobe_subscription["offerId"]
                prod_item = get_product_items_by_skus(
                    mpt_client, product_id, [actual_sku]
                )[0]
                price_item = get_pricelist_items_by_product_items(
                    mpt_client, pricelist_id, [prod_item["id"]]
                )[0]

                lines = [
                    {
                        "price": {
                            "unitPP": price_item["unitPP"],
                        },
                        "id": subscription["lines"][0]["id"],
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

                logger.info(f"updating subscription {subscription['id']}")

                update_agreement_subscription(
                    mpt_client,
                    subscription["id"],
                    lines=lines,
                    parameters=parameters,
                )

            next_sync = (
                (datetime.fromisoformat(commitment_date) + timedelta(days=1))
                .date()
                .isoformat()
            )

            update_agreement(
                mpt_client,
                agreement["id"],
                parameters={
                    "fulfillment": [{"externalId": "nextSync", "value": next_sync}]
                },
            )

            logger.info(f"agreement updated {agreement['id']}")

        except Exception:
            logger.exception(f"Cannot sync agreement {agreement_id}")
