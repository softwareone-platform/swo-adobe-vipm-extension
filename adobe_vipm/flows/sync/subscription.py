import datetime as dt
import logging
import traceback

from mpt_extension_sdk.mpt_http import mpt
from mpt_extension_sdk.mpt_http.base import MPTClient

from adobe_vipm.airtable import models
from adobe_vipm.flows import utils as flows_utils
from adobe_vipm.flows.constants import Param
from adobe_vipm.flows.utils import notification
from adobe_vipm.flows.utils.template import get_template_data_by_adobe_subscription
from adobe_vipm.utils import get_commitment_start_date

logger = logging.getLogger(__name__)


class SubscriptionSyncer:
    """
    Handles synchronization of subscriptions between internal systems and Adobe.

    Attributes:
        mpt_client (MPTClient): The client used to interact with the MPT system.
        agreement (dict): The agreement data that includes product and listing details.
        customer (dict): The customer data including coterm date and other details.
        adobe_subscriptions (list[dict]): A list of Adobe subscriptions to be synchronized.
        subscriptions_for_update (list[dict]): A list of subscriptions requiring updates.
        dry_run (bool): Specifies whether the operation should simulate updates without
            making actual changes.
    """

    def __init__(
        self,
        mpt_client: MPTClient,
        agreement: dict,
        customer: dict,
        adobe_subscriptions: list[dict],
        subscriptions_for_update: list[dict],
        *,
        dry_run: bool,
    ):
        self._subscriptions_for_update = subscriptions_for_update
        self._mpt_client = mpt_client
        self._agreement = agreement
        self._product_id = agreement["product"]["id"]
        self._currency = agreement["listing"]["priceList"]["currency"]
        self._agreement_id = agreement["id"]
        self._authorization_id: str = agreement["authorization"]["id"]
        self._seller_id: str = agreement["seller"]["id"]
        self._licensee_id: str = agreement["licensee"]["id"]
        self._adobe_customer_id: str = flows_utils.get_adobe_customer_id(agreement)
        self._customer = customer
        self._adobe_subscriptions = adobe_subscriptions
        self._dry_run = dry_run

    def sync(self, *, sync_prices: bool) -> None:
        """
        Synchronizes subscriptions.

        Args:
            sync_prices (bool): Indicates whether to synchronize subscription pricing details.
        """
        logger.info("Synchronizing subscriptions.")
        try:
            skus = [subscription[2] for subscription in self._subscriptions_for_update]
            prices = models.get_sku_price(self._customer, skus, self._product_id, self._currency)
            missing_prices_skus = []
            coterm_date = self._customer["cotermDate"]
            for subscription, adobe_subscription, actual_sku in self._subscriptions_for_update:
                if actual_sku not in prices:
                    logger.error(
                        "Skipping subscription %s because the sku %s is not in the prices",
                        subscription["id"],
                        actual_sku,
                    )
                    missing_prices_skus.append(actual_sku)
                    continue

                self._update_subscription(
                    actual_sku,
                    adobe_subscription,
                    coterm_date,
                    prices,
                    subscription,
                    sync_prices=sync_prices,
                )
            if missing_prices_skus:
                flows_utils.notify_missing_prices(
                    self._agreement_id,
                    missing_prices_skus,
                    self._product_id,
                    self._currency,
                    get_commitment_start_date(self._customer),
                )
        except Exception:
            logger.exception("Error synchronizing agreement %s.", self._agreement_id)
            notification.notify_agreement_unhandled_exception_in_teams(
                self._agreement_id, traceback.format_exc()
            )

    def _update_subscription(
        self,
        actual_sku: str,
        adobe_subscription: dict,
        coterm_date: str,
        prices: dict,
        subscription: dict,
        *,
        sync_prices: bool,
    ) -> None:
        # A business requirement for Adobe is that subscription has 1-1 relation with item.
        line_id = subscription["lines"][0]["id"]
        logger.info(
            "Updating subscription: %s (%s): sku=%s", subscription["id"], line_id, actual_sku
        )
        fulfillment_params = {
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
        lines = [
            {
                "id": line_id,
                "quantity": adobe_subscription["autoRenewal"][Param.RENEWAL_QUANTITY.value],
            }
        ]
        if sync_prices:
            lines[0]["price"] = {"unitPP": prices[actual_sku]}
        else:
            logger.info("Skipping price sync - sync_prices %s.", sync_prices)

        template_data = get_template_data_by_adobe_subscription(
            adobe_subscription, self._product_id
        )
        auto_renewal_enabled = adobe_subscription["autoRenewal"]["enabled"]
        if self._dry_run:
            logger.info(
                "Dry run mode: skipping update agreement subscription %s with: \n lines: %s \n "
                "parameters: %s \n commitmentDate: %s \n autoRenew: %s \n template: %s",
                subscription["id"],
                lines,
                fulfillment_params,
                coterm_date,
                auto_renewal_enabled,
                template_data,
            )
        else:
            mpt.update_agreement_subscription(
                self._mpt_client,
                subscription["id"],
                lines=lines,
                parameters=fulfillment_params,
                commitmentDate=coterm_date,
                autoRenew=auto_renewal_enabled,
                template=template_data,
            )
