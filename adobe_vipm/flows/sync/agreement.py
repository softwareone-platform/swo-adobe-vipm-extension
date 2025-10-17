import copy
import datetime as dt
import logging
import sys
import traceback
from functools import partial

from mpt_extension_sdk.mpt_http import mpt
from mpt_extension_sdk.mpt_http.base import MPTClient
from mpt_extension_sdk.mpt_http.utils import find_first

from adobe_vipm.adobe.client import AdobeClient
from adobe_vipm.adobe.constants import AdobeStatus
from adobe_vipm.adobe.errors import (
    AuthorizationNotFoundError,
)
from adobe_vipm.adobe.utils import get_3yc_commitment_request
from adobe_vipm.airtable import models
from adobe_vipm.flows.constants import (
    TEMPLATE_SUBSCRIPTION_EXPIRED,
    AgreementStatus,
    AssetStatus,
    ItemTermsModel,
    Param,
    TeamsColorCode,
)
from adobe_vipm.flows.utils import (
    get_3yc_fulfillment_parameters,
    get_adobe_customer_id,
    get_deployment_id,
    get_deployments,
    get_global_customer,
    get_parameter,
    get_sku_with_discount_level,
    get_template_name_by_subscription,
    notify_agreement_unhandled_exception_in_teams,
    notify_missing_prices,
)
from adobe_vipm.notifications import send_exception, send_notification
from adobe_vipm.utils import get_3yc_commitment, get_commitment_start_date, get_partial_sku

logger = logging.getLogger(__name__)


class AgreementsSyncer:  # noqa: WPS214
    """
    Sync agreement.

    Attributes:
        _mpt_client (MPTClient): The MPT client used for interacting with the MPT system.
        _adobe_client (AdobeClient): The Adobe client used for interacting with Adobe API.
    """

    def __init__(
        self,
        mpt_client: MPTClient,
        adobe_client: AdobeClient,
        agreement: dict,
        customer: dict,
        adobe_subscriptions: list[dict],
    ):
        self._mpt_client = mpt_client
        self._adobe_client = adobe_client
        self._agreement = agreement
        self._customer = customer
        self._adobe_subscriptions = adobe_subscriptions
        self._authorization_id: str = agreement["authorization"]["id"]
        self._seller_id: str = agreement["seller"]["id"]
        self._licensee_id: str = agreement["licensee"]["id"]
        self._adobe_customer_id: str = get_adobe_customer_id(self._agreement)

    def sync(self, *, dry_run: bool, sync_prices: bool) -> None:  # noqa: C901
        """
        Sync agreement with parameters, prices from Adobe API, airtable to MPT agreement.

        Args:
            dry_run: If True do not update agreement.
            sync_prices: If true sync prices. Keep in mind dry_run parameter.
        """
        logger.info("Synchronizing agreement %s", self._agreement["id"])
        if self._agreement["status"] != AgreementStatus.ACTIVE:
            logger.info(
                "Skipping agreement %s because it is not in Active status", self._agreement["id"]
            )
            return
        try:
            if not self._is_sync_possible():
                return

            self._add_missing_subscriptions()

            assets_for_update = self._get_assets_for_update()
            self._update_assets(assets_for_update, dry_run=dry_run)
            subscriptions_for_update = self._get_subscriptions_for_update(self._agreement)
            if subscriptions_for_update:
                self._update_subscriptions(
                    self._agreement,
                    subscriptions_for_update,
                    dry_run=dry_run,
                    sync_prices=sync_prices,
                )

            self._update_agreement(self._agreement, dry_run=dry_run)

            if self._customer.get("globalSalesEnabled", False):
                adobe_deployments = self._adobe_client.get_customer_deployments_active_status(
                    self._authorization_id, self._adobe_customer_id
                )
                self._sync_global_customer_parameters(adobe_deployments)
                self._sync_deployments_prices(
                    adobe_deployments, dry_run=dry_run, sync_prices=sync_prices
                )

        except AuthorizationNotFoundError:
            logger.exception(
                "AuthorizationNotFoundError synchronizing agreement %s.", self._agreement["id"]
            )
        except Exception:
            logger.exception("Error synchronizing agreement %s.", self._agreement["id"])
            notify_agreement_unhandled_exception_in_teams(
                self._agreement["id"], traceback.format_exc()
            )
        else:
            if not dry_run:
                self._update_last_sync_date()
                self._agreement = mpt.get_agreement(self._mpt_client, self._agreement["id"])

    def _is_sync_possible(self):
        if any(
            filter(
                lambda sub: sub["status"] in {"Updating", "Terminating"},
                self._agreement["subscriptions"],
            ),
        ):
            logger.info("Agreement %s has processing subscriptions, skip it", self._agreement["id"])
            return False

        if not self._adobe_subscriptions:
            logger.info(
                "Skipping price sync - no subscriptions found for the customer %s",
                self._adobe_customer_id,
            )
            return False

        if not self._customer.get("discounts", []):
            msg = (
                "Error synchronizing agreement self._agreement['id']. Customer "
                f"{self._adobe_customer_id} does not have discounts information."
                f" Cannot proceed with price synchronization."
            )
            logger.error(msg)
            send_notification(
                "Customer does not have discounts information",
                msg,
                TeamsColorCode.ORANGE.value,
            )
            return False

        return True

    def _add_missing_subscriptions(self) -> None:
        buyer_id = self._agreement["buyer"]["id"]
        product_id = self._agreement["product"]["id"]
        currency = self._agreement["listing"]["priceList"]["currency"]
        deployment_id = get_deployment_id(self._agreement) or ""
        logger.info(
            "Checking missing subscriptions for agreement=%s, deployment=%s",
            self._agreement["id"],
            deployment_id,
        )
        adobe_subscriptions = tuple(
            a_s for a_s in self._adobe_subscriptions if a_s.get("deploymentId", "") == deployment_id
        )
        skus = {get_partial_sku(item["offerId"]) for item in adobe_subscriptions}
        mpt_entitlements_external_ids = {
            subscription["externalIds"]["vendor"]
            for subscription in self._agreement["subscriptions"] + self._agreement["assets"]
        }
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
            for item in mpt.get_product_items_by_skus(self._mpt_client, product_id, skus)
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
            prices = models.get_sku_price(
                self._customer,
                offer_ids,
                product_id,
                currency,
            )
            sku_discount_level = get_sku_with_discount_level(
                adobe_subscription["offerId"], self._customer
            )
            unit_price = {"price": {"unitPP": prices[sku_discount_level]}}
            if item["terms"]["model"] == ItemTermsModel.ONE_TIME:
                mpt.create_asset(
                    self._mpt_client,
                    {
                        "status": "Active",
                        "name": f"Asset for {item['name']}",
                        "agreement": {"id": self._agreement["id"]},
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
                        "product": {"id": product_id},
                        "buyer": {"id": buyer_id},
                        "licensee": {"id": self._licensee_id},
                        "seller": {"id": self._seller_id},
                    },
                )
            else:
                template_name = get_template_name_by_subscription(adobe_subscription)
                template = mpt.get_template_by_name(self._mpt_client, product_id, template_name)
                subscription = {
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
                    "agreement": {"id": self._agreement["id"]},
                    "buyer": {"id": buyer_id},
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
                    "product": {"id": product_id},
                    "autoRenew": adobe_subscription["autoRenewal"]["enabled"],
                }
                if template:
                    subscription["template"] = {
                        "id": template.get("id"),
                        "name": template.get("name"),
                    }
                mpt.create_agreement_subscription(self._mpt_client, subscription)

    def _update_subscriptions(
        self,
        agreement: dict,
        subscriptions_for_update: list[tuple[dict, dict, str]],
        *,
        dry_run: bool,
        sync_prices: bool,
    ) -> None:
        """
        Updates subscriptions by synchronizing prices and handling missing prices.

        Args:
            agreement (dict): A dictionary containing details about the agreement.
            subscriptions_for_update: subscriptions for update
            dry_run: Run command in a dry run mode
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
                dry_run=dry_run,
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

        self._log_agreement_lines(agreement, currency, product_id, dry_run=dry_run)

    def _update_subscription(
        self,
        actual_sku: str,
        product_id: str,
        adobe_subscription: dict,
        coterm_date: str,
        prices: dict,
        subscription: dict,
        *,
        dry_run: bool,
        sync_prices: bool,
    ) -> None:
        line_id = subscription["lines"][0]["id"]
        # A business requirement for Adobeis is that that subscription has 1-1 relation with item.

        if not dry_run:
            logger.info(
                "Updating subscription: %s (%s): sku=%s",
                subscription["id"],
                line_id,
                actual_sku,
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
                        "value": str(
                            adobe_subscription["autoRenewal"][Param.RENEWAL_QUANTITY.value]
                        ),
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

            template_name = get_template_name_by_subscription(adobe_subscription)
            template = mpt.get_template_by_name(self._mpt_client, product_id, template_name)

            mpt.update_agreement_subscription(
                self._mpt_client,
                subscription["id"],
                lines=lines,
                parameters=parameters,
                commitmentDate=coterm_date,
                autoRenew=adobe_subscription["autoRenewal"]["enabled"],
                template={
                    "id": template.get("id"),
                    "name": template.get("name"),
                },
            )

        else:
            logger.info(
                "NOT updating subscription due to dry_run=%s: "
                "Subscription: %s (%s), "
                "sku=%s, "
                "current_price=%s, "
                "new_price=%s, "
                "auto_renew=%s, "
                "current_quantity=%s, "
                "renewal_quantity=%s, "
                "renewal_date=%s, "
                "commitment_date=%s",
                dry_run,
                subscription["id"],
                line_id,
                actual_sku,
                subscription["lines"][0]["price"]["unitPP"],
                prices[actual_sku],
                adobe_subscription["autoRenewal"]["enabled"],
                adobe_subscription["currentQuantity"],
                adobe_subscription["autoRenewal"]["renewalQuantity"],
                adobe_subscription["renewalDate"],
                coterm_date,
            )

    def _update_agreement(self, agreement: dict, *, dry_run: bool) -> None:
        parameters = {}
        commitment_info = get_3yc_commitment(self._customer)
        if commitment_info:
            parameters = self._add_3yc_fulfillment_params(agreement, commitment_info, parameters)
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
            "value": self._customer.get("cotermDate", ""),
        })
        if not dry_run:
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

    def _log_agreement_lines(
        self, agreement: dict, currency: str, product_id: str, *, dry_run: bool
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

            if dry_run:
                sys.stdout.write(
                    f"OneTime item: {line['id']}: sku={actual_sku}, current_price={current_price}, "
                    f"new_price={prices[actual_sku]}\n",
                )
            else:
                logger.info("OneTime item: %s: sku=%s\n", line["id"], actual_sku)

    def _update_assets(
        self, assets_for_update: list[tuple[dict, dict, str]], *, dry_run: bool
    ) -> None:
        for asset, adobe_subscription, actual_sku in assets_for_update:
            parameters = {
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

            if not dry_run:
                logger.info("Updating asset: %s: sku=%s", asset["id"], actual_sku)
                mpt.update_asset(self._mpt_client, asset["id"], parameters=parameters)
            else:
                current_quantity = get_parameter("fulfillment", asset, "usedQuantity")["value"]
                sys.stdout.write(
                    f"Asset: {asset['id']}: sku={actual_sku}, "
                    f"current used quantity={current_quantity}, "
                    f"new used quantity={adobe_subscription['usedQuantity']}"
                )

    def _get_assets_for_update(self) -> list[tuple[dict, dict, str]]:
        logger.info("Getting assets for update for agreement %s", self._agreement["id"])

        for_update = []
        for asset in self._agreement["assets"]:
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

    def _get_subscriptions_for_update(self, agreement: dict) -> list[tuple[dict, dict, str]]:
        logger.info("Getting subscriptions for update for agreement %s", agreement["id"])
        for_update = []

        for subscription in agreement["subscriptions"]:
            if subscription["status"] in {
                SubscriptionStatus.TERMINATED,
                SubscriptionStatus.EXPIRED,
            }:
                continue

            mpt_subscription = mpt.get_agreement_subscription(self._mpt_client, subscription["id"])
            adobe_subscription_id = mpt_subscription["externalIds"]["vendor"]

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
                template = mpt.get_template_by_name(
                    self._mpt_client,
                    agreement["product"]["id"],
                    TEMPLATE_SUBSCRIPTION_EXPIRED,
                )
                if template:
                    mpt.update_agreement_subscription(
                        self._mpt_client,
                        mpt_subscription["id"],
                        template={
                            "id": template.get("id"),
                            "name": template.get("name"),
                        },
                    )
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

    def _check_update_airtable_missing_deployments(self, adobe_deployments: list[dict]) -> None:
        agreement_id = self._agreement["id"]
        product_id = self._agreement["product"]["id"]
        logger.info("Checking airtable for missing deployments for agreement %s", agreement_id)
        customer_deployment_ids = {cd["deploymentId"] for cd in adobe_deployments}
        airtable_deployment_ids = {
            ad.deployment_id
            for ad in models.get_gc_agreement_deployments_by_main_agreement(
                product_id, agreement_id
            )
        }
        missing_deployment_ids = customer_deployment_ids - airtable_deployment_ids
        if not missing_deployment_ids:
            return
        logger.info("Found missing deployments: %s", missing_deployment_ids)
        missing_deployments_data = []
        for missing_deployment_id in sorted(missing_deployment_ids):
            transfer = models.get_transfer_by_authorization_membership_or_customer(
                product_id,
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
                        account_id=self._agreement["client"]["id"],
                        seller_id=self._seller_id,
                        product_id=product_id,
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
            models.create_gc_agreement_deployments(product_id, missing_deployments)
            send_notification(
                "Missing deployments added to Airtable",
                f"agreement {agreement_id}, deployments: {missing_deployment_ids}.",
                TeamsColorCode.ORANGE.value,
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
                logger.info("Setting global customer for agreement %s", self._agreement["id"])
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
                logger.info("Setting deployments for agreement %s", self._agreement["id"])
                parameters[Param.PHASE_FULFILLMENT.value].append({
                    "externalId": "deployments",
                    "value": ",".join(deployments),
                })
                self._check_update_airtable_missing_deployments(adobe_deployments)
            if parameters[Param.PHASE_FULFILLMENT.value]:
                mpt.update_agreement(self._mpt_client, self._agreement["id"], parameters=parameters)
        except Exception:
            logger.exception(
                "Error setting global customer parameters for agreement %s.",
                self._agreement["id"],
            )
            notify_agreement_unhandled_exception_in_teams(
                self._agreement["id"], traceback.format_exc()
            )

    def _process_orphaned_deployment_subscriptions(self, deployment_agreements: list[dict]) -> None:
        logger.info("Looking for orphaned deployment subscriptions in Adobe.")

        mpt_subscription_ids = {
            subscription["externalIds"]["vendor"]
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
            logger.warning("> Disabling auto-renewal for orphaned subscription %s", subscription)
            try:
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

    def _sync_deployments_prices(
        self, adobe_deployments: list[dict], *, dry_run: bool, sync_prices: bool
    ) -> None:
        """
        Sync deployment agreements prices.

        Args:
            adobe_deployments: Adobe customer deployments.
            dry_run: Run command in a dry run mode.
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

        for deployment_agreement in deployment_agreements:
            subscriptions_for_update = self._get_subscriptions_for_update(deployment_agreement)
            if subscriptions_for_update:
                self._update_subscriptions(
                    deployment_agreement,
                    subscriptions_for_update,
                    dry_run=dry_run,
                    sync_prices=sync_prices,
                )

            self._update_agreement(deployment_agreement, dry_run=dry_run)

            self._sync_gc_3yc_agreements(deployment_agreement, dry_run=dry_run)

    def _sync_gc_3yc_agreements(self, deployment_agreement: dict, *, dry_run: bool) -> None:
        """
        Sync 3YC parameters from main agreement to provided deployment agreement.

        Args:
            deployment_agreement: MPT deployment agreement.
            dry_run: If True do not update agreement. Only simulate sync.
        """
        parameters_3yc = get_3yc_fulfillment_parameters(self._agreement)

        if not dry_run:
            mpt.update_agreement(
                self._mpt_client,
                deployment_agreement["id"],
                parameters={
                    "fulfillment": parameters_3yc,
                },
            )

    def _update_last_sync_date(self) -> None:
        logger.info("Updating Last Sync Date for agreement %s", self._agreement["id"])

        mpt.update_agreement(
            self._mpt_client,
            self._agreement["id"],
            parameters={
                "fulfillment": [
                    {
                        "externalId": Param.LAST_SYNC_DATE.value,
                        "value": dt.datetime.now(tz=dt.UTC).date().isoformat(),
                    },
                ]
            },
        )


def _check_adobe_subscription_id(subscription_id, adobe_subscription):
    return adobe_subscription.get("subscriptionId", "") == subscription_id


def _is_deployment_matched(missing_deployment_id: str, subscription: dict) -> bool:
    return subscription.get("deploymentId") == missing_deployment_id


def _check_adobe_deployment_id(deployment_id: str, adobe_deployment: dict) -> bool:
    return adobe_deployment.get("deploymentId", "") == deployment_id


def _is_subscription_in_set(subscription_ids: set, subscription: dict) -> bool:
    return subscription["subscriptionId"] in subscription_ids
