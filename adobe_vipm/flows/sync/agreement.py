import copy
import datetime as dt
import logging
import traceback
from functools import partial
from typing import Any

from mpt_extension_sdk.mpt_http import mpt
from mpt_extension_sdk.mpt_http.base import MPTClient
from mpt_extension_sdk.mpt_http.utils import find_first

from adobe_vipm.adobe.client import AdobeClient
from adobe_vipm.adobe.constants import AdobeStatus
from adobe_vipm.adobe.errors import AuthorizationNotFoundError
from adobe_vipm.adobe.utils import get_3yc_commitment_request
from adobe_vipm.airtable import models
from adobe_vipm.flows.constants import (
    TEMPLATE_SUBSCRIPTION_EXPIRED,
    TEMPLATE_SUBSCRIPTION_TERMINATION,
    AgreementStatus,
    ItemTermsModel,
    Param,
    SubscriptionStatus,
)
from adobe_vipm.flows.sync.asset import AssetsSyncer
from adobe_vipm.flows.sync.util import _check_adobe_subscription_id
from adobe_vipm.flows.utils import (
    get_3yc_fulfillment_parameters,
    get_adobe_customer_id,
    get_deployment_id,
    get_deployments,
    get_global_customer,
    get_parameter,
    get_sku_with_discount_level,
    notify_agreement_unhandled_exception_in_teams,
    notify_missing_prices,
)
from adobe_vipm.flows.utils.template import get_template_data_by_adobe_subscription
from adobe_vipm.notifications import send_exception, send_warning
from adobe_vipm.utils import get_3yc_commitment, get_commitment_start_date, get_partial_sku

logger = logging.getLogger(__name__)


class AgreementsSyncer:  # noqa: WPS214
    """
    Sync agreement.

    Args:
        mpt_client: The MPT client used to interact  with the MPT.
        adobe_client: The Adobe client used to interact with Adobe API.
        agreement: The agreement to sync.
        customer: The customer data.
        adobe_subscriptions: List of the Adobe subscriptions.
        dry_run: If true, no changes will be made (dry run mode).
    """

    def __init__(
        self,
        mpt_client: MPTClient,
        adobe_client: AdobeClient,
        agreement: dict,
        customer: dict,
        adobe_subscriptions: list[dict],
        *,
        dry_run: bool,
    ):
        self._mpt_client = mpt_client
        self._adobe_client = adobe_client
        self._agreement = agreement
        self._customer = customer
        self._adobe_subscriptions = adobe_subscriptions
        self._dry_run = dry_run
        self._authorization_id: str = agreement["authorization"]["id"]
        self._seller_id: str = agreement["seller"]["id"]
        self._licensee_id: str = agreement["licensee"]["id"]
        self._adobe_customer_id: str = get_adobe_customer_id(self._agreement)
        self._currency = agreement["listing"]["priceList"]["currency"]

    @property
    def agreement_id(self) -> str:
        """Return agreement id."""
        return self._agreement["id"]

    @property
    def product_id(self) -> str:
        """Return agreement product id."""
        return self._agreement["product"]["id"]

    def sync(self, *, sync_prices: bool) -> None:  # noqa: C901
        """
        Sync agreement with parameters, prices from Adobe API, airtable to MPT agreement.

        Args:
            sync_prices: If true sync prices. Keep in mind dry_run parameter.
        """
        logger.info("Synchronizing agreement %s", self.agreement_id)
        if self._agreement["status"] != AgreementStatus.ACTIVE:
            logger.info(
                "Skipping agreement %s because it is not in Active status", self.agreement_id
            )
            return

        try:
            if not self._is_sync_possible():
                return

            self._add_missing_subscriptions_and_assets()  # TODO: move asset part to asset classes

            AssetsSyncer(
                self._mpt_client,
                self.agreement_id,
                self._agreement["assets"],
                self._customer,
                self._adobe_subscriptions,
            ).sync(dry_run=self._dry_run)

            subscriptions_for_update = self._get_subscriptions_for_update(self._agreement)
            if subscriptions_for_update:
                self._update_subscriptions(
                    self._agreement, subscriptions_for_update, sync_prices=sync_prices
                )

            self._prepare_agreement_line_prices(self._agreement, self._currency, self.product_id)

            self._update_agreement(self._agreement)

            if self._customer.get("globalSalesEnabled", False):
                adobe_deployments = self._adobe_client.get_customer_deployments_active_status(
                    self._authorization_id, self._adobe_customer_id
                )
                self._sync_global_customer_parameters(adobe_deployments)
                self._sync_deployments_prices(adobe_deployments, sync_prices=sync_prices)

        except AuthorizationNotFoundError:
            logger.exception(
                "AuthorizationNotFoundError synchronizing agreement %s.", self.agreement_id
            )
        except Exception:
            logger.exception("Error synchronizing agreement %s.", self.agreement_id)
            notify_agreement_unhandled_exception_in_teams(self.agreement_id, traceback.format_exc())
        else:
            self._update_last_sync_date()
            self._agreement = mpt.get_agreement(self._mpt_client, self._agreement["id"])

    def _is_sync_possible(self):
        if any(
            filter(
                lambda sub: sub["status"] in {"Updating", "Terminating"},
                self._agreement["subscriptions"],
            ),
        ):
            logger.info("Agreement %s has processing subscriptions, skip it", self.agreement_id)
            return False

        if not self._adobe_subscriptions:
            logger.info(
                "Skipping price sync - no subscriptions found for the customer %s",
                self._adobe_customer_id,
            )
            return False

        if not self._customer.get("discounts", []):
            msg = (
                f"Error synchronizing agreement {self.agreement_id}. Customer "
                f"{self._adobe_customer_id} does not have discounts information."
                f" Cannot proceed with price synchronization."
            )
            # TODO: Move to the validate method or raise an error and send the notification from
            # the main method.
            logger.error(msg)
            send_warning("Customer does not have discounts information", msg)
            return False

        return True

    def _add_missing_subscriptions_and_assets(self) -> None:
        currency = self._agreement["listing"]["priceList"]["currency"]
        deployment_id = get_deployment_id(self._agreement) or ""
        logger.info(
            "Checking missing subscriptions for agreement=%s, deployment=%s",
            self.agreement_id,
            deployment_id,
        )
        adobe_subscriptions = tuple(
            a_s for a_s in self._adobe_subscriptions if a_s.get("deploymentId", "") == deployment_id
        )
        skus = {get_partial_sku(item["offerId"]) for item in adobe_subscriptions}

        mpt_entitlements_external_ids = self._extract_mpt_entitlements_external_ids()

        missing_adobe_subscriptions = tuple(
            subsc
            for subsc in adobe_subscriptions
            if subsc["subscriptionId"] not in mpt_entitlements_external_ids
            and subsc["status"] == AdobeStatus.SUBSCRIPTION_ACTIVE.value
        )
        if missing_adobe_subscriptions:
            logger.warning("> Found missing subscriptions")
        else:
            logger.info("> No missing subscriptions found")
            return

        items_map = {
            item["externalIds"]["vendor"]: item
            for item in mpt.get_product_items_by_skus(self._mpt_client, self.product_id, skus)
        }
        offer_ids = [
            get_sku_with_discount_level(adobe_subscription["offerId"], self._customer)
            for adobe_subscription in missing_adobe_subscriptions
        ]
        for adobe_subscription in missing_adobe_subscriptions:
            logger.info(">> Adding missing subscription %s", adobe_subscription["subscriptionId"])

            if adobe_subscription["currencyCode"] != currency:
                logger.warning(
                    "Skipping adobe subscription %s due to  currency mismatch.",
                    adobe_subscription["subscriptionId"],
                )
                if self._dry_run:
                    logger.info(
                        "Dry run mode: skipping update adobe subscription %s with: %s",
                        adobe_subscription["subscriptionId"],
                        {"auto_renewal": False},
                    )
                else:
                    self._adobe_client.update_subscription(
                        self._authorization_id,
                        self._adobe_customer_id,
                        adobe_subscription["subscriptionId"],
                        auto_renewal=False,
                    )

                    send_exception(
                        title="Price currency mismatch detected!", text=f"{adobe_subscription}"
                    )
                continue

            item = items_map[get_partial_sku(adobe_subscription["offerId"])]
            prices = models.get_sku_price(self._customer, offer_ids, self.product_id, currency)
            sku_discount_level = get_sku_with_discount_level(
                adobe_subscription["offerId"], self._customer
            )
            unit_price = {"price": {"unitPP": prices[sku_discount_level]}}
            if item["terms"]["model"] == ItemTermsModel.ONE_TIME:
                self._create_mpt_asset(adobe_subscription, item, unit_price)
            else:
                self._create_mpt_subscription(
                    adobe_subscription, item, sku_discount_level, prices, unit_price
                )

    def _create_mpt_asset(
        self, adobe_subscription: dict[str, Any], item: dict[str, Any], unit_price: dict[str, Any]
    ) -> None:
        asset_payload = {
            "status": "Active",
            "name": f"Asset for {item['name']}",
            "agreement": {"id": self.agreement_id},
            "parameters": {
                "fulfillment": [
                    {
                        "externalId": Param.ADOBE_SKU.value,
                        "value": adobe_subscription["offerId"],
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
            },
            "externalIds": {"vendor": adobe_subscription["subscriptionId"]},
            "lines": [
                {
                    "quantity": adobe_subscription[Param.CURRENT_QUANTITY],
                    "item": item,
                    **unit_price,
                }
            ],
            "startDate": adobe_subscription["creationDate"],
            "product": {"id": self.product_id},
            "buyer": {"id": self._agreement["buyer"]["id"]},
            "licensee": {"id": self._licensee_id},
            "seller": {"id": self._seller_id},
        }
        if self._dry_run:
            logger.info(
                "Dry run mode: skipping create mpt asset for agreement %s with: %s",
                self.agreement_id,
                asset_payload,
            )
            return

        mpt.create_asset(self._mpt_client, asset_payload)

    def _create_mpt_subscription(
        self,
        adobe_subscription: dict[str, Any],
        item: dict[str, Any],
        sku_discount_level: str,
        prices: dict[str, Any],
        unit_price: dict[str, Any],
    ) -> None:
        subscription_payload = {
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
            "agreement": {"id": self.agreement_id},
            "buyer": {"id": self._agreement["buyer"]["id"]},
            "licensee": {"id": self._licensee_id},
            "seller": {"id": self._seller_id},
            "lines": [
                {
                    "quantity": adobe_subscription[Param.CURRENT_QUANTITY.value],
                    "item": item,
                    **unit_price,
                }
            ],
            "name": f"Subscription for {item.get('name')}",
            "startDate": adobe_subscription["creationDate"],
            "externalIds": {"vendor": adobe_subscription["subscriptionId"]},
            "product": {"id": self.product_id},
            "autoRenew": adobe_subscription["autoRenewal"]["enabled"],
        }
        template_data = get_template_data_by_adobe_subscription(adobe_subscription, self.product_id)
        if template_data:
            subscription_payload["template"] = {
                "id": template_data["id"],
                "name": template_data["name"],
            }
        if self._dry_run:
            logger.info(
                "Dry run mode: skipping subscription creation for agreement %s with: %s",
                self.agreement_id,
                subscription_payload,
            )
        else:
            mpt.create_agreement_subscription(self._mpt_client, subscription_payload)

    def _extract_mpt_entitlements_external_ids(self) -> set[str]:
        """
        Extract external IDs from MPT entitlements (subscriptions and assets).

        Returns:
            Set of external IDs from entitlements

        Raises:
            Logs exception and sends notification if external IDs are missing
        """
        mpt_entitlements_external_ids = set()
        entitlements_without_external_ids = set()
        for entitlement in self._agreement["subscriptions"] + self._agreement["assets"]:
            if entitlement["status"] == SubscriptionStatus.TERMINATED:
                continue

            try:
                external_id = entitlement["externalIds"]["vendor"]
            except KeyError:
                entitlements_without_external_ids.add(entitlement["id"])
                continue

            mpt_entitlements_external_ids.add(external_id)

        if entitlements_without_external_ids:
            entitlements_to_notify = ", ".join(entitlements_without_external_ids)
            message = (
                f"Missing external IDs for entitlements: {entitlements_to_notify} in the "
                f"agreement {self.agreement_id}"
            )
            logger.warning(message)
            send_warning("Missing external IDs", message)

        return mpt_entitlements_external_ids

    def _update_subscriptions(
        self,
        agreement: dict,
        subscriptions_for_update: list[tuple[dict, dict, str]],
        *,
        sync_prices: bool,
    ) -> None:
        """
        Updates subscriptions by synchronizing prices and handling missing prices.

        Args:
            agreement (dict): A dictionary containing details about the agreement.
            subscriptions_for_update: subscriptions for update
            sync_prices: sync prices
        """
        product_id = agreement["product"]["id"]
        currency = agreement["listing"]["priceList"]["currency"]
        agreement_id = agreement["id"]
        skus = [item[2] for item in subscriptions_for_update]
        prices = models.get_sku_price(self._customer, skus, product_id, currency)
        missing_prices_skus = []
        coterm_date = self._customer["cotermDate"]
        for subscription, adobe_subscription, actual_sku in subscriptions_for_update:
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
                product_id,
                adobe_subscription,
                coterm_date,
                prices,
                subscription,
                sync_prices=sync_prices,
            )
        if missing_prices_skus:
            notify_missing_prices(
                agreement_id,
                missing_prices_skus,
                product_id,
                currency,
                get_commitment_start_date(self._customer),
            )

    def _update_subscription(
        self,
        actual_sku: str,
        product_id: str,
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

        template_data = get_template_data_by_adobe_subscription(adobe_subscription, product_id)
        auto_renewal_enabled = adobe_subscription["autoRenewal"]["enabled"]
        if self._dry_run:
            logger.info(
                "Dry run mode: skipping update agreement subscription %s with: \n lines: %s \n "
                "parameters: %s \n commitmentDate: %s \n autoRenew: %s \n template: %s",
                subscription["id"],
                lines,
                parameters,
                coterm_date,
                auto_renewal_enabled,
                template_data,
            )
        else:
            mpt.update_agreement_subscription(
                self._mpt_client,
                subscription["id"],
                lines=lines,
                parameters=parameters,
                commitmentDate=coterm_date,
                autoRenew=auto_renewal_enabled,
                template=template_data,
            )

    def _update_agreement(self, agreement: dict) -> None:
        parameters = {}
        commitment_info = get_3yc_commitment(self._customer)
        if commitment_info:
            parameters = self._add_3yc_fulfillment_params(agreement, commitment_info, parameters)
            for mq in commitment_info.get("minimumQuantities", {}):
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
            "value": self._customer.get("cotermDate", ""),
        })
        if self._dry_run:
            logger.info(
                "Dry run mode: skipping update for agreement %s with:/n lines: %s/n parameters: %s",
                agreement["id"],
                agreement["lines"],
                parameters,
            )
        else:
            mpt.update_agreement(
                self._mpt_client,
                agreement["id"],
                lines=agreement["lines"],
                parameters=parameters,
            )
        logger.info("Agreement updated %s", agreement["id"])

    def _add_3yc_fulfillment_params(
        self, agreement: dict, commitment_info: dict, parameters: dict
    ) -> dict:
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
        request_info = get_3yc_commitment_request(self._customer, is_recommitment=is_recommitment)
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

    def _prepare_agreement_line_prices(
        self, agreement: dict, currency: str, product_id: str
    ) -> None:
        agreement_lines = []
        for line in agreement["lines"]:
            if line["item"]["externalIds"]["vendor"] != "adobe-reseller-transfer":
                actual_sku = models.get_adobe_sku(line["item"]["externalIds"]["vendor"])
                agreement_lines.append((
                    line,
                    get_sku_with_discount_level(actual_sku, self._customer),
                ))

        skus = [item[1] for item in agreement_lines]
        prices = models.get_sku_price(self._customer, skus, product_id, currency)
        for line, actual_sku in agreement_lines:
            current_price = line["price"]["unitPP"]
            line["price"]["unitPP"] = prices[actual_sku]
            logger.info(
                "OneTime item: %s: sku=%s, current_price=%s, new_price=%s",
                line["id"],
                actual_sku,
                current_price,
                prices[actual_sku],
            )

    # REFACTOR: get method must not update subscriptions in mpt or terminate a subscription
    def _get_subscriptions_for_update(self, agreement: dict) -> list[tuple[dict, dict, str]]:  # noqa: C901
        logger.info("Getting subscriptions for update for agreement %s", agreement["id"])
        for_update = []

        for subscription in agreement["subscriptions"]:
            if subscription["status"] in {
                SubscriptionStatus.TERMINATED,
                SubscriptionStatus.EXPIRED,
            }:
                if not self._is_subscription_template_final(subscription):
                    template_name = (
                        TEMPLATE_SUBSCRIPTION_EXPIRED
                        if subscription["status"] == SubscriptionStatus.EXPIRED
                        else TEMPLATE_SUBSCRIPTION_TERMINATION
                    )
                    self._update_subscription_template(subscription, template_name)

                continue

            mpt_subscription = mpt.get_agreement_subscription(self._mpt_client, subscription["id"])
            adobe_subscription_id = mpt_subscription.get("externalIds", {}).get("vendor")

            adobe_subscription = find_first(
                partial(_check_adobe_subscription_id, adobe_subscription_id),
                self._adobe_subscriptions,
            )

            if not adobe_subscription:
                logger.error("No subscription found in Adobe customer data!")
                continue

            actual_sku = adobe_subscription["offerId"]

            if adobe_subscription["status"] == AdobeStatus.SUBSCRIPTION_TERMINATED:
                logger.info("Processing terminated Adobe subscription %s.", adobe_subscription_id)
                self._update_subscription_template(mpt_subscription, TEMPLATE_SUBSCRIPTION_EXPIRED)
                if self._dry_run:
                    logger.info(
                        "Dry run mode: skipping terminate subscription from agreement %s",
                        self.agreement_id,
                    )
                else:
                    mpt.terminate_subscription(
                        self._mpt_client,
                        mpt_subscription["id"],
                        f"Adobe subscription status {AdobeStatus.SUBSCRIPTION_TERMINATED}.",
                    )
                continue

            for_update.append((
                mpt_subscription,
                adobe_subscription,
                get_sku_with_discount_level(actual_sku, self._customer),
            ))

        return for_update

    def _is_subscription_template_final(self, subscription: dict) -> bool:
        template_name = subscription.get("template", {}).get("name")
        return template_name in {TEMPLATE_SUBSCRIPTION_EXPIRED, TEMPLATE_SUBSCRIPTION_TERMINATION}

    def _update_subscription_template(self, subscription: dict, template_name: str) -> None:
        template = mpt.get_template_by_name(self._mpt_client, self.product_id, template_name)
        if not template:
            return

        template_data = {
            "id": template.get("id"),
            "name": template.get("name"),
        }
        if self._dry_run:
            logger.info(
                "Dry run mode: skipping update agreement subscription %s with:\n template: %s",
                subscription["id"],
                template_data,
            )
        else:
            mpt.update_agreement_subscription(
                self._mpt_client, subscription["id"], template=template_data
            )

    def _check_update_airtable_missing_deployments(self, adobe_deployments: list[dict]) -> None:
        logger.info("Checking airtable for missing deployments for agreement %s", self.agreement_id)
        customer_deployment_ids = {cd["deploymentId"] for cd in adobe_deployments}
        airtable_deployment_ids = {
            ad.deployment_id
            for ad in models.get_gc_agreement_deployments_by_main_agreement(
                self.product_id, self.agreement_id
            )
        }
        missing_deployment_ids = customer_deployment_ids - airtable_deployment_ids
        if not missing_deployment_ids:
            return
        logger.info("Found missing deployments: %s", missing_deployment_ids)
        missing_deployments_data = []
        for missing_deployment_id in sorted(missing_deployment_ids):
            transfer = models.get_transfer_by_authorization_membership_or_customer(
                self.product_id,
                self._authorization_id,
                get_adobe_customer_id(self._agreement),
            )
            if not transfer:
                logger.info("No transfer found for missing deployment %s", missing_deployment_id)
                continue

            is_deployment_matched = partial(_is_deployment_matched, missing_deployment_id)
            deployment_currency = (
                find_first(is_deployment_matched, self._adobe_subscriptions, {})
            ).get("currency")
            missing_deployments_data.append({
                "deployment": find_first(
                    partial(_check_adobe_deployment_id, missing_deployment_id), adobe_deployments
                ),
                "transfer": transfer,
                "deployment_currency": deployment_currency,
            })

        if missing_deployments_data:
            deployment_model = models.get_gc_agreement_deployment_model(
                models.AirTableBaseInfo.for_migrations(self.product_id)
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
                        main_agreement_id=self.agreement_id,
                        account_id=self._agreement["client"]["id"],
                        seller_id=self._seller_id,
                        product_id=self.product_id,
                        membership_id=missing_deployment_data["transfer"].membership_id,
                        transfer_id=missing_deployment_data["transfer"].transfer_id,
                        status="pending",
                        customer_id=self._adobe_customer_id,
                        deployment_currency=missing_deployment_data["deployment_currency"],
                        deployment_country=missing_deployment_data["deployment"]["companyProfile"][
                            "address"
                        ]["country"],
                        licensee_id=self._licensee_id,
                    )
                )
            models.create_gc_agreement_deployments(self.product_id, missing_deployments)
            send_warning(
                "Missing deployments added to Airtable",
                f"agreement {self.agreement_id}, deployments: {missing_deployment_ids}.",
            )

    def _sync_global_customer_parameters(self, adobe_deployments: list[dict]) -> None:
        """
        Sync global customer parameters for the agreement.

        Args:
            adobe_deployments: Adobe customer deployments.
        """
        try:
            parameters = {Param.PHASE_FULFILLMENT.value: []}
            global_customer_enabled = get_global_customer(self._agreement)
            if global_customer_enabled != ["Yes"]:
                logger.info("Setting global customer for agreement %s", self.agreement_id)
                parameters[Param.PHASE_FULFILLMENT.value].append({
                    "externalId": "globalCustomer",
                    "value": ["Yes"],
                })

            deployments = [
                (
                    f"{deployment['deploymentId']} - "
                    f"{deployment['companyProfile']['address']['country']}"
                )
                for deployment in adobe_deployments
            ]
            agreement_deployments = get_deployments(self._agreement)
            if deployments != agreement_deployments:
                logger.info("Setting deployments for agreement %s", self.agreement_id)
                parameters[Param.PHASE_FULFILLMENT.value].append({
                    "externalId": "deployments",
                    "value": ",".join(deployments),
                })
                self._check_update_airtable_missing_deployments(adobe_deployments)
            if parameters[Param.PHASE_FULFILLMENT.value]:
                if self._dry_run:
                    logger.info(
                        "Dry run mode: skipping update agreement %s with:\n parameters: %s",
                        self.agreement_id,
                        parameters,
                    )
                else:
                    mpt.update_agreement(self._mpt_client, self.agreement_id, parameters=parameters)
        except Exception:
            logger.exception(
                "Error setting global customer parameters for agreement %s.",
                self.agreement_id,
            )
            notify_agreement_unhandled_exception_in_teams(self.agreement_id, traceback.format_exc())

    def _process_orphaned_deployment_subscriptions(self, deployment_agreements: list[dict]) -> None:
        logger.info("Looking for orphaned deployment subscriptions in Adobe.")

        mpt_subscription_ids = {
            subscription.get("externalIds", {}).get("vendor")
            for agreement in deployment_agreements
            for subscription in agreement["subscriptions"]
        }
        adobe_subscription_ids = {
            subscription["subscriptionId"]
            for subscription in self._adobe_subscriptions
            if subscription.get("deploymentId")
        }
        orphaned_subscription_ids = adobe_subscription_ids - mpt_subscription_ids

        for subscription in filter(
            partial(_is_subscription_in_set, orphaned_subscription_ids), self._adobe_subscriptions
        ):
            if subscription["autoRenewal"]["enabled"] is False:
                continue
            logger.warning("> Disabling auto-renewal for orphaned subscription %s", subscription)
            try:
                if self._dry_run:
                    logger.info(
                        "Dry run mode: skipping update orphaned subscription %s with:\n "
                        "auto_renewal False",
                        subscription["subscriptionId"],
                    )
                else:
                    self._adobe_client.update_subscription(
                        self._authorization_id,
                        self._adobe_customer_id,
                        subscription["subscriptionId"],
                        auto_renewal=False,
                    )
            except Exception as error:
                send_exception(
                    "Error disabling auto-renewal for orphaned Adobe subscription"
                    f" {subscription['subscriptionId']}.",
                    f"{error}",
                )

    def _sync_deployments_prices(self, adobe_deployments: list[dict], *, sync_prices: bool) -> None:
        """
        Sync deployment agreements prices.

        Args:
            adobe_deployments: Adobe customer deployments.
            sync_prices: If True also sync prices.
        """
        if not adobe_deployments:
            return

        deployment_agreements = mpt.get_agreements_by_customer_deployments(
            self._mpt_client,
            Param.DEPLOYMENT_ID.value,
            [deployment["deploymentId"] for deployment in adobe_deployments],
        )

        self._process_orphaned_deployment_subscriptions(deployment_agreements)

        active_deployment_agreements = [
            agreement
            for agreement in deployment_agreements
            if agreement["status"] == AgreementStatus.ACTIVE
        ]
        for deployment_agreement in active_deployment_agreements:
            subscriptions_for_update = self._get_subscriptions_for_update(deployment_agreement)
            if subscriptions_for_update:
                self._update_subscriptions(
                    deployment_agreement, subscriptions_for_update, sync_prices=sync_prices
                )

            self._update_agreement(deployment_agreement)

            self._sync_gc_3yc_agreements(deployment_agreement)

    def _sync_gc_3yc_agreements(self, deployment_agreement: dict) -> None:
        """
        Sync 3YC parameters from main agreement to provided deployment agreement.

        Args:
            deployment_agreement: MPT deployment agreement.
        """
        parameters_data = {
            "fulfillment": get_3yc_fulfillment_parameters(self._agreement),
        }
        if self._dry_run:
            logger.info(
                "Dry run mode: skipping update agreement gc_3yc %s with:\n parameters: %s",
                deployment_agreement["id"],
                parameters_data,
            )
        else:
            mpt.update_agreement(
                self._mpt_client,
                deployment_agreement["id"],
                parameters=parameters_data,
            )

    def _update_last_sync_date(self) -> None:
        logger.info("Updating Last Sync Date for agreement %s", self.agreement_id)
        parameters_data = {
            "fulfillment": [
                {
                    "externalId": Param.LAST_SYNC_DATE.value,
                    "value": dt.datetime.now(tz=dt.UTC).date().isoformat(),
                },
            ]
        }
        if self._dry_run:
            logger.info(
                "Dry run mode: skipping update agreement last sync date %s with:\n parameters: %s",
                self.agreement_id,
                parameters_data,
            )
        else:
            mpt.update_agreement(self._mpt_client, self.agreement_id, parameters=parameters_data)


def _is_deployment_matched(missing_deployment_id: str, subscription: dict) -> bool:
    return subscription.get("deploymentId") == missing_deployment_id


def _check_adobe_deployment_id(deployment_id: str, adobe_deployment: dict) -> bool:
    return adobe_deployment.get("deploymentId", "") == deployment_id


def _is_subscription_in_set(subscription_ids: set, subscription: dict) -> bool:
    return subscription["subscriptionId"] in subscription_ids
