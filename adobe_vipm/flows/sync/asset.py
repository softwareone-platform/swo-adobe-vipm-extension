import datetime as dt
import logging
from functools import partial

from mpt_extension_sdk.mpt_http import mpt
from mpt_extension_sdk.mpt_http.base import MPTClient
from mpt_extension_sdk.mpt_http.utils import find_first

from adobe_vipm.flows.constants import AssetStatus, Param
from adobe_vipm.flows.sync.util import _check_adobe_subscription_id
from adobe_vipm.flows.utils import get_parameter, get_sku_with_discount_level

logger = logging.getLogger(__name__)


class AssetsSyncer:
    """
    Handles the synchronization of assets.

    Attributes:
        mpt_client (MptClient): The client interface used to interact with the
            MPT system for fetching and updating asset data.
        agreement (dict): The agreement object containing assets and related
            information for the current customer.
        customer (dict): Customer information used to determine the appropriate
            SKU with discount levels.
        adobe_subscriptions (list[dict]): A list of subscriptions associated with
            the Adobe customer's account.
    """

    def __init__(
        self,
        mpt_client: MPTClient,
        agreement_id: str,
        assets: list[dict],
        customer: dict,
        adobe_subscriptions: list[dict],
    ) -> None:
        self._mpt_client = mpt_client
        self._agreement_id = agreement_id
        self._assets = assets
        self._customer = customer
        self._adobe_subscriptions = adobe_subscriptions

    def sync(self, *, dry_run: bool) -> None:
        """
        Synchronizes assets by updating them based on their status and configuration.

        Args:
            dry_run (bool): If True, the updates will be simulated without being
                applied. If False, the updates will be applied to the assets.
        """
        assets_for_update = self._get_assets_for_update()
        self._update_assets(assets_for_update, dry_run=dry_run)

    def _get_assets_for_update(self) -> list[dict]:
        logger.info("Getting assets for update for agreement %s", self._agreement_id)

        for_update = []
        for asset in self._assets:
            if asset["status"] == AssetStatus.TERMINATED:
                continue

            mpt_asset = mpt.get_asset_by_id(self._mpt_client, asset["id"])
            adobe_subscription_id = mpt_asset["externalIds"]["vendor"]
            adobe_subscription = find_first(
                partial(_check_adobe_subscription_id, adobe_subscription_id),
                self._adobe_subscriptions,
            )
            if not adobe_subscription:
                logger.error("No subscription found in Adobe customer data!")
                continue

            for_update.append((
                mpt_asset,
                adobe_subscription,
                get_sku_with_discount_level(adobe_subscription["offerId"], self._customer),
            ))

        return for_update

    def _update_assets(self, assets_for_update: list[dict], *, dry_run: bool) -> None:
        for asset, adobe_subscription, actual_sku in assets_for_update:
            asset_params = {
                "fulfillment": [
                    {
                        "externalId": Param.USED_QUANTITY.value,
                        "value": str(adobe_subscription[Param.USED_QUANTITY]),
                    },
                    {
                        "externalId": Param.LAST_SYNC_DATE.value,
                        "value": dt.datetime.now(tz=dt.UTC).date().isoformat(),
                    },
                ],
            }

            if dry_run:
                current_quantity = get_parameter("fulfillment", asset, "usedQuantity")["value"]
                logger.info(
                    "Updating asset: %s: sku=%s, current used quantity=%s, new used quantity=%s",
                    asset["id"],
                    actual_sku,
                    current_quantity,
                    adobe_subscription["usedQuantity"],
                )
            else:
                logger.info("Updating asset: %s: sku=%s", asset["id"], actual_sku)
                mpt.update_asset(self._mpt_client, asset["id"], parameters=asset_params)
