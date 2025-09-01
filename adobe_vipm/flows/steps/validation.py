import datetime as dt
import itertools
import logging
from collections import Counter
from difflib import get_close_matches
from operator import attrgetter, itemgetter

from adobe_vipm.adobe.client import get_adobe_client
from adobe_vipm.adobe.config import get_config
from adobe_vipm.adobe.constants import AdobeStatus, ThreeYearCommitmentStatus
from adobe_vipm.adobe.errors import (
    AdobeAPIError,
    AdobeError,
    AdobeHttpError,
    AdobeProductNotFoundError,
)
from adobe_vipm.adobe.utils import (
    get_3yc_commitment_request,
    get_item_by_partial_sku,
    join_phone_number,
)
from adobe_vipm.adobe.validation import (
    is_valid_address_line_1_length,
    is_valid_address_line_2_length,
    is_valid_city_length,
    is_valid_company_name,
    is_valid_company_name_length,
    is_valid_country,
    is_valid_email,
    is_valid_first_last_name,
    is_valid_minimum_consumables,
    is_valid_minimum_licenses,
    is_valid_phone_number_length,
    is_valid_postal_code,
    is_valid_postal_code_length,
    is_valid_state_or_province,
)
from adobe_vipm.airtable.models import (
    STATUS_RUNNING,
    STATUS_SYNCHRONIZED,
    get_adobe_product_by_marketplace_sku,
)
from adobe_vipm.flows.constants import (
    ERR_3YC_NO_MINIMUMS,
    ERR_3YC_QUANTITY_CONSUMABLES,
    ERR_3YC_QUANTITY_LICENSES,
    ERR_ADDRESS,
    ERR_ADDRESS_LINE_1_LENGTH,
    ERR_ADDRESS_LINE_2_LENGTH,
    ERR_ADOBE_MEMBERSHIP_ID,
    ERR_ADOBE_MEMBERSHIP_ID_INACTIVE_ACCOUNT,
    ERR_ADOBE_MEMBERSHIP_NOT_FOUND,
    ERR_ADOBE_TRANSFER_PREVIEW,
    ERR_CITY_LENGTH,
    ERR_COMMITMENT_3YC_CONSUMABLES,
    ERR_COMMITMENT_3YC_EXPIRED_REJECTED_NO_COMPLIANT,
    ERR_COMMITMENT_3YC_LICENSES,
    ERR_COMMITMENT_3YC_VALIDATION,
    ERR_COMPANY_NAME_CHARS,
    ERR_COMPANY_NAME_LENGTH,
    ERR_CONTACT,
    ERR_COTERM_DATE_IN_LAST_24_HOURS,
    ERR_COUNTRY_CODE,
    ERR_DOWNSIZE_MINIMUM_3YC_CONSUMABLES,
    ERR_DOWNSIZE_MINIMUM_3YC_GENERIC,
    ERR_DUPLICATED_ITEMS,
    ERR_EMAIL_FORMAT,
    ERR_EXISTING_ITEMS,
    ERR_FIRST_NAME_FORMAT,
    ERR_INVALID_DOWNSIZE_QUANTITY,
    ERR_INVALID_ITEM_DOWNSIZE_FIRST_PO,
    ERR_INVALID_ITEM_DOWNSIZE_QUANTITY,
    ERR_INVALID_ITEM_DOWNSIZE_QUANTITY_ANY_COMBINATION,
    ERR_INVALID_TERMINATION_ORDER_QUANTITY,
    ERR_LAST_NAME_FORMAT,
    ERR_MARKET_SEGMENT_NOT_ELIGIBLE,
    ERR_MEMBERSHIP_ITEMS_DONT_MATCH,
    ERR_NO_RETURABLE_ERRORS_FOUND,
    ERR_PHONE_NUMBER_LENGTH,
    ERR_POSTAL_CODE_FORMAT,
    ERR_POSTAL_CODE_LENGTH,
    ERR_STATE_DID_YOU_MEAN,
    ERR_STATE_OR_PROVINCE,
    MARKET_SEGMENT_COMMERCIAL,
    STATUS_MARKET_SEGMENT_NOT_ELIGIBLE,
    STATUS_MARKET_SEGMENT_PENDING,
    TEMPLATE_NAME_PURCHASE,
    Param,
)
from adobe_vipm.flows.fulfillment.shared import switch_order_to_failed, switch_order_to_query
from adobe_vipm.flows.fulfillment.transfer import (
    check_gc_main_agreement,
    check_pending_deployments,
    get_order_line_items_with_deployment_id,
    manage_order_with_deployment_id,
    save_gc_parameters,
    submit_transfer_order,
)
from adobe_vipm.flows.pipeline import Step
from adobe_vipm.flows.steps.transfer import check_agreement_deployments
from adobe_vipm.flows.utils import get_ordering_parameter
from adobe_vipm.flows.utils.customer import is_within_coterm_window
from adobe_vipm.flows.utils.date import is_coterm_date_within_order_creation_window
from adobe_vipm.flows.utils.market_segment import (
    get_market_segment_eligibility_status,
    set_market_segment_eligibility_status_pending,
)
from adobe_vipm.flows.utils.order import (
    get_adobe_order_id,
    set_order_error,
)
from adobe_vipm.flows.utils.parameter import (
    get_coterm_date,
    set_ordering_parameter_error,
    update_ordering_parameter_value,
)
from adobe_vipm.flows.utils.subscription import get_subscription_by_line_subs_id
from adobe_vipm.flows.utils.validation import (
    is_purchase_validation_enabled,
    validate_subscription_and_returnable_orders,
)
from adobe_vipm.utils import get_3yc_commitment, get_partial_sku

logger = logging.getLogger(__name__)


class ValidateDuplicateLinesForOrder(Step):
    """Validates if Adobe Order contains duplicated items, with the same sku."""

    def __call__(self, client, context, next_step):
        """Validates if Adobe Order contains duplicated items, with the same sku."""
        items = [line["item"]["id"] for line in context.order["lines"]]
        duplicates = [item for item, count in Counter(items).items() if count > 1]
        if duplicates:
            switch_order_to_failed(
                client,
                context.order,
                ERR_DUPLICATED_ITEMS.to_dict(duplicates=",".join(duplicates)),
            )
            return

        items = []
        for subscription in context.order["agreement"]["subscriptions"]:
            for line in subscription["lines"]:
                items.append(line["item"]["id"])

        items.extend([
            line["item"]["id"] for line in context.order["lines"] if line["oldQuantity"] == 0
        ])
        duplicates = [item for item, count in Counter(items).items() if count > 1]
        if duplicates:
            switch_order_to_failed(
                client,
                context.order,
                ERR_EXISTING_ITEMS.to_dict(duplicates=",".join(duplicates)),
            )
            return

        next_step(client, context)


class ValidateDuplicateLines(Step):
    """
    Validates if there are duplicated lines.

    Lines with the same item ID within this order or new lines that are not duplicated
    within this order but that have already a subscription.
    """

    def __call__(self, client, context, next_step):
        """Validates if there are duplicated lines."""
        if not context.order["lines"]:
            next_step(client, context)
            return

        items = [line["item"]["id"] for line in context.order["lines"]]
        duplicates = [item for item, count in Counter(items).items() if count > 1]
        if duplicates:
            message = ERR_DUPLICATED_ITEMS.to_dict(duplicates=",".join(duplicates))
            context.order = set_order_error(context.order, message)
            logger.info("%s: %s", context, message)
            context.validation_succeeded = False
            return

        items = []
        for subscription in context.order["agreement"]["subscriptions"]:
            for line in subscription["lines"]:
                items.append(line["item"]["id"])

        items.extend([
            line["item"]["id"] for line in context.order["lines"] if line["oldQuantity"] == 0
        ])
        duplicates = [item for item, count in Counter(items).items() if count > 1]
        if duplicates:
            message = ERR_EXISTING_ITEMS.to_dict(duplicates=",".join(duplicates))
            context.order = set_order_error(
                context.order,
                message,
            )
            logger.info("%s: %s", context, message)
            context.validation_succeeded = False
            return
        next_step(client, context)


class ValidateReturnableOrders(Step):
    """
    Validates that all the lines that should be downsized can be processed.

    The sum of the quantity of one or more orders that can be returned
    matched the downsize quantity.
    If there are SKUs that cannot be downsized and no return order
    has been placed previously, the order will be failed.
    This can happen if the draft validation have been skipped or the order
    has been switched to `Processing` if a day or more have passed after
    the draft validation.
    """

    def __call__(self, client, context, next_step):
        """Validates that all the lines that should be downsized can be processed."""
        if (
            context.adobe_returnable_orders
            and not all(context.adobe_returnable_orders.values())
            and not context.adobe_return_orders
        ):
            non_returnable_skus = [
                k for k, v in context.adobe_returnable_orders.items() if v is None
            ]
            error = ERR_NO_RETURABLE_ERRORS_FOUND.to_dict(
                non_returnable_skus=", ".join(non_returnable_skus),
            )

            switch_order_to_failed(
                client,
                context.order,
                error,
            )
            logger.info("%s: failed due to %s", context, error["message"])
            return

        next_step(client, context)


class ValidateRenewalWindow(Step):
    """Check if the renewal window is open. In that case stop the order processing."""

    def __init__(self, *, is_validation=False):
        self.is_validation = is_validation

    def __call__(self, client, context, next_step):
        """Check if the renewal window is open. In that case stop the order processing."""
        if is_coterm_date_within_order_creation_window(context.order):
            coterm_date = get_coterm_date(context.order)
            logger.info(
                "%s: Order is being created within the last 24 hours of coterm date '%s'",
                context,
                coterm_date,
            )
            if self.is_validation:
                context.order = set_order_error(
                    context.order,
                    ERR_COTERM_DATE_IN_LAST_24_HOURS.to_dict(),
                )
            else:
                switch_order_to_failed(
                    client,
                    context.order,
                    ERR_COTERM_DATE_IN_LAST_24_HOURS.to_dict(),
                )
                return
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
                self.manage_order_error(client, context, error)
                return

            count_licenses, count_consumables = self.get_quantities(context, subscriptions)

            error = self.validate_minimum_quantity(
                context, commitment, count_licenses, count_consumables
            )
            if error:
                self.manage_order_error(client, context, error)
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
            self.manage_order_error(
                client,
                context,
                ERR_COMMITMENT_3YC_LICENSES.format(
                    selected_licenses=count_licenses, minimum_licenses=minimum_licenses_commited
                ),
            )
            return False

        if count_consumables < minimum_consumables_commited:
            self.manage_order_error(
                client,
                context,
                ERR_COMMITMENT_3YC_CONSUMABLES.format(
                    selected_consumables=count_consumables,
                    minimum_consumables=minimum_consumables_commited,
                ),
            )
            return False

        return True


def handle_transfer_preview_error(client, order, error):
    """Handle transfer preview errors."""
    if (
        isinstance(error, AdobeAPIError)
        and error.code
        in {
            AdobeStatus.TRANSFER_INVALID_MEMBERSHIP,
            AdobeStatus.TRANSFER_INVALID_MEMBERSHIP_OR_TRANSFER_IDS,
        }
    ) or (isinstance(error, AdobeHttpError) and error.status_code == 404):
        error_msg = (
            str(error) if isinstance(error, AdobeAPIError) else ERR_ADOBE_MEMBERSHIP_NOT_FOUND
        )
        param = get_ordering_parameter(order, Param.MEMBERSHIP_ID.value)
        order = set_ordering_parameter_error(
            order,
            Param.MEMBERSHIP_ID.value,
            ERR_ADOBE_MEMBERSHIP_ID.to_dict(title=param["name"], details=error_msg),
        )
        switch_order_to_query(client, order)
        return

    switch_order_to_failed(
        client,
        order,
        ERR_ADOBE_TRANSFER_PREVIEW.to_dict(error=str(error)),
    )


def _check_transfer(mpt_client, order, membership_id):
    """
    Checks the validity of a transfer order based on the provided parameters.

    Args:
        mpt_client (MPTClient): An instance of the Marketplace platform client.
        order (dict): The MPT order being processed.
        membership_id (str): The Adobe membership ID associated with the transfer.

    Returns:
        bool: True if the transfer is valid, False otherwise.
    """
    adobe_client = get_adobe_client()
    authorization_id = order["authorization"]["id"]
    transfer_preview = None
    try:
        transfer_preview = adobe_client.preview_transfer(authorization_id, membership_id)
    except AdobeError as e:
        handle_transfer_preview_error(mpt_client, order, e)
        logger.warning("Transfer order %s has been failed: %s.", order["id"], str(e))
        return False

    adobe_lines = sorted(
        [
            (get_partial_sku(item["offerId"]), item["quantity"])
            for item in transfer_preview["items"]
        ],
        key=itemgetter(0),
    )

    order_lines = sorted(
        [(line["item"]["externalIds"]["vendor"], line["quantity"]) for line in order["lines"]],
        key=itemgetter(0),
    )
    if adobe_lines != order_lines:
        error = ERR_MEMBERSHIP_ITEMS_DONT_MATCH.to_dict(
            lines=",".join([line[0] for line in adobe_lines]),
        )
        switch_order_to_failed(mpt_client, order, error)
        logger.warning("Transfer %s has been failed: %s.", order["id"], error["message"])
        return False
    return True


class ValidateMarketSegmentEligibility(Step):
    """
    Validate if the customer is eligible to place orders for a given market segment.

    The market segment the order refers to is determined by the product (product per segment).
    """

    def __call__(self, client, context, next_step):
        """Validate if the customer is eligible to place orders for a given market segment."""
        if context.market_segment != MARKET_SEGMENT_COMMERCIAL:
            status = get_market_segment_eligibility_status(context.order)
            if not status:
                context.order = set_market_segment_eligibility_status_pending(context.order)
                switch_order_to_query(client, context.order, template_name=TEMPLATE_NAME_PURCHASE)
                logger.info(
                    "%s: customer is pending eligibility approval for segment %s",
                    context,
                    context.market_segment,
                )
                return
            if status == STATUS_MARKET_SEGMENT_NOT_ELIGIBLE:
                logger.info(
                    "%s: customer is not eligible for segment %s",
                    context,
                    context.market_segment,
                )
                switch_order_to_failed(
                    client,
                    context.order,
                    ERR_MARKET_SEGMENT_NOT_ELIGIBLE.to_dict(segment=context.market_segment),
                )
                return
            if status == STATUS_MARKET_SEGMENT_PENDING:
                return
            logger.info("%s: customer is eligible for segment %s", context, context.market_segment)
        next_step(client, context)


class ValidateGCMainAgreement(Step):
    """Validates if the main agreement exists in Airtable and all deployments are synchronized."""

    def __call__(self, client, context, next_step):
        """Validates if the main agreement exists in Airtable."""
        if not check_gc_main_agreement(context.gc_main_agreement, context.order):
            return

        if context.gc_main_agreement:
            adobe_client = get_adobe_client()
            context.customer_deployments = adobe_client.get_customer_deployments_active_status(
                context.authorization_id, context.gc_main_agreement.customer_id
            )
            context.order = save_gc_parameters(client, context.order, context.customer_deployments)

        if not check_pending_deployments(
            context.gc_main_agreement, context.existing_deployments, context.customer_deployments
        ):
            return

        next_step(client, context)


class ValidateTransfer(Step):
    """Validates the transfer order by checking membership and items."""

    def __call__(self, client, context, next_step):
        """Validates the transfer order by checking membership and items."""
        context.adobe_order_id = get_adobe_order_id(context.order)
        if context.adobe_order_id:
            next_step(client, context)
            return

        if not _check_transfer(client, context.order, context.membership_id):
            return

        context.order = submit_transfer_order(client, context.order, context.membership_id)
        if not context.order:
            return

        context.adobe_order_id = context.order["externalIds"]["vendor"]
        next_step(client, context)


class ValidateDeploymentItems(Step):
    """Validates if order line items contain deployment IDs."""

    def __call__(self, client, context, next_step):
        """Validates if order line items contain deployment IDs."""
        context.items_with_deployment_id = get_order_line_items_with_deployment_id(
            context.adobe_transfer_order, context.order
        )
        if context.items_with_deployment_id:
            manage_order_with_deployment_id(
                client,
                context.order,
                context.adobe_transfer_order,
                context.gc_main_agreement,
                context.items_with_deployment_id,
            )
            return

        next_step(client, context)


class ValidateAgreementDeployments(Step):
    """Validates if the deployments exist in Airtable and if deployments are synchronized."""

    def __call__(self, client, context, next_step):
        """Checks if deployments exists in Airtable."""
        adobe_client = get_adobe_client()

        if not check_agreement_deployments(
            adobe_client,
            context.adobe_customer,
            context.adobe_transfer_order,
            context.existing_deployments,
            context.order,
            context.gc_main_agreement,
            context.customer_deployments,
        ):
            return

        next_step(client, context)


class ValidateDownsizes(Step):
    """Validates downsize items in order. Checks if it is possible to return them."""

    def _get_returnable_by_quantity_map(self, returnable_orders):
        returnable_by_quantity = {}
        for r in range(len(returnable_orders), 0, -1):
            for sub in itertools.combinations(returnable_orders, r):
                returnable_by_quantity[sum(line_item.quantity for line_item in sub)] = sub
        return returnable_by_quantity

    def __call__(self, client, context, next_step):  # noqa: C901
        """Validates downsize items in order. Checks if it is possible to return them."""
        adobe_client = get_adobe_client()
        errors = []

        if is_within_coterm_window(context.adobe_customer):
            logger.info(
                "Downsize occurs in the last two weeks before the anniversary date. "
                "Returnable orders are not going to be submitted, the renewal quantity "
                "will be updated. Skip downsize validation."
            )
            next_step(client, context)
            return

        for line in context.downsize_lines:
            subscription_id = get_subscription_by_line_subs_id(
                context.order["agreement"]["subscriptions"], line
            )
            returnable_orders = adobe_client.get_returnable_orders_by_subscription_id(
                context.authorization_id,
                context.adobe_customer_id,
                subscription_id,
                context.adobe_customer["cotermDate"],
            )
            if not returnable_orders:
                continue

            returnable_by_quantity = self._get_returnable_by_quantity_map(returnable_orders)
            delta = line["oldQuantity"] - line["quantity"]
            if delta not in returnable_by_quantity:
                end_of_cancellation_window = max(
                    dt.datetime.fromisoformat(roi.order["creationDate"])
                    .replace(tzinfo=dt.UTC)
                    .date()
                    for roi in returnable_orders
                ) + dt.timedelta(days=15)

                quantities = [
                    str(roi.quantity)
                    for roi in sorted(returnable_orders, key=attrgetter("quantity"))
                    if roi.quantity != line["oldQuantity"]
                ]
                if len(quantities) == 0:
                    message = ERR_INVALID_ITEM_DOWNSIZE_FIRST_PO.format(
                        item=line["item"]["name"],
                        delta=delta,
                        quantity=line["quantity"],
                    )
                    errors.append(message)
                    context.validation_succeeded = False
                    continue

                message = ERR_INVALID_ITEM_DOWNSIZE_QUANTITY.format(
                    item=line["item"]["name"],
                    delta=delta,
                    available_quantities=", ".join(quantities),
                    any_combination=(
                        ERR_INVALID_ITEM_DOWNSIZE_QUANTITY_ANY_COMBINATION
                        if len(quantities) > 1
                        else ""
                    ),
                    date=end_of_cancellation_window.isoformat(),
                )
                errors.append(message)
                context.validation_succeeded = False
                continue
        if errors:
            context.order = set_order_error(
                context.order,
                ERR_INVALID_DOWNSIZE_QUANTITY.to_dict(messages="\n".join(errors)),
            )
            return
        next_step(client, context)


class CheckPurchaseValidationEnabled(Step):
    """Checks that all required parameters for validation are marked as required."""

    def __call__(self, client, context, next_step):
        """Checks that all required parameters for validation are marked as required."""
        if not is_purchase_validation_enabled(context.order):
            return
        next_step(client, context)


class ValidateCustomerData(Step):
    """Validates provided customer data from the MPT order."""

    def validate_3yc(self, context):
        """
        Validates 3YC parameters in MPT order.

        Modifies context.order and context.validation_succeeded with errors in
        case if validation is failed.
        """
        p3yc = context.customer_data[Param.THREE_YC.value]

        if p3yc != ["Yes"]:
            return

        errors = False

        for param_name, validator, error in (
            (
                Param.THREE_YC_CONSUMABLES.value,
                is_valid_minimum_consumables,
                ERR_3YC_QUANTITY_CONSUMABLES,
            ),
            (Param.THREE_YC_LICENSES.value, is_valid_minimum_licenses, ERR_3YC_QUANTITY_LICENSES),
        ):
            param = get_ordering_parameter(context.order, param_name)

            if not validator(context.customer_data[param_name]):
                context.validation_succeeded = False
                context.order = set_ordering_parameter_error(
                    context.order,
                    param_name,
                    error.to_dict(title=param["name"]),
                    required=False,
                )

        if not errors and not (
            context.customer_data[Param.THREE_YC_LICENSES.value]
            or context.customer_data[Param.THREE_YC_CONSUMABLES.value]
        ):
            errors = True
            param_licenses = get_ordering_parameter(context.order, Param.THREE_YC_LICENSES.value)
            param_consumables = get_ordering_parameter(
                context.order, Param.THREE_YC_CONSUMABLES.value
            )
            context.validation_succeeded = False
            context.order = set_order_error(
                context.order,
                ERR_3YC_NO_MINIMUMS.to_dict(
                    title_min_licenses=param_licenses["name"],
                    title_min_consumables=param_consumables["name"],
                ),
            )

    def validate_company_name(self, context):
        """
        Validates Company name parameter in MPT order.

        Modifies context.order and context.validation_succeeded with errors in
        case if validation is failed.
        """
        param = get_ordering_parameter(context.order, Param.COMPANY_NAME.value)
        name = context.customer_data[Param.COMPANY_NAME.value]
        if not is_valid_company_name_length(name):
            context.validation_succeeded = False
            context.order = set_ordering_parameter_error(
                context.order,
                Param.COMPANY_NAME.value,
                ERR_COMPANY_NAME_LENGTH.to_dict(title=param["name"]),
            )
            return
        if not is_valid_company_name(name):
            context.validation_succeeded = False
            context.order = set_ordering_parameter_error(
                context.order,
                Param.COMPANY_NAME.value,
                ERR_COMPANY_NAME_CHARS.to_dict(title=param["name"]),
            )

    def validate_address(self, context):  # noqa: C901
        """
        Validates address parameter in MPT order.

        Modifies context.order and context.validation_succeeded with errors in
        case if validation is failed.
        """
        param = get_ordering_parameter(context.order, Param.ADDRESS.value)
        address = context.customer_data[Param.ADDRESS.value]
        errors = []

        country_code = address["country"]

        if not is_valid_country(country_code):
            errors.append(ERR_COUNTRY_CODE)
            context.validation_succeeded = False
            context.order = set_ordering_parameter_error(
                context.order,
                Param.ADDRESS.value,
                ERR_ADDRESS.to_dict(
                    title=param["name"],
                    errors="".join(errors),
                ),
            )
            return

        if not is_valid_state_or_province(country_code, address["state"]):
            config = get_config()
            country = config.get_country(country_code)
            state_error = ERR_STATE_OR_PROVINCE
            if country.provinces_to_code:  # pragma: no branch
                suggestions = get_close_matches(
                    address["state"],
                    list(country.provinces_to_code.keys()),
                )
                if suggestions:
                    if len(suggestions) > 1:
                        did_u_mean = ERR_STATE_DID_YOU_MEAN.format(
                            suggestion=", ".join(suggestions)
                        )
                        state_error = f"{state_error}{did_u_mean}"
                        errors.append(state_error)
                    else:
                        address["state"] = suggestions[0]
                else:
                    errors.append(state_error)
            else:  # pragma: no cover
                errors.append(state_error)

        if not is_valid_postal_code(country_code, address["postCode"]):
            errors.append(ERR_POSTAL_CODE_FORMAT)

        for field, validator_func, err_msg in (
            ("postCode", is_valid_postal_code_length, ERR_POSTAL_CODE_LENGTH),
            ("addressLine1", is_valid_address_line_1_length, ERR_ADDRESS_LINE_1_LENGTH),
            ("city", is_valid_city_length, ERR_CITY_LENGTH),
        ):
            if not validator_func(address[field]):
                errors.append(err_msg)

        if address["addressLine2"] and not is_valid_address_line_2_length(address["addressLine2"]):
            errors.append(ERR_ADDRESS_LINE_2_LENGTH)

        if errors:
            context.validation_succeeded = False
            context.order = set_ordering_parameter_error(
                context.order,
                Param.ADDRESS.value,
                ERR_ADDRESS.to_dict(
                    title=param["name"],
                    errors="; ".join(errors),
                ),
            )
            return
        context.order = update_ordering_parameter_value(
            context.order,
            Param.ADDRESS.value,
            address,
        )

    def validate_contact(self, context):  # noqa: C901
        """
        Validates contact parameter in MPT order.

        Modifies context.order and context.validation_succeeded with errors in
        case if validation is failed.
        """
        contact = context.customer_data[Param.CONTACT.value]
        param = get_ordering_parameter(context.order, Param.CONTACT.value)
        errors = []

        if not contact:
            context.validation_succeeded = False
            context.order = set_ordering_parameter_error(
                context.order,
                Param.CONTACT.value,
                ERR_CONTACT.to_dict(
                    title=param["name"],
                    errors="it is mandatory.",
                ),
            )
            return

        if not is_valid_first_last_name(contact["firstName"]):
            errors.append(ERR_FIRST_NAME_FORMAT)

        if not is_valid_first_last_name(contact["lastName"]):
            errors.append(ERR_LAST_NAME_FORMAT)

        if not is_valid_email(contact["email"]):
            errors.append(ERR_EMAIL_FORMAT)

        if contact.get("phone") and not is_valid_phone_number_length(
            join_phone_number(contact["phone"])
        ):
            errors.append(ERR_PHONE_NUMBER_LENGTH)

        if errors:
            context.validation_succeeded = False
            context.order = set_ordering_parameter_error(
                context.order,
                Param.CONTACT.value,
                ERR_CONTACT.to_dict(
                    title=param["name"],
                    errors="; ".join(errors),
                ),
            )

    def __call__(self, client, context, next_step):
        """Validates provided customer data from the MPT order."""
        self.validate_company_name(context)
        self.validate_address(context)
        self.validate_contact(context)
        self.validate_3yc(context)

        if not context.validation_succeeded:
            return

        next_step(client, context)


class ValidateDownsizesOnAdobe(Step):
    """Checks that for downsizes there orders to remove on Adobe side."""

    def __call__(self, client, context, next_step):
        """Checks that for downsizes there orders to remove on Adobe side."""
        adobe_client = get_adobe_client()
        for line in context.downsize_lines:
            subscription_id = get_subscription_by_line_subs_id(
                context.order["agreement"]["subscriptions"], line
            )
            is_valid, _ = validate_subscription_and_returnable_orders(
                adobe_client, context, line, subscription_id
            )
            if not is_valid:
                context.validation_succeeded = False
                context.order = set_order_error(
                    context.order,
                    ERR_INVALID_TERMINATION_ORDER_QUANTITY.to_dict(),
                )
                return

        next_step(client, context)


class ValidateTransferStatus(Step):
    """Checks transfer status for errors."""

    def __call__(self, mpt_client, context, next_step):
        """Checks transfer status for errors."""
        transfer = context.transfer
        order = context.order

        if transfer.status == STATUS_RUNNING:
            self._set_transfer_error(context, order, "Migration in progress, retry later")
            return
        if transfer.status == STATUS_SYNCHRONIZED:
            self._set_transfer_error(context, order, "Membership has already been migrated")
            return

        if context.adobe_transfer["status"] == AdobeStatus.TRANSFER_INACTIVE_ACCOUNT:
            context.order = set_ordering_parameter_error(
                context.order,
                Param.MEMBERSHIP_ID.value,
                ERR_ADOBE_MEMBERSHIP_ID_INACTIVE_ACCOUNT.to_dict(
                    status=context.adobe_transfer["status"],
                ),
            )
            context.validation_succeeded = False
            return

        next_step(mpt_client, context)

    def _set_transfer_error(self, context, order, details):
        param = get_ordering_parameter(order, Param.MEMBERSHIP_ID.value)
        context.order = set_ordering_parameter_error(
            order,
            Param.MEMBERSHIP_ID.value,
            ERR_ADOBE_MEMBERSHIP_ID.to_dict(title=param["name"], details=details),
        )
        context.validation_succeeded = False
