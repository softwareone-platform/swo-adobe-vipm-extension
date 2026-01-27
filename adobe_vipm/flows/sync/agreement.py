import datetime as dt
import logging
import traceback
from functools import partial
from typing import Any

from dateutil.relativedelta import relativedelta
from django.conf import settings
from mpt_extension_sdk.core.utils import setup_client
from mpt_extension_sdk.mpt_http import mpt
from mpt_extension_sdk.mpt_http.base import MPTClient
from mpt_extension_sdk.mpt_http.utils import find_first

from adobe_vipm.adobe.client import AdobeClient
from adobe_vipm.adobe.constants import THREE_YC_TEMP_3YC_STATUSES, AdobeStatus
from adobe_vipm.adobe.errors import AdobeAPIError, AuthorizationNotFoundError
from adobe_vipm.adobe.utils import get_3yc_commitment_request
from adobe_vipm.airtable import models
from adobe_vipm.flows import utils as flows_utils
from adobe_vipm.flows.constants import (
    MARKET_SEGMENT_EDUCATION,
    TEMPLATE_ASSET_DEFAULT,
    TEMPLATE_SUBSCRIPTION_EXPIRED,
    TEMPLATE_SUBSCRIPTION_TERMINATION,
    AgreementStatus,
    ItemTermsModel,
    Param,
    SubscriptionStatus,
)
from adobe_vipm.flows.mpt import get_agreements_by_3yc_commitment_request_invitation
from adobe_vipm.flows.sync.asset import AssetSyncer
from adobe_vipm.flows.sync.helper import check_adobe_subscription_id
from adobe_vipm.flows.sync.price_manager import PriceManager
from adobe_vipm.flows.sync.subscription import SubscriptionSyncer
from adobe_vipm.flows.utils import notify_agreement_unhandled_exception_in_teams
from adobe_vipm.flows.utils.market_segment import get_market_segment
from adobe_vipm.flows.utils.template import get_template_data_by_adobe_subscription
from adobe_vipm.notifications import send_exception, send_warning
from adobe_vipm.utils import get_3yc_commitment, get_partial_sku

logger = logging.getLogger(__name__)


class AgreementSyncer:  # noqa: WPS214
    """
    Sync agreement.

    Args:
        mpt_client: The MPT client used to interact  with the MPT.
        adobe_client: The Adobe client used to interact with Adobe API.
        agreement: The agreement to sync.
        adobe_customer: The Adobe customer data.
        adobe_subscriptions: List of the Adobe subscriptions.
        dry_run: If true, no changes will be made (dry run mode).
    """

    def __init__(
        self,
        mpt_client: MPTClient,
        adobe_client: AdobeClient,
        agreement: dict,
        adobe_customer: dict,
        adobe_subscriptions: list[dict],
        *,
        dry_run: bool,
    ):
        self._mpt_client = mpt_client
        self._adobe_client = adobe_client
        self._agreement = agreement
        self._adobe_customer = adobe_customer
        self._adobe_customer_id = adobe_customer["customerId"]
        self._adobe_subscriptions = adobe_subscriptions
        self._dry_run = dry_run
        self._authorization_id: str = agreement["authorization"]["id"]
        self._seller_id: str = agreement["seller"]["id"]
        self._licensee_id: str = agreement["licensee"]["id"]
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

            AssetSyncer(
                self._mpt_client,
                self.agreement_id,
                self._agreement["assets"],
                self._adobe_customer,
                self._adobe_subscriptions,
            ).sync(dry_run=self._dry_run)

            subscriptions_for_update = self._get_subscriptions_for_update(self._agreement)
            if subscriptions_for_update:
                SubscriptionSyncer(
                    self._mpt_client,
                    self._agreement,
                    self._adobe_customer,
                    self._adobe_subscriptions,
                    subscriptions_for_update,
                    dry_run=self._dry_run,
                ).sync(sync_prices=sync_prices)

            self._update_agreement_line_prices(self._agreement, self._currency, self.product_id)

            self._update_agreement(self._agreement)

            if self._adobe_customer.get("globalSalesEnabled", False):
                adobe_deployments = self._adobe_client.get_customer_deployments_active_status(
                    self._authorization_id, self._adobe_customer_id
                )
                self._sync_global_customer_parameters(adobe_deployments)

                deployment_id = flows_utils.get_parameter(
                    Param.PHASE_FULFILLMENT.value, self._agreement, Param.DEPLOYMENT_ID.value
                ).get("value", "")

                if not deployment_id and adobe_deployments:
                    self._process_main_agreement_deployments(
                        adobe_deployments, sync_prices=sync_prices
                    )

        except AuthorizationNotFoundError:
            logger.exception(
                "AuthorizationNotFoundError synchronizing agreement %s.", self.agreement_id
            )
        except Exception:
            logger.exception("Error synchronizing agreement %s.", self.agreement_id)
            flows_utils.notification.notify_agreement_unhandled_exception_in_teams(
                self.agreement_id, traceback.format_exc()
            )
        else:
            self._update_last_sync_date()
            self._agreement = mpt.get_agreement(self._mpt_client, self._agreement["id"])

    def _process_main_agreement_deployments(
        self, adobe_deployments: list[dict], *, sync_prices: bool
    ):
        self._check_update_airtable_missing_deployments(adobe_deployments)
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
        if active_deployment_agreements:
            self._sync_deployment_agreements(
                adobe_deployments, active_deployment_agreements, sync_prices=sync_prices
            )

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

        if not self._adobe_customer.get("discounts", []):
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
        deployment_id = flows_utils.get_deployment_id(self._agreement) or ""
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
        if not missing_adobe_subscriptions:
            logger.info("> No missing subscriptions found")
            return
        logger.warning("> Found missing subscriptions")

        items_map = {
            item["externalIds"]["vendor"]: item
            for item in mpt.get_product_items_by_skus(self._mpt_client, self.product_id, skus)
        }
        offer_ids = [
            flows_utils.get_sku_with_discount_level(
                adobe_subscription["offerId"], self._adobe_customer
            )
            for adobe_subscription in missing_adobe_subscriptions
        ]
        for adobe_subscription in missing_adobe_subscriptions:
            logger.info(">> Adding missing subscription %s", adobe_subscription["subscriptionId"])

            if adobe_subscription["currencyCode"] != currency:
                self._manage_wrong_currency_subscription(adobe_subscription)
                continue

            item = items_map[get_partial_sku(adobe_subscription["offerId"])]
            prices = models.get_sku_price(
                self._adobe_customer, offer_ids, self.product_id, currency
            )
            sku_discount_level = flows_utils.get_sku_with_discount_level(
                adobe_subscription["offerId"], self._adobe_customer
            )

            unit_price = {}
            if sku_discount_level in prices:
                unit_price = {"price": {"unitPP": prices.get(sku_discount_level)}}

            if item["terms"]["model"] == ItemTermsModel.ONE_TIME:
                self._create_mpt_asset(adobe_subscription, item, unit_price)
            else:
                self._create_mpt_subscription(
                    adobe_subscription, item, sku_discount_level, prices, unit_price
                )

    def _create_mpt_asset(
        self, adobe_subscription: dict[str, Any], item: dict[str, Any], unit_price: dict[str, Any]
    ) -> None:
        mpt_client = setup_client()
        template = mpt.get_asset_template_by_name(
            mpt_client, self.product_id, TEMPLATE_ASSET_DEFAULT
        )
        template_data = {"id": template["id"], "name": template["name"]} if template else None
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
            "template": template_data,
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

    def _update_agreement(self, agreement: dict) -> None:
        parameters = {}

        commitment_info = get_3yc_commitment(self._adobe_customer)
        self._update_3yc_fulfillment_params(agreement, commitment_info, parameters)
        self._update_3yc_ordering_params(commitment_info, parameters)

        parameters.setdefault(Param.PHASE_FULFILLMENT.value, [])
        parameters[Param.PHASE_FULFILLMENT.value].append({
            "externalId": Param.COTERM_DATE.value,
            "value": self._adobe_customer.get("cotermDate", ""),
        })

        if get_market_segment(self.product_id) == MARKET_SEGMENT_EDUCATION:
            self._add_education_market_sub_segments(parameters)

        self._execute_agreement_update(agreement, parameters)
        logger.info("Agreement updated %s", agreement["id"])

    def _execute_agreement_update(self, agreement: dict, parameters: dict) -> None:
        if self._dry_run:
            logger.info(
                "Dry run mode: skipping update for agreement %s with:\n lines: %s\n parameters: %s",
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

    def _update_3yc_fulfillment_params(
        self, agreement: dict, commitment_info: dict, parameters: dict
    ) -> None:
        parameters.setdefault(Param.PHASE_FULFILLMENT.value, [])
        three_yc_recommitment_par = flows_utils.get_parameter(
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
        request_info = get_3yc_commitment_request(
            self._adobe_customer, is_recommitment=is_recommitment
        )
        parameters[Param.PHASE_FULFILLMENT.value].append({
            "externalId": status_param_ext_id,
            "value": request_info.get("status"),
        })
        parameters.setdefault(request_type_param_phase, [])
        parameters[request_type_param_phase].append(
            {"externalId": request_type_param_ext_id, "value": None},
        )
        parameters[Param.PHASE_FULFILLMENT.value] += [
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

    def _update_3yc_ordering_params(self, commitment_info: dict, parameters: dict):
        parameters.setdefault(Param.PHASE_ORDERING.value, [])
        for mq in commitment_info.get("minimumQuantities", {}):
            if mq["offerType"] == "LICENSE":
                parameters[Param.PHASE_ORDERING.value].append({
                    "externalId": Param.THREE_YC_LICENSES.value,
                    "value": str(mq.get("quantity")),
                })
            if mq["offerType"] == "CONSUMABLES":
                parameters[Param.PHASE_ORDERING.value].append({
                    "externalId": Param.THREE_YC_CONSUMABLES.value,
                    "value": str(mq.get("quantity")),
                })

    def _update_agreement_line_prices(
        self, agreement: dict, currency: str, product_id: str
    ) -> None:
        agreement_lines = self._get_processable_agreement_lines(agreement)
        price_manager = PriceManager(
            self._mpt_client,
            self._adobe_customer,
            agreement_lines,
            self.agreement_id,
            self._agreement["listing"]["priceList"]["id"],
        )
        skus = [sku for _, sku in agreement_lines]
        prices = price_manager.get_sku_prices_for_agreement_lines(skus, product_id, currency)

        for line, actual_sku in agreement_lines:
            if actual_sku not in prices:
                continue

            current_price = line["price"]["unitPP"]
            line["price"]["unitPP"] = prices[actual_sku]
            logger.info(
                "OneTime item: %s: sku=%s, current_price=%s, new_price=%s",
                line["id"],
                actual_sku,
                current_price,
                prices[actual_sku],
            )

    def _get_processable_agreement_lines(self, agreement: dict) -> list[tuple[dict, str]]:
        agreement_lines = []
        for line in agreement["lines"]:
            if line["item"]["externalIds"]["vendor"] != "adobe-reseller-transfer":
                actual_sku = models.get_adobe_sku(line["item"]["externalIds"]["vendor"])
                agreement_lines.append((line, actual_sku))
        return agreement_lines

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
                partial(check_adobe_subscription_id, adobe_subscription_id),
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
                flows_utils.get_sku_with_discount_level(actual_sku, self._adobe_customer),
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

    def _check_update_airtable_missing_deployments(self, adobe_deployments: list[dict]) -> None:  # noqa: C901
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
                self._adobe_customer_id,
            )
            if not transfer:
                logger.info("No transfer found for missing deployment %s", missing_deployment_id)
                continue

            is_deployment_matched = partial(_is_deployment_matched, missing_deployment_id)
            deployment_currency = (
                find_first(is_deployment_matched, self._adobe_subscriptions, {})
            ).get("currencyCode")
            missing_deployments_data.append({
                "deployment": find_first(
                    partial(_check_adobe_deployment_id, missing_deployment_id), adobe_deployments
                ),
                "transfer": transfer,
                "deployment_currency": deployment_currency,
            })

        if missing_deployments_data:
            missing_deployments = []
            for missing_deployment_data in missing_deployments_data:
                logger.info(
                    "> Adding missing deployment to Airtable: %s",
                    missing_deployment_data["deployment"]["deploymentId"],
                )
                missing_deployments.append({
                    "deployment_id": missing_deployment_data["deployment"]["deploymentId"],
                    "main_agreement_id": self._agreement["id"],
                    "account_id": self._agreement["client"]["id"],
                    "seller_id": self._agreement["seller"]["id"],
                    "product_id": self._agreement["product"]["id"],
                    "membership_id": missing_deployment_data["transfer"].membership_id,
                    "transfer_id": missing_deployment_data["transfer"].transfer_id,
                    "status": "pending",
                    "customer_id": self._adobe_customer_id,
                    "deployment_currency": missing_deployment_data["deployment_currency"],
                    "deployment_country": missing_deployment_data["deployment"]["companyProfile"][
                        "address"
                    ]["country"],
                    "licensee_id": self._agreement["licensee"]["id"],
                })
            if self._dry_run:
                logger.info(
                    "Dry run mode: skip create gc agreement deployments in Airtablewith: %s",
                    missing_deployments,
                )
            else:
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
            global_customer_enabled = flows_utils.get_global_customer(self._agreement)
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
            agreement_deployments = flows_utils.get_deployments(self._agreement)
            if deployments != agreement_deployments:
                logger.info("Setting deployments for agreement %s", self.agreement_id)
                parameters[Param.PHASE_FULFILLMENT.value].append({
                    "externalId": "deployments",
                    "value": ",".join(deployments),
                })
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
            flows_utils.notification.notify_agreement_unhandled_exception_in_teams(
                self.agreement_id, traceback.format_exc()
            )

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
            if subscription["autoRenewal"]["enabled"] is False or subscription["status"] in {
                AdobeStatus.SUBSCRIPTION_INACTIVE.value,
                AdobeStatus.PENDING.value,
            }:
                logger.info(
                    "> Skipping orphaned subscription %s (auto-renewal: %s, status: %s)",
                    subscription["subscriptionId"],
                    subscription["autoRenewal"]["enabled"],
                    subscription["status"],
                )
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

    def _sync_deployment_agreements(
        self, adobe_deployments: list[dict], deployment_agreements, *, sync_prices: bool
    ) -> None:
        """
        Sync deployment agreements prices.

        Args:
            deployment_agreements: deployment agreements.
            adobe_deployments: Adobe customer deployments.
            sync_prices: If True also sync prices.
        """
        if not adobe_deployments:
            return

        for deployment_agreement in deployment_agreements:
            subscriptions_for_update = self._get_subscriptions_for_update(deployment_agreement)
            if subscriptions_for_update:
                SubscriptionSyncer(
                    self._mpt_client,
                    deployment_agreement,
                    self._adobe_customer,
                    self._adobe_subscriptions,
                    subscriptions_for_update,
                    dry_run=self._dry_run,
                ).sync(sync_prices=sync_prices)

            self._update_agreement(deployment_agreement)

            self._sync_gc_3yc_agreements(deployment_agreement)

    def _sync_gc_3yc_agreements(self, deployment_agreement: dict) -> None:
        """
        Sync 3YC parameters from main agreement to provided deployment agreement.

        Args:
            deployment_agreement: MPT deployment agreement.
        """
        parameters_data = {
            "fulfillment": flows_utils.get_3yc_fulfillment_parameters(self._agreement),
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

    def _add_education_market_sub_segments(self, parameters: dict) -> None:
        subsegments = self._adobe_customer.get("companyProfile", {}).get("marketSubSegments", [])
        parameters[Param.PHASE_FULFILLMENT.value].append({
            "externalId": Param.MARKET_EDUCATION_SUB_SEGMENTS.value,
            "value": ",".join(subsegments),
        })

    def _manage_wrong_currency_subscription(self, adobe_subscription: dict) -> None:
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
            send_exception(title="Price currency mismatch detected!", text=f"{adobe_subscription}")


def _is_deployment_matched(missing_deployment_id: str, subscription: dict) -> bool:
    return subscription.get("deploymentId") == missing_deployment_id


def _check_adobe_deployment_id(deployment_id: str, adobe_deployment: dict) -> bool:
    return adobe_deployment.get("deploymentId", "") == deployment_id


def _is_subscription_in_set(subscription_ids: set, subscription: dict) -> bool:
    return subscription["subscriptionId"] in subscription_ids


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
    param: str,
    *,
    dry_run: bool,
    sync_prices: bool,
) -> None:
    today = dt.datetime.now(tz=dt.UTC).date()
    today_iso = today.isoformat()
    yesterday = (today - dt.timedelta(days=1)).isoformat()
    rql_query = (
        "eq(status,Active)&"
        f"in(product.id,({','.join(settings.MPT_PRODUCTS_IDS)}))&"
        f"any(parameters.fulfillment,and(eq(externalId,{param}),eq(displayValue,{yesterday})))&"
        f"any(parameters.fulfillment,and(eq(externalId,{Param.LAST_SYNC_DATE.value}),ne(displayValue,{today_iso})))&"
        # Let's get only what we need
        "select=lines,parameters,assets,subscriptions,product,listing"
    )
    for agreement in mpt.get_agreements_by_query(mpt_client, rql_query):
        sync_agreement(
            mpt_client, adobe_client, agreement, dry_run=dry_run, sync_prices=sync_prices
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
        f"in(product.id,({','.join(settings.MPT_PRODUCTS_IDS)}))&"
        f"any(subscriptions,any(parameters.fulfillment,and(eq(externalId,renewalDate),in(displayValue,({','.join(yesterday_every_month)})))))&"
        f"any(parameters.fulfillment,and(eq(externalId,{Param.LAST_SYNC_DATE.value}),ne(displayValue,{today_iso})))&"
        # Let's get only what we need
        "select=lines,parameters,assets,subscriptions,product,listing"
    )
    for agreement in mpt.get_agreements_by_query(mpt_client, rql_query):
        sync_agreement(mpt_client, adobe_client, agreement, dry_run=dry_run, sync_prices=True)


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
        sync_agreement(
            mpt_client, adobe_client, agreement, dry_run=dry_run, sync_prices=sync_prices
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
            sync_agreement(mpt_client, adobe_client, agreement, dry_run=dry_run, sync_prices=True)
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
        sync_agreement(mpt_client, adobe_client, agreement, dry_run=dry_run, sync_prices=False)


def sync_agreement(
    mpt_client: MPTClient,
    adobe_client: AdobeClient,
    agreement: dict,
    *,
    dry_run: bool,
    sync_prices: bool,
):
    """
    Synchronizes a specific agreement with Adobe and MPT clients based on the given parameters.

    Args:
        mpt_client (MPTClient): Client interface to work with MPT data and services.
        adobe_client (AdobeClient): Client interface to interact with Adobe services.
        agreement (dict): A dictionary representing the agreement details to synchronize.
        dry_run (bool): Flag indicating whether to execute in dry-run mode (no actual changes).
        sync_prices (bool): Flag indicating whether to synchronize subscription prices.
    """
    if agreement["product"]["id"] not in settings.MPT_PRODUCTS_IDS:
        logger.error("Product %s not in MPT_PRODUCTS_IDS. Skipping.", agreement["product"]["id"])
        return

    adobe_customer_id = flows_utils.get_adobe_customer_id(agreement)
    if not adobe_customer_id:
        message = (
            f"CustomerId not found in Agreement {agreement['id']} with params "
            f"{agreement['parameters']}. Skipping."
        )
        logger.warning(message)
        notify_agreement_unhandled_exception_in_teams(agreement["id"], message)
        return

    adobe_customer = get_customer_or_process_lost_customer(
        mpt_client, adobe_client, agreement, adobe_customer_id, dry_run=dry_run
    )
    if not adobe_customer:
        # The agreement has been processed correctly via the lost customer procedure.
        # All subscriptions have been terminated, so no further action is needed.
        return

    authorization_id: str = agreement["authorization"]["id"]
    adobe_subscriptions = adobe_client.get_subscriptions(authorization_id, adobe_customer_id)[
        "items"
    ]

    AgreementSyncer(
        mpt_client, adobe_client, agreement, adobe_customer, adobe_subscriptions, dry_run=dry_run
    ).sync(sync_prices=sync_prices)


def get_customer_or_process_lost_customer(
    mpt_client: MPTClient,
    adobe_client: AdobeClient,
    agreement: dict,
    customer_id: str,
    *,
    dry_run: bool,
) -> dict | None:
    """
    Attempts to retrieve the customer using Adobe Client.

    Args:
        mpt_client: An instance of MPTClient used for managing lost customer processes.
        adobe_client: An instance of AdobeClient used for retrieving customer information.
        agreement: A dictionary containing the agreement details, including authorization
            information necessary for fetching customer data.
        customer_id: The unique identifier of the customer to be retrieved.
        dry_run: if True, it just simulates the process

    Returns:
        dict | None: Returns the customer details as a dictionary if successful. Returns
        None if the customer is determined to be invalid and the lost customer procedure
        is initiated.

    Raises:
        AdobeAPIError: If an error occurs during the customer retrieval process that is
        not related to invalid customer status.
    """
    try:
        return adobe_client.get_customer(agreement["authorization"]["id"], customer_id)
    except AdobeAPIError as error:
        if error.code == AdobeStatus.INVALID_CUSTOMER:
            logger.info(
                "Received Adobe error %s - %s, assuming lost customer "
                "and proceeding with lost customer procedure.",
                error.code,
                error.message,
            )
            if dry_run:
                logger.info("Dry run mode: skipping processing lost customer %s.", customer_id)
                return None

            send_warning(
                "Executing Lost Customer Procedure.",
                f"Received Adobe error {error.code} - {error.message},"
                " assuming lost customer and proceeding with lost customer procedure.",
            )
            _process_lost_customer(mpt_client, adobe_client, agreement, customer_id)
            return None
        raise


def _process_lost_customer(  # noqa: C901
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
            mpt.terminate_subscription(
                mpt_client,
                subscription_id,
                "Suspected Lost Customer",
            )
        except Exception as error:
            logger.exception(
                "> Suspected Lost Customer: Error terminating subscription %s.",
                subscription_id,
            )
            send_exception(
                f"> Suspected Lost Customer: Error terminating subscription {subscription_id}",
                f"{error}",
            )

    try:
        adobe_deployments = adobe_client.get_customer_deployments_active_status(
            agreement["authorization"]["id"], customer_id
        )
    except AdobeAPIError as error:
        msg = (
            f"Error getting customer deployments for Suspected Lost Customer {customer_id},"
            f" authorization {agreement['authorization']['id']}."
        )
        send_exception(msg, f"{error}")
        logger.exception(msg)
        return

    if adobe_deployments:
        deployment_agreements = mpt.get_agreements_by_customer_deployments(
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
                    mpt.terminate_subscription(
                        mpt_client, subscription_id, "Suspected Lost Customer"
                    )
                except Exception as error:
                    logger.exception(
                        "> Suspected Lost Customer: Error terminating subscription %s.",
                        subscription_id,
                    )
                    send_exception(
                        f"> Suspected Lost Customer: Error terminating subscription"
                        f" {subscription_id}",
                        f"{error}",
                    )
