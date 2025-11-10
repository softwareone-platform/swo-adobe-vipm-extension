"""This module contains orders helper functions."""

import datetime as dt
import logging
from operator import itemgetter

from dateutil import parser
from django.conf import settings
from mpt_extension_sdk.mpt_http.mpt import (
    get_agreement,
    get_licensee,
    update_order,
)

from adobe_vipm.adobe.client import get_adobe_client
from adobe_vipm.adobe.constants import AdobeStatus, ResellerChangeAction, ThreeYearCommitmentStatus
from adobe_vipm.adobe.errors import AdobeAPIError, AdobeProductNotFoundError
from adobe_vipm.adobe.utils import (
    get_3yc_commitment_request,
    get_item_by_partial_sku,
)
from adobe_vipm.airtable.models import (
    get_adobe_product_by_marketplace_sku,
    get_prices_for_skus,
)
from adobe_vipm.flows.constants import (
    ERR_ADOBE_GOVERNMENT_VALIDATE_IS_LGA,
    ERR_ADOBE_GOVERNMENT_VALIDATE_IS_NOT_LGA,
    ERR_ADOBE_RESSELLER_CHANGE_PREVIEW,
    ERR_COMMITMENT_3YC_CONSUMABLES,
    ERR_COMMITMENT_3YC_EXPIRED_REJECTED_NO_COMPLIANT,
    ERR_COMMITMENT_3YC_LICENSES,
    ERR_COMMITMENT_3YC_VALIDATION,
    ERR_CUSTOMER_LOST_EXCEPTION,
    ERR_DOWNSIZE_MINIMUM_3YC_CONSUMABLES,
    ERR_DOWNSIZE_MINIMUM_3YC_GENERIC,
    ERR_SKU_AVAILABILITY,
    MARKET_SEGMENT_GOVERNMENT,
    MARKET_SEGMENT_LARGE_GOVERNMENT_AGENCY,
    NUMBER_OF_DAYS_ALLOW_DOWNSIZE_IF_3YC,
    Param,
    TeamsColorCode,
)
from adobe_vipm.flows.errors import GovernmentLGANotValidOrderError, GovernmentNotValidOrderError
from adobe_vipm.flows.fulfillment.shared import handle_error, switch_order_to_failed
from adobe_vipm.flows.pipeline import Step
from adobe_vipm.flows.sync import sync_agreements_by_agreement_ids
from adobe_vipm.flows.utils import (
    get_adobe_customer_id,
    get_adobe_order_id,
    get_customer_data,
    get_due_date,
    get_market_segment,
    get_order_line_by_sku,
    get_ordering_parameter,
    get_price_item_by_line_sku,
    get_retry_count,
    reset_order_error,
    reset_ordering_parameters_error,
    set_customer_data,
    set_order_error,
    split_downsizes_upsizes_new,
)
from adobe_vipm.flows.utils.validation import validate_government_lga_data
from adobe_vipm.notifications import send_exception, send_notification
from adobe_vipm.utils import get_3yc_commitment, get_partial_sku

logger = logging.getLogger(__name__)


def populate_order_info(client, order: dict) -> dict:
    """
    Enrich the order with the full representation of the agreement object.

    Args:
        client (MPTClient): an instance of the Marketplace platform client.
        order: the order that is being processed.

    Returns:
        The enriched order.
    """
    order["agreement"] = get_agreement(client, order["agreement"]["id"])
    order["agreement"]["licensee"] = get_licensee(client, order["agreement"]["licensee"]["id"])

    return order


def manage_order_error(client, context, error_data, *, is_validation=False) -> None:
    """Set order error if is_validation flag is set, otherwise fail order."""
    if is_validation:
        context.order = set_order_error(context.order, error_data)
    else:
        switch_order_to_failed(client, context.order, error_data)


class PrepareCustomerData(Step):
    """Prepares customer data from order to Adobe format for futher processing."""

    def __call__(self, client, context, next_step):
        """Prepares customer data from order to Adobe format for futher processing."""
        licensee = context.order["agreement"]["licensee"]
        address = licensee["address"]
        contact = licensee.get("contact")

        customer_data_updated = False

        if not context.customer_data.get(Param.COMPANY_NAME.value):
            context.customer_data[Param.COMPANY_NAME.value] = licensee["name"]
            customer_data_updated = True

        if not context.customer_data.get(Param.ADDRESS.value):
            context.customer_data[Param.ADDRESS.value] = {
                "country": address["country"],
                "state": address["state"],
                "city": address["city"],
                "addressLine1": address["addressLine1"],
                "addressLine2": address.get("addressLine2"),
                "postCode": address["postCode"],
            }
            customer_data_updated = True

        if not context.customer_data.get(Param.CONTACT.value) and contact:
            context.customer_data[Param.CONTACT.value] = {
                "firstName": contact["firstName"],
                "lastName": contact["lastName"],
                "email": contact["email"],
                "phone": contact.get("phone"),
            }
            customer_data_updated = True

        if customer_data_updated:
            context.order = set_customer_data(context.order, context.customer_data)
            update_order(
                client,
                context.order_id,
                parameters=context.order["parameters"],
            )

        next_step(client, context)


class SetupContext(Step):
    """
    Initialize the processing context.

    Enrich the order with the full representations of the agreement and the licensee
    retrieving them.
    If the Adobe customerId fulfillment parameter is set, then retrieve the customer
    object from adobe and set it.
    """

    def __call__(self, client, context, next_step):
        """Initialize the processing context."""
        adobe_client = get_adobe_client()
        context.order = reset_order_error(context.order)
        context.order = reset_ordering_parameters_error(context.order)
        context.order["agreement"] = get_agreement(client, context.order["agreement"]["id"])
        context.order["agreement"]["licensee"] = get_licensee(
            client, context.order["agreement"]["licensee"]["id"]
        )
        context.downsize_lines, context.upsize_lines, context.new_lines = (
            split_downsizes_upsizes_new(
                context.order,
            )
        )

        retry_count = get_retry_count(context.order)
        if retry_count and int(retry_count) > 0:
            # when due date parameter is created and new code to process it
            # is released, it may happen
            # that there are order in processing, that don't have
            # due date parameter. If such orders were processed at least once
            # means retry_count is set and it is > 0
            # just setup due date to not to send email, like new order was
            # created
            context.due_date = dt.datetime.now(tz=dt.UTC).date() + dt.timedelta(
                days=int(settings.EXTENSION_CONFIG.get("DUE_DATE_DAYS"))
            )
        else:
            # usual due date processing for new orders
            # or when order was in processing when due date parameter
            # was added, but extension didn't try to process it still
            # means process it like usual order and send email notification
            context.due_date = get_due_date(context.order)

        context.order_id = context.order["id"]
        context.type = context.order["type"]
        context.agreement_id = context.order["agreement"]["id"]
        context.authorization_id = context.order["authorization"]["id"]
        context.product_id = context.order["agreement"]["product"]["id"]
        context.seller_id = context.order["agreement"]["seller"]["id"]
        context.currency = context.order["agreement"]["listing"]["priceList"]["currency"]
        context.customer_data = get_customer_data(context.order)
        context.market_segment = get_market_segment(context.product_id)
        context.adobe_customer_id = get_adobe_customer_id(context.order)
        if context.adobe_customer_id:
            try:
                context.adobe_customer = adobe_client.get_customer(
                    context.authorization_id,
                    context.adobe_customer_id,
                )
            except AdobeAPIError as ex:
                if ex.code == AdobeStatus.INVALID_CUSTOMER:
                    error = f"Received Adobe error {ex.code} - {ex.message}"
                    logger.info(
                        "Received Adobe error %s - %s, assuming lost customer "
                        "and proceeding to fail the order.",
                        ex.code,
                        ex.message,
                    )
                    send_notification(
                        f"Lost customer {context.adobe_customer_id}.",
                        f"{error}",
                        TeamsColorCode.ORANGE.value,
                    )
                    switch_order_to_failed(
                        client,
                        context.order,
                        ERR_CUSTOMER_LOST_EXCEPTION.to_dict(error=error),
                    )
                    sync_agreements_by_agreement_ids(
                        client, [context.agreement_id], dry_run=False, sync_prices=False
                    )
                    return
                logger.exception("%s: failed to retrieve Adobe customer.", context)
                return
        context.adobe_new_order_id = get_adobe_order_id(context.order)
        logger.info("%s: initialization completed.", context)
        next_step(client, context)


class Validate3YCCommitment(Step):
    """Validates 3YC parameters."""

    def __init__(self, *, is_validation=False):
        self.is_validation = is_validation

    def __call__(self, client, context, next_step):  # noqa: C901
        """Validates 3YC parameters."""
        is_new_purchase_order_validation = not context.adobe_customer

        if context.adobe_return_orders:
            next_step(client, context)
            return

        if is_new_purchase_order_validation:
            logger.info(
                "%s: No Adobe customer found, validating 3YC quantities parameters",
                context,
            )
            if self.validate_3yc_quantities_parameters(client, context):
                next_step(client, context)
            return

        commitment = get_3yc_commitment_request(
            context.adobe_customer,
            is_recommitment=False,
        ) or get_3yc_commitment(context.adobe_customer)

        adobe_client = get_adobe_client()
        commitment_status = commitment.get("status", "")

        if commitment_status == ThreeYearCommitmentStatus.REQUESTED and not self.is_validation:
            logger.info(
                "%s: 3YC commitment request is in status %s",
                context,
                ThreeYearCommitmentStatus.REQUESTED,
            )
            return

        if self._is_commitment_expired_or_rejected(commitment_status, commitment, context):
            switch_order_to_failed(
                client,
                context.order,
                ERR_COMMITMENT_3YC_EXPIRED_REJECTED_NO_COMPLIANT.to_dict(
                    status=commitment.get("status")
                ),
            )
            return

        if commitment:
            if self._validate_3yc_commitment_date_before_coterm_date(context, commitment):
                logger.info("%s: 3YC commitment end date is before coterm date", context)
                next_step(client, context)
                return

            subscriptions = adobe_client.get_subscriptions(
                context.authorization_id,
                context.adobe_customer_id,
            )

            is_valid, error = self.validate_items_in_subscriptions(context, subscriptions)
            if not is_valid:
                manage_order_error(
                    client,
                    context,
                    ERR_COMMITMENT_3YC_VALIDATION.to_dict(error=error),
                    is_validation=self.is_validation,
                )
                return

            count_licenses, count_consumables = self.get_quantities(context, subscriptions)

            error = self.validate_minimum_quantity(
                context, commitment, count_licenses, count_consumables
            )
            if error:
                manage_order_error(
                    client,
                    context,
                    ERR_COMMITMENT_3YC_VALIDATION.to_dict(error=error),
                    is_validation=self.is_validation,
                )
                return

        next_step(client, context)

    def _is_commitment_expired_or_rejected(self, commitment_status, commitment, context):
        """Check if commitment is expired, noncompliant, or rejected."""
        if commitment_status in {
            ThreeYearCommitmentStatus.EXPIRED,
            ThreeYearCommitmentStatus.NONCOMPLIANT,
            ThreeYearCommitmentStatus.DECLINED,
        }:
            logger.info("%s: 3YC commitment is expired or noncompliant", context)
            return True

        if not commitment and context.customer_data.get("3YC") == ["Yes"]:
            logger.info("%s: 3YC commitment has been rejected", context)
            return True

        return False

    def _validate_3yc_commitment_date_before_coterm_date(self, context, commitment):
        if not context.adobe_customer["cotermDate"]:
            return False

        threeyc_end_date = (
            dt.datetime.strptime(
                commitment["endDate"],
                "%Y-%m-%d",
            )
            .replace(tzinfo=dt.UTC)
            .date()
        )
        coterm_date = (
            dt.datetime.strptime(
                context.adobe_customer["cotermDate"],
                "%Y-%m-%d",
            )
            .replace(tzinfo=dt.UTC)
            .date()
        )
        return threeyc_end_date < coterm_date

    def get_quantities(self, context, subscriptions) -> tuple[float, float]:
        """Calculates licensees and consumables quantities of subscriptions."""
        count_licenses, count_consumables = self.get_licenses_and_consumables_count(subscriptions)

        count_licenses, count_consumables = self.process_lines_quantities(
            context,
            count_licenses=count_licenses,
            count_consumables=count_consumables,
            is_downsize=True,
        )

        count_licenses, count_consumables = self.process_lines_quantities(
            context,
            count_licenses=count_licenses,
            count_consumables=count_consumables,
            is_downsize=False,
        )

        return count_licenses, count_consumables

    def manage_order_error(self, client, context, error) -> None:
        """Set order error if is_validation flag is set, otherwise fail order."""
        if self.is_validation:
            context.order = set_order_error(
                context.order,
                ERR_COMMITMENT_3YC_VALIDATION.to_dict(error=error),
            )
        else:
            switch_order_to_failed(
                client,
                context.order,
                ERR_COMMITMENT_3YC_VALIDATION.to_dict(error=error),
            )

    def get_licenses_and_consumables_count(self, subscriptions: dict) -> tuple[float, float]:
        """
        Get the count of licenses and consumables from the Adobe customer subscriptions.

        Args:
            subscriptions: Adobe customer subscriptions.

        Returns:
            The count of licenses and consumables.
        """
        count_licenses = 0
        count_consumables = 0

        active_subscriptions = [
            sub for sub in subscriptions.get("items", []) if sub["autoRenewal"]["enabled"]
        ]
        for subscription in active_subscriptions:
            try:
                sku = get_adobe_product_by_marketplace_sku(get_partial_sku(subscription["offerId"]))
            except AdobeProductNotFoundError:
                logger.exception(
                    "Adobe product not found for SKU: %s", get_partial_sku(subscription["offerId"])
                )
                send_exception(
                    "Adobe product not found in airtable for SKU: %s",
                    get_partial_sku(subscription["offerId"]),
                )
                continue

            if not sku.is_valid_3yc_type():
                continue

            if sku.is_consumable():
                count_consumables += subscription["autoRenewal"][Param.RENEWAL_QUANTITY.value]
            else:
                count_licenses += subscription["autoRenewal"][Param.RENEWAL_QUANTITY.value]

        return count_licenses, count_consumables

    def process_lines_quantities(
        self,
        context,
        count_licenses=0,
        count_consumables=0,
        *,
        is_downsize=False,
    ) -> tuple[float, float]:
        """Calculates quantities for licensees and consumables for downsize or upsize lines."""
        lines = context.downsize_lines if is_downsize else context.upsize_lines + context.new_lines

        for line in lines:
            delta = self._calculate_delta(line, is_downsize)
            try:
                sku = get_adobe_product_by_marketplace_sku(line["item"]["externalIds"]["vendor"])
            except AdobeProductNotFoundError:
                logger.exception(
                    "Adobe product not found for SKU: %s", line["item"]["externalIds"]["vendor"]
                )
                send_exception(
                    "Adobe product not found in airtable for SKU: %s",
                    line["item"]["externalIds"]["vendor"],
                )
                continue

            if not sku.is_valid_3yc_type():
                continue

            count_licenses, count_consumables = self._update_counts(
                sku, delta, count_licenses, count_consumables, is_downsize=is_downsize
            )

        return count_licenses, count_consumables

    def _calculate_delta(self, line, is_downsize) -> float:
        """Calculate the quantity delta for a line."""
        if is_downsize:
            return line["oldQuantity"] - line["quantity"]
        return line["quantity"] - line["oldQuantity"]

    def _update_counts(self, sku, delta, count_licenses, count_consumables, *, is_downsize):
        """Update license and consumable counts based on SKU type and delta."""
        if sku.is_consumable():
            count_consumables += delta if not is_downsize else -delta
        else:
            count_licenses += delta if not is_downsize else -delta

        return count_licenses, count_consumables

    def validate_items_in_subscriptions(self, context, subscriptions) -> tuple[bool, str]:
        """Validates items quantities in subscriptions."""
        if subscriptions.get("items", []):
            for line in context.downsize_lines + context.upsize_lines:
                adobe_item = get_item_by_partial_sku(
                    subscriptions["items"], line["item"]["externalIds"]["vendor"]
                )
                if not adobe_item:
                    vendor_id = line["item"]["externalIds"]["vendor"]
                    return False, f"Item {vendor_id} not found in Adobe subscriptions"
        return True, None

    def validate_minimum_quantity(  # noqa: C901
        self,
        context,
        commitment,
        count_licenses,
        count_consumables,
    ):
        """Validates minimum items quantities in subscriptions."""
        is_invalid_license_minimum = False
        is_invalid_consumable_minimum = False
        minimum_licenses = 0
        minimum_consumables = 0

        for mq in commitment["minimumQuantities"]:
            if mq["offerType"] == "LICENSE" and count_licenses < mq["quantity"]:
                is_invalid_license_minimum = True
                minimum_licenses = mq["quantity"]
            if mq["offerType"] == "CONSUMABLES" and count_consumables < mq["quantity"]:
                is_invalid_consumable_minimum = True
                minimum_consumables = mq["quantity"]

        if is_invalid_consumable_minimum and is_invalid_license_minimum:
            logger.error(
                "%s: failed due to reduction quantity is not allowed below "
                "the minimum commitment of licenses and consumables",
                context,
            )
            return ERR_DOWNSIZE_MINIMUM_3YC_GENERIC.format(
                minimum_licenses=minimum_licenses,
                minimum_consumables=minimum_consumables,
            )

        if is_invalid_license_minimum:
            logger.error(
                "%s: failed due to reduction quantity is not allowed below "
                "the minimum commitment of licenses",
                context,
            )
            return ERR_COMMITMENT_3YC_LICENSES.format(
                selected_licenses=count_licenses, minimum_licenses=minimum_licenses
            )

        if is_invalid_consumable_minimum:
            logger.error(
                "%s: failed due to reduction quantity is not allowed below"
                " the minimum commitment of consumables",
                context,
            )
            return ERR_DOWNSIZE_MINIMUM_3YC_CONSUMABLES.format(
                selected_consumables=count_consumables, minimum_consumables=minimum_consumables
            )

        return None

    def validate_3yc_quantities_parameters(self, client, context):
        """
        Validate the 3YC commitment quantities are not allowed below the minimum commitment.

        For both licenses and consumables.
        """
        count_licenses, count_consumables = self.get_quantities(context, {})

        if count_licenses == 0 and count_consumables == 0:
            return True

        minimum_licenses_commited = int(context.customer_data.get("3YCLicenses", 0) or 0)
        minimum_consumables_commited = int(context.customer_data.get("3YCConsumables", 0) or 0)

        if count_licenses < minimum_licenses_commited:
            manage_order_error(
                client,
                context,
                ERR_COMMITMENT_3YC_VALIDATION.to_dict(
                    error=ERR_COMMITMENT_3YC_LICENSES.format(
                        selected_licenses=count_licenses, minimum_licenses=minimum_licenses_commited
                    )
                ),
                is_validation=self.is_validation,
            )
            return False

        if count_consumables < minimum_consumables_commited:
            manage_order_error(
                client,
                context,
                ERR_COMMITMENT_3YC_VALIDATION.to_dict(
                    error=ERR_COMMITMENT_3YC_CONSUMABLES.format(
                        selected_consumables=count_consumables,
                        minimum_consumables=minimum_consumables_commited,
                    )
                ),
                is_validation=self.is_validation,
            )
            return False

        return True


class UpdatePrices(Step):
    """Update prices based on airtable and adobe discount level."""

    def __call__(self, client, context, next_step):
        """Update prices based on airtable and adobe discount level."""
        if context.adobe_new_order or not context.adobe_preview_order:
            next_step(client, context)
            return

        self._client = client
        self._context = context
        self._actual_skus = self._get_actual_skus()
        logger.info("Actual SKUs: %s", self._actual_skus)
        prices = self._get_prices_for_skus()
        updated_lines = self._create_updated_lines(prices)
        self._update_order(updated_lines)

        next_step(self._client, self._context)

    def _get_actual_skus(self):
        """Extract SKUs from either new order or preview order."""
        return [item["offerId"] for item in self._context.adobe_preview_order["lineItems"]]

    def _get_prices_for_skus(self):
        """Get prices for SKUs."""
        preview_prices = {
            line_items["offerId"]: line_items["pricing"]["discountedPartnerPrice"]
            for line_items in self._context.adobe_preview_order["lineItems"]
        }
        logger.info("Preview prices: %s", preview_prices)
        return {sku: preview_prices[sku] for sku in self._actual_skus}

    def _create_updated_lines(self, prices):
        """Create updated order lines with new prices."""
        updated_lines = []

        # Update lines for actual SKUs
        for sku in self._actual_skus:
            line = get_order_line_by_sku(self._context.order, sku)
            new_price_item = get_price_item_by_line_sku(
                prices, line["item"]["externalIds"]["vendor"]
            )
            updated_lines.append({
                "id": line["id"],
                "price": {"unitPP": new_price_item[1]},
            })

        # Add remaining lines with unchanged prices
        updated_lines_ids = {line["id"] for line in updated_lines}
        order_lines = [
            line for line in self._context.order["lines"] if line["id"] not in updated_lines_ids
        ]
        mapped_lines = [
            {
                "id": line["id"],
                "price": {"unitPP": line["price"]["unitPP"]},
            }
            for line in order_lines
        ]
        updated_lines.extend(mapped_lines)

        return sorted(updated_lines, key=itemgetter("id"))

    def _update_order(self, lines):
        """Update the order with new prices."""
        update_order(self._client, self._context.order_id, lines=lines)
        logger.info("%s: order lines prices updated successfully", self._context)


class FetchResellerChangeData(Step):
    """Fetch reseller change data from Adobe."""

    def __init__(self, *, is_validation: bool) -> None:
        self.is_validation = is_validation

    def __call__(self, mpt_client, context, next_step):
        """Fetch reseller change data from Adobe."""
        if context.adobe_customer_id:
            next_step(mpt_client, context)
            return

        authorization_id = context.order["authorization"]["id"]
        seller_id = context.order["agreement"]["seller"]["id"]
        reseller_change_code = get_ordering_parameter(context.order, Param.CHANGE_RESELLER_CODE)
        admin_email = get_ordering_parameter(context.order, Param.ADOBE_CUSTOMER_ADMIN_EMAIL)

        adobe_client = get_adobe_client()

        logger.info(
            "%s: Executing the preview reseller change with %s and %s",
            context,
            reseller_change_code.get("value"),
            admin_email.get("value"),
        )
        try:
            context.adobe_transfer = adobe_client.reseller_change_request(
                authorization_id,
                seller_id,
                reseller_change_code.get("value"),
                admin_email.get("value"),
                ResellerChangeAction.PREVIEW,
            )
        except AdobeAPIError as ex:
            error_data = ERR_ADOBE_RESSELLER_CHANGE_PREVIEW.to_dict(
                reseller_change_code=reseller_change_code["value"],
                error=str(ex),
            )
            handle_error(
                mpt_client,
                context,
                error_data,
                is_validation=self.is_validation,
                parameter=Param.CHANGE_RESELLER_CODE,
            )
            return

        next_step(mpt_client, context)


class ValidateResellerChange(Step):
    """Validate the reseller change data."""

    def __init__(self, *, is_validation: bool) -> None:
        self.is_validation = is_validation

    def __call__(self, mpt_client, context, next_step):
        """Validate the reseller change data."""
        if context.adobe_customer_id:
            next_step(mpt_client, context)
            return

        expiry_date = context.adobe_transfer["approval"]["expiry"]
        reseller_change_code = get_ordering_parameter(context.order, Param.CHANGE_RESELLER_CODE)[
            "value"
        ]

        if parser.parse(expiry_date).date() < dt.datetime.now(tz=dt.UTC).date():
            error_data = ERR_ADOBE_RESSELLER_CHANGE_PREVIEW.to_dict(
                reseller_change_code=reseller_change_code,
                error="Reseller change code has expired",
            )
            handle_error(
                mpt_client,
                context,
                error_data,
                is_validation=self.is_validation,
                parameter=Param.CHANGE_RESELLER_CODE,
            )
            return

        next_step(mpt_client, context)


class ValidateSkuAvailability(Step):
    """Validate the SKU availability."""

    def __init__(self, *, is_validation: bool) -> None:
        self.is_validation = is_validation

    def __call__(self, mpt_client, context, next_step):
        """Validate the SKU availability."""
        commitment = get_3yc_commitment(context.adobe_customer)
        if commitment:
            # If the 3YCEndDate > today + 1 year, then the renewal quantity will be modifiable
            # and the validation will be ok
            commitment_end_date = dt.date.fromisoformat(commitment["endDate"])
            if commitment_end_date > (
                dt.datetime.now(tz=dt.UTC).date()
                + dt.timedelta(days=NUMBER_OF_DAYS_ALLOW_DOWNSIZE_IF_3YC)
            ):
                next_step(mpt_client, context)
                return

        adobe_skus = context.new_lines + context.upsize_lines + context.downsize_lines
        adobe_skus = [
            get_adobe_product_by_marketplace_sku(line["item"]["externalIds"]["vendor"]).sku
            for line in adobe_skus
        ]
        sku_prices = get_prices_for_skus(context.product_id, context.currency, adobe_skus)
        sku_prices = list(sku_prices.keys())
        missing_skus = [sku for sku in adobe_skus if sku not in sku_prices]
        if missing_skus:
            logger.warning(
                "SKU availability validation failed. Missing SKUs: %s. Available SKUs: %s",
                missing_skus,
                sku_prices,
            )
            context.validation_succeeded = False
            manage_order_error(
                mpt_client,
                context,
                ERR_SKU_AVAILABILITY.to_dict(missing_skus=missing_skus, available_skus=sku_prices),
                is_validation=self.is_validation,
            )
            return

        logger.info("SKU availability validation passed. All SKUs found in pricing.")
        next_step(mpt_client, context)


class ValidateGovernmentTransfer(Step):
    """Validate the government transfer."""

    def __init__(self, *, is_validation: bool) -> None:
        self.is_validation = is_validation

    def __call__(self, mpt_client, context, next_step):
        """Validate the government transfer."""
        if get_market_segment(context.order["product"]["id"]) not in {
            MARKET_SEGMENT_GOVERNMENT,
            MARKET_SEGMENT_LARGE_GOVERNMENT_AGENCY,
        }:
            next_step(mpt_client, context)
            return
        adobe_client = get_adobe_client()
        adobe_customer = adobe_client.get_customer(
            context.order["authorization"]["id"], context.customer_id
        )
        try:
            validate_government_lga_data(context.order, adobe_customer)
        except GovernmentLGANotValidOrderError:
            handle_error(
                mpt_client,
                context,
                ERR_ADOBE_GOVERNMENT_VALIDATE_IS_NOT_LGA.to_dict(),
                is_validation=self.is_validation,
                parameter=Param.MEMBERSHIP_ID,
            )
            return
        except GovernmentNotValidOrderError:
            handle_error(
                mpt_client,
                context,
                ERR_ADOBE_GOVERNMENT_VALIDATE_IS_LGA.to_dict(),
                is_validation=self.is_validation,
                parameter=Param.MEMBERSHIP_ID,
            )
            return

        next_step(mpt_client, context)
