from typing import Any

from django.conf import settings
from mpt_extension_sdk.core.utils import setup_client
from mpt_extension_sdk.mpt_http.mpt import get_agreements_by_query, update_asset
from mpt_extension_sdk.mpt_http.wrap_http_error import MPTAPIError
from mpt_extension_sdk.runtime.tracer import dynamic_trace_span

from adobe_vipm.adobe.client import get_adobe_client
from adobe_vipm.adobe.errors import AdobeAPIError
from adobe_vipm.flows.constants import Param
from adobe_vipm.flows.errors import MPTHttpError
from adobe_vipm.flows.utils import get_deployment_id, get_parameter
from adobe_vipm.management.commands.base import AdobeBaseCommand


class Command(AdobeBaseCommand):  # noqa: WPS214
    """Migrate assets with the Adobe subscriptionId."""

    help = "Migrate assets with the Adobe subscriptionId"

    def add_arguments(self, parser):
        """Add arguments."""
        parser.add_argument(
            "--agreements", nargs="*", default=[], help="List of specific agreements to update."
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            default=False,
            help="Run command without making changes.",
        )

    def handle(self, *args, **options):  # noqa: WPS110
        """Run command."""
        for agreement in self._get_agreements(options["agreements"]):
            self._process_agreement(agreement, dry_run=options["dry_run"])

    @dynamic_trace_span(lambda *args, **kwargs: f"Agreement {args[1]['id']}")  # noqa: WPS237
    def _process_agreement(self, agreement: dict[str, Any], *, dry_run: bool) -> None:
        self.info(f"Start updating assets for agreement {agreement['id']}.")
        subscriptions = self._get_subscriptions_from_adobe(agreement)
        for asset in self._get_assets_no_subscription_id(agreement["assets"]):
            self.info(f"Start updating asset {asset['id']}.")
            adobe_subscription = self._find_subscription(subscriptions, asset)
            if not adobe_subscription:
                self.error(f"Error updating asset {asset['id']}: subscription not found in Adobe")
                continue

            self._update_mpt_asset(asset, adobe_subscription, dry_run=dry_run)
            self.info(f"Asset {asset['id']} has been updated.")

        self.success(f"Agreement {agreement['id']} has been updated.")

    def _get_agreements(self, agreements: list[str]) -> list[dict[str, Any]]:
        mpt_client = setup_client()
        select_fields = "-*,id,externalIds,authorization.id,assets,assets.parameters,parameters"  # noqa: WPS237
        rql_query = (
            f"select={select_fields}&in(product.id,({settings.MPT_PRODUCTS_IDS}))&eq(status,Active)"  # noqa: WPS237
        )
        if agreements:
            rql_query += f"&(in(id,{tuple(agreements)}))"  # noqa: WPS336

        return get_agreements_by_query(mpt_client, rql_query)

    def _get_assets_no_subscription_id(self, assets: list[dict[str, Any]]) -> list[dict[str, Any]]:  # noqa: WPS221
        return [asset for asset in assets if not asset.get("externalIds", {}).get("vendor")]

    def _get_subscriptions_from_adobe(self, agreement: dict[str, Any]) -> list[dict[str, Any]]:
        adobe_client = get_adobe_client()
        try:
            subscriptions = adobe_client.get_subscriptions_by_deployment(
                agreement["authorization"]["id"],
                customer_id=agreement["externalIds"]["vendor"],
                deployment_id=get_deployment_id(agreement),
            )
        except AdobeAPIError as error:
            self.error(
                f"Error getting Adobe subscriptions for agreement {agreement['id']}: {error}"
            )
            return []

        return [
            {
                Param.ADOBE_SKU: sub["offerId"],
                Param.CURRENT_QUANTITY: str(sub[Param.CURRENT_QUANTITY]),
                Param.USED_QUANTITY: str(sub[Param.USED_QUANTITY]),
                "processed": False,
                "subscriptionId": sub["subscriptionId"],
            }
            for sub in subscriptions["items"]
        ]

    def _find_subscription(
        self,
        subscriptions: list[dict[str, Any]],
        asset: dict[str, Any],  # noqa: WPS221
    ) -> dict[str, Any]:
        adobe_sku = get_parameter(Param.PHASE_FULFILLMENT, asset, Param.ADOBE_SKU).get("value")
        current_quantity = get_parameter(
            Param.PHASE_FULFILLMENT, asset, Param.CURRENT_QUANTITY
        ).get("value")
        return next(
            filter(
                lambda sub: sub[Param.ADOBE_SKU] == adobe_sku
                and sub[Param.CURRENT_QUANTITY] == current_quantity
                and sub["processed"] is False,
                subscriptions,
            ),
            None,
        )

    def _update_mpt_asset(
        self,
        asset: dict[str, Any],
        adobe_subscription: dict[str, Any],
        *,
        dry_run: bool = False,  # noqa: WPS221
    ) -> None:
        parameters_data = {
            "fulfillment": [
                {
                    "externalId": Param.ADOBE_SKU.value,
                    "value": adobe_subscription[Param.ADOBE_SKU],
                },
                {
                    "externalId": Param.CURRENT_QUANTITY.value,
                    "value": str(adobe_subscription[Param.CURRENT_QUANTITY]),
                },
                {
                    "externalId": Param.USED_QUANTITY.value,
                    "value": str(adobe_subscription[Param.USED_QUANTITY]),
                },
            ]
        }
        external_ids_data = {"vendor": adobe_subscription["subscriptionId"]}
        if dry_run:
            self.info(
                f"Dry run mode - Asset {asset['id']} updated with: \n"
                f"parameters: {parameters_data} \n"
                f"externalIds: {external_ids_data} \n"
            )
        else:
            mpt_client = setup_client()
            try:
                update_asset(
                    mpt_client,
                    asset["id"],
                    parameters=parameters_data,
                    externalIds=external_ids_data,
                )
            except (MPTHttpError, MPTAPIError) as error:
                self.error(f"Error updating asset {asset['id']}: {error}")
            else:
                self.info(
                    f"Asset {asset['id']} updated with: \n"
                    f"parameters: {parameters_data} \n"
                    f"externalIds: {external_ids_data} \n"
                )

        adobe_subscription["processed"] = True
