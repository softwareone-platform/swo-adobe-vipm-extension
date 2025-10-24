from argparse import ArgumentParser
from typing import Any, override

from django.conf import settings
from mpt_extension_sdk.mpt_http.mpt import (
    create_agreement_subscription,
    get_agreements_by_query,
    get_product_items_by_skus,
    update_agreement_subscription,
)
from mpt_extension_sdk.mpt_http.utils import find_first
from mpt_extension_sdk.mpt_http.wrap_http_error import MPTAPIError, wrap_mpt_http_error
from mpt_extension_sdk.runtime.tracer import dynamic_trace_span
from requests import Response

from adobe_vipm.adobe.client import get_adobe_client
from adobe_vipm.adobe.errors import AdobeAPIError
from adobe_vipm.airtable.models import get_sku_price
from adobe_vipm.flows.constants import AssetStatus, ItemTermsModel, Param, SubscriptionStatus
from adobe_vipm.flows.errors import MPTHttpError
from adobe_vipm.flows.utils import (
    get_deployment_id,
    get_fulfillment_parameter,
    get_sku_with_discount_level,
)
from adobe_vipm.management.commands.base import AdobeBaseCommand
from adobe_vipm.shared import mpt_client
from adobe_vipm.utils import get_partial_sku

# TODO: We set the SKUs to process for each item and environment as a constant, since
#  it's a one-shot process. These are the SKUs for COM testing items, it's still pending to add
#  the SKUs for GOV and EDU segments and, for staging and production envs
SKUS_TO_PROCESS = ("30006340CA", "30006208CA", "30006568CA")


class CreateSubscriptionError(Exception):
    """Exception raised when a subscription could not be created."""


class GetAdobeSubscriptionsError(Exception):
    """Exception raised when subscriptions could not be found."""


class TerminateAssetError(Exception):
    """Exception raised when an asset could not be terminated."""


class PriceNotFoundInAirtableError(Exception):
    """Exception raised when the price is not found in Airtable."""


class UpdateSubscriptionError(Exception):
    """Exception raised when a subscription could not be updated."""


# For now, we keep this method here instead of moving it to the SDK as it's a one-shot command, and
# we're going to remove it later from the SKD to use the python-api-client instead
@wrap_mpt_http_error
def terminate_asset(asset_id: str) -> Response:  # pragma: no cover
    """Terminate an asset."""
    response = mpt_client.post(f"/commerce/assets/{asset_id}/terminate")
    response.raise_for_status()
    return response.json()


class Command(AdobeBaseCommand):  # noqa: WPS214
    """Migrate Assets to non-renewal subscriptions."""

    help = "Migrate Assets to non-renewal subscriptions."

    @override
    def add_arguments(self, parser: ArgumentParser) -> None:
        parser.add_argument(
            "--agreements", nargs="*", default=[], help="List of specific agreements to update."
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            default=False,
            help="Run command without making changes.",
        )

    @override
    def handle(self, *args: list[Any], **options: Any) -> None:  # noqa: WPS110
        for agreement in self._get_agreements(options["agreements"]):
            self._process_agreement(agreement, dry_run=options["dry_run"])

    @dynamic_trace_span(lambda *args, **kwargs: f"Agreement {args[1]['id']}")  # noqa: WPS237
    def _process_agreement(self, agreement: dict[str, Any], *, dry_run: bool) -> None:  # noqa: C901 WPS210 WPS213 WPS231
        self.info(f"Starting to process assets for agreement {agreement['id']}")
        try:
            adobe_subs = self._get_subscriptions_from_adobe(agreement)
        except GetAdobeSubscriptionsError as error:
            self.error(f"Error processing assets for agreement {agreement['id']}: {error}")
            return

        subscriptions_processed = set()
        for asset in self._get_assets_to_process(agreement):
            adobe_sub = self._find_subscription(adobe_subs, asset)
            asset_id = asset["id"]
            if not adobe_sub:
                self.error(f"No subscription found for asset {asset_id}")
                continue

            if adobe_sub["id"] in subscriptions_processed:
                self.info(
                    f"Duplicate subscription for asset {asset['id']}. Set asset as terminated"
                )
                try:
                    self._terminate_asset(asset_id, dry_run=dry_run)
                except TerminateAssetError as error:
                    self.error(f"Failed to terminate asset {asset_id}: {error}")
                continue

            try:
                self._create_or_update_subscription(adobe_sub, agreement, dry_run=dry_run)
            except (
                CreateSubscriptionError,
                PriceNotFoundInAirtableError,
                UpdateSubscriptionError,
            ) as error:
                self.error(f"Failed creating/updating subscription for {asset_id}: {error}")
                continue

            self.info(f"Created subscription for {adobe_sub['id']}.")
            subscriptions_processed.add(adobe_sub["id"])

            try:
                self._terminate_asset(asset_id, dry_run=dry_run)
            except TerminateAssetError as error:
                self.error(f"Failed to terminate asset {asset_id}: {error}")
                continue

            self.info(f"Terminated assets for {adobe_sub['id']}.")

        self.success(f"Agreement {agreement['id']} has been updated.")

    def _create_or_update_subscription(
        self,
        adobe_sub: dict[str, Any],
        agreement: dict[str, Any],
        *,
        dry_run: bool = False,
    ) -> None:
        product_id = agreement["product"]["id"]
        entitlement = self._get_item_by_sku(product_id, adobe_sub[Param.ADOBE_SKU])
        sub_data = {
            "status": SubscriptionStatus.ACTIVE.value,
            "commitmentDate": adobe_sub["renewalDate"],
            "parameters": {
                "fulfillment": [
                    {
                        "externalId": Param.ADOBE_SKU.value,
                        "value": adobe_sub[Param.ADOBE_SKU],
                    },
                    {
                        "externalId": Param.CURRENT_QUANTITY.value,
                        "value": str(adobe_sub[Param.CURRENT_QUANTITY]),
                    },
                    {
                        "externalId": Param.RENEWAL_QUANTITY.value,
                        "value": str(adobe_sub[Param.RENEWAL_QUANTITY]),
                    },
                    {
                        "externalId": Param.RENEWAL_DATE.value,
                        "value": str(adobe_sub[Param.RENEWAL_DATE]),
                    },
                ]
            },
            "agreement": {"id": agreement["id"]},
            "buyer": {"id": agreement["buyer"]["id"]},
            "licensee": {"id": agreement["licensee"]["id"]},
            "seller": {"id": agreement["seller"]["id"]},
            "lines": self._get_subscription_lines(adobe_sub, product_id, entitlement),
            "name": f"Subscription for {entitlement['name']}",
            "startDate": adobe_sub["start_date"],
            "externalIds": {"vendor": adobe_sub["id"]},
            "product": {"id": product_id},
            "autoRenew": False,
        }
        if dry_run:
            self.info(f"Dry run mode - Create/Update subscription with: \n {sub_data}")
            return

        agreement_sub = self._get_agreement_sub(agreement["subscriptions"], adobe_sub["id"])
        if agreement_sub is not None:
            try:
                update_agreement_subscription(
                    mpt_client,
                    agreement_sub["id"],
                    parameters=sub_data["parameters"],
                    lines=sub_data["lines"],
                )
            except (MPTHttpError, MPTAPIError) as error:
                self.error(f"Error updating subscription {agreement_sub['id']}: {error}")
                raise UpdateSubscriptionError(error)

            self.info(
                f"Subscription {agreement_sub['id']} has been updated with: \n"
                f"parameters: {sub_data['parameters']} \nlines: {sub_data['lines']}"
            )
            return

        try:
            subscription = create_agreement_subscription(mpt_client, sub_data)
        except (MPTHttpError, MPTAPIError) as error:
            self.error(f"Error creating subscription {adobe_sub['id']}: {error}")
            raise CreateSubscriptionError(error)

        self.info(
            f"Subscription {subscription['id']} has been created with: \n parameters: {sub_data}"
        )

    def _find_subscription(
        self,
        subscriptions: list[dict[str, Any]],
        asset: dict[str, Any],
    ) -> dict[str, Any]:
        external_id = asset["externalIds"]["vendor"]
        return find_first(lambda sub: sub["id"] == external_id, subscriptions)

    def _get_agreement_sub(
        self, subscriptions: list[dict[str, Any]], sub_id: str
    ) -> dict[str, Any] | None:
        return find_first(lambda sub: sub["externalIds"]["vendor"] == sub_id, subscriptions)

    def _get_agreements(self, agreements: list[str]) -> list[dict[str, Any]]:
        select_fields = (
            "-*,id,authorization.id,assets,assets.lines,assets.parameters,buyer,externalIds,"
            "licensee,parameters,product.id,seller,subscriptions.id,subscriptions.externalIds"
        )
        skus_query = ",".join([f"ilike(displayValue,{sku}*)" for sku in SKUS_TO_PROCESS])
        assets_query = (
            f"any(assets,any(parameters.fulfillment,and(eq(externalId,adobeSKU),or({skus_query})))"
        )
        filter_query = (
            f"in(product.id,({settings.MPT_PRODUCTS_IDS})),{assets_query},eq(status,Active)"
        )
        rql_query = f"select={select_fields}&and({filter_query})"
        if agreements:
            rql_query += f"in(id,{tuple(agreements)})"  # noqa: WPS336

        return get_agreements_by_query(mpt_client, rql_query)

    def _get_assets_to_process(self, agreement: dict[str, Any]) -> list[dict[str, Any]]:
        return [
            asset
            for asset in agreement["assets"]
            if asset["status"] == AssetStatus.ACTIVE and self._has_sku_to_process(asset)
        ]

    def _get_customer_from_adobe(self, authorization_id: str, customer_id: str) -> dict[str, Any]:
        adobe_client = get_adobe_client()
        return adobe_client.get_customer(authorization_id, customer_id)

    def _get_item_by_sku(self, product_id: str, adobe_sku: str) -> dict[str, Any]:
        entitlements = get_product_items_by_skus(
            mpt_client, product_id, [get_partial_sku(adobe_sku)]
        )
        return find_first(
            lambda entitlement: entitlement["terms"]["model"] != ItemTermsModel.ONE_TIME,
            entitlements,
        )

    def _get_subscriptions_from_adobe(self, agreement: dict[str, Any]) -> list[dict[str, Any]]:
        adobe_client = get_adobe_client()
        customer_id = get_fulfillment_parameter(agreement, "customerId")["value"]
        try:
            customer = self._get_customer_from_adobe(agreement["authorization"]["id"], customer_id)
        except AdobeAPIError as error:
            self.error(f"Error getting customer with ID {customer_id}: {error}")
            raise GetAdobeSubscriptionsError(error)

        try:
            subscriptions = adobe_client.get_subscriptions_by_deployment(
                agreement["authorization"]["id"], customer_id, get_deployment_id(agreement)
            )
        except AdobeAPIError as error:
            self.error(
                f"Error getting Adobe subscriptions for agreement {agreement['id']}: {error}"
            )
            raise GetAdobeSubscriptionsError(error)

        return [
            {
                "id": sub["subscriptionId"],
                "currency": sub["currencyCode"],
                "customer": customer,
                "customer_id": customer_id,
                Param.ADOBE_SKU: sub["offerId"],
                Param.CURRENT_QUANTITY: str(sub[Param.CURRENT_QUANTITY]),
                Param.USED_QUANTITY: str(sub[Param.USED_QUANTITY]),
                Param.RENEWAL_QUANTITY: str(sub["autoRenewal"][Param.RENEWAL_QUANTITY]),
                Param.RENEWAL_DATE: str(sub[Param.RENEWAL_DATE]),
                "start_date": sub["creationDate"],
            }
            for sub in subscriptions["items"]
        ]

    def _get_subscription_lines(
        self,
        adobe_sub: dict[str, Any],
        product_id: str,
        entitlement: dict[str, Any],
    ) -> list[dict[str, Any]]:
        adobe_sku = adobe_sub[Param.ADOBE_SKU]
        prices = get_sku_price(
            adobe_sub["customer"], [adobe_sku], product_id, adobe_sub["currency"]
        )
        sku_discount_level = get_sku_with_discount_level(adobe_sku, adobe_sub["customer"])
        try:
            unit_price = {"price": {"unitPP": prices[sku_discount_level]}}
        except KeyError:
            msg = (
                f"Error getting lines. Discount level {sku_discount_level} has not been "
                f"found in Airtable."
            )
            self.error(msg)
            raise PriceNotFoundInAirtableError(msg)

        return [
            {
                "quantity": adobe_sub[Param.CURRENT_QUANTITY],
                "item": entitlement,
                **unit_price,
            }
        ]

    def _has_sku_to_process(self, asset: str) -> bool:
        partial_sku = get_fulfillment_parameter(asset, Param.ADOBE_SKU).get("value")
        return partial_sku and get_partial_sku(partial_sku) in SKUS_TO_PROCESS

    def _terminate_asset(self, asset_id: str, *, dry_run: bool) -> None:
        if dry_run:
            self.info(f"Dry run mode - asset {asset_id} has been set as terminated")
            return

        try:
            terminate_asset(asset_id)
        except (MPTHttpError, MPTAPIError) as error:
            self.error(f"Error setting asset {asset_id} as terminated: {error}")
            raise TerminateAssetError(error)

        self.info(f"Asset {asset_id} has been set as terminated")
