import datetime as dt
import logging

from dateutil import parser
from mpt_extension_sdk.mpt_http.mpt import get_agreement, get_product_items_by_skus

from adobe_vipm.adobe.client import get_adobe_client
from adobe_vipm.adobe.constants import AdobeStatus, ThreeYearCommitmentStatus
from adobe_vipm.adobe.errors import AdobeAPIError, AdobeError, AdobeHttpError
from adobe_vipm.airtable.models import (
    STATUS_RUNNING,
    STATUS_SYNCHRONIZED,
    get_prices_for_3yc_skus,
    get_prices_for_skus,
    get_transfer_by_authorization_membership_or_customer,
)
from adobe_vipm.flows.constants import (
    ERR_ADOBE_CHANGE_RESELLER_CODE_EMPTY,
    ERR_ADOBE_MEMBERSHIP_ID,
    ERR_ADOBE_MEMBERSHIP_ID_EMPTY,
    ERR_ADOBE_MEMBERSHIP_ID_INACTIVE_ACCOUNT,
    ERR_ADOBE_MEMBERSHIP_ID_ITEM,
    ERR_ADOBE_MEMBERSHIP_NOT_FOUND,
    ERR_ADOBE_MEMBERSHIP_PROCESSING,
    ERR_ADOBE_RESSELLER_CHANGE_LINES,
    ERR_ADOBE_RESSELLER_CHANGE_PREVIEW,
    ERR_ADOBE_RESSELLER_CHANGE_PRODUCT_NOT_CONFIGURED,
    ERR_ADOBE_UNEXPECTED_ERROR,
    ERR_NO_SUBSCRIPTIONS_WITHOUT_DEPLOYMENT,
    ERR_UPDATING_TRANSFER_ITEMS,
    Param,
)
from adobe_vipm.flows.context import Context
from adobe_vipm.flows.pipeline import Pipeline, Step
from adobe_vipm.flows.utils import (
    are_all_transferring_items_expired,
    exclude_items_with_deployment_id,
    exclude_subscriptions_with_deployment_id,
    get_adobe_membership_id,
    get_order_line_by_sku,
    get_ordering_parameter,
    get_transfer_item_sku_by_subscription,
    has_order_line_updated,
    is_migrate_customer,
    is_transferring_item_expired,
    set_order_error,
    set_ordering_parameter_error,
)
from adobe_vipm.utils import get_3yc_commitment, get_partial_sku

logger = logging.getLogger(__name__)


def get_prices(order: dict, commitment: dict, adobe_skus: list[str]) -> dict[str, float]:
    """
    Get the purchase prices for the provided SKUs from airtable.

    Taking into account if the customer has committed for 3y.

    Args:
        order: The order for which the prices must be retrieved for determining
        the product and the currency.
        commitment: Customer 3YC data if any, None otherwise.
        adobe_skus: list of SKUs for which the prices must be retrieved.

    Returns:
        A dictionary with SKU, purchase price items.
    """
    currency = order["agreement"]["listing"]["priceList"]["currency"]
    product_id = order["agreement"]["product"]["id"]
    if (
        commitment
        and commitment["status"]
        in {ThreeYearCommitmentStatus.COMMITTED, ThreeYearCommitmentStatus.ACTIVE}
        and dt.date.fromisoformat(commitment["endDate"]) >= dt.datetime.now(tz=dt.UTC).date()
    ):
        return get_prices_for_3yc_skus(
            product_id,
            currency,
            dt.date.fromisoformat(commitment["startDate"]),
            adobe_skus,
        )

    return get_prices_for_skus(product_id, currency, adobe_skus)


def _update_order_lines(
    order: dict,
    adobe_items: list[dict],
    prices: dict[str, float],
    items_map: dict[str, dict],
    quantity_field: str,
    returned_skus: list[str],
    *,
    order_error: bool,  # TODO: that's a really strange parameter, you pass it down and return back
) -> tuple[bool, dict]:
    for adobe_line in adobe_items:
        item = items_map.get(get_partial_sku(adobe_line["offerId"]))
        if not item:
            param = get_ordering_parameter(order, Param.MEMBERSHIP_ID.value)
            order = set_ordering_parameter_error(
                order,
                Param.MEMBERSHIP_ID.value,
                ERR_ADOBE_MEMBERSHIP_ID_ITEM.to_dict(
                    title=param["name"],
                    item_sku=get_partial_sku(adobe_line["offerId"]),
                ),
            )
            order_error = True

            return order_error, order

        current_line = get_order_line_by_sku(order, get_partial_sku(adobe_line["offerId"]))
        if current_line:
            current_line["quantity"] = adobe_line[quantity_field]
        else:
            new_line = {
                "item": item,
                "quantity": adobe_line[quantity_field],
                "oldQuantity": 0,
            }
            new_line.setdefault("price", {})
            new_line["price"]["unitPP"] = prices.get(adobe_line["offerId"], 0)
            order["lines"].append(new_line)

    lines = [
        line for line in order["lines"] if line["item"]["externalIds"]["vendor"] in returned_skus
    ]
    order["lines"] = lines

    return order_error, order


def add_lines_to_order(
    mpt_client,
    order: dict,
    adobe_items: list[dict],
    commitment: dict,
    quantity_field: str,
    *,
    is_transferred=False,
) -> tuple[bool, dict]:
    """
    Add the lines that belongs to the provided Adobe VIP membership to the current order.

    Updates the purchase price of each line according to the customer discount level/benefits.

    Args:
        mpt_client (MPTClient): The client used to consume the MPT API.
        order: The order to validate.
        adobe_items: List of Adobe subscriptions to be migrated.
        commitment: Either the customer 3y commitment data or None if the customer doesn't
        have such benefit.
        quantity_field: The name of the field that contains the quantity depending on the
        provided `adobe_object` argument.
        is_transferred: True if the order has already been transferred, False otherwise.

    Returns:
        (True, order) if there is an error adding the lines, (False, order) otherwise.
    """
    order_error = False
    items = []

    if adobe_items:
        items = _get_items(adobe_items, mpt_client, order)
        if is_transferred:
            if are_all_transferring_items_expired(adobe_items):
                # If the order already has items and all the items on Adobe to be migrated are
                # expired, the user can add, edit or delete the expired subscriptions
                if len(order["lines"]):
                    return False, order

            else:
                adobe_items, order, order_error = _fail_validation_if_items_updated(
                    adobe_items,
                    order,
                    quantity_field,
                    order_error=order_error,
                )
        else:
            adobe_items = [item for item in adobe_items if not is_transferring_item_expired(item)]

    if not adobe_items:
        return _handle_empty_adobe_items(order)

    order_error, order = _get_updated_order_lines(
        adobe_items,
        commitment,
        items,
        order,
        quantity_field,
        order_error=order_error,
    )

    return order_error, order


def _handle_empty_adobe_items(order: dict) -> tuple[bool, dict]:
    if is_migrate_customer(order):
        order = set_ordering_parameter_error(
            order,
            Param.MEMBERSHIP_ID.value,
            ERR_ADOBE_MEMBERSHIP_ID_EMPTY.to_dict(),
        )
    return True, order


def _get_updated_order_lines(
    adobe_items: list[dict],
    commitment: dict,
    items: list[dict],
    order: dict,
    quantity_field: str,
    *,
    order_error: bool,
) -> tuple[bool, dict]:
    valid_skus = [get_partial_sku(item["offerId"]) for item in adobe_items]
    returned_full_skus = [item["offerId"] for item in adobe_items]
    prices = get_prices(order, commitment, returned_full_skus)
    items_map = {
        item["externalIds"]["vendor"]: item
        for item in items
        if item["externalIds"]["vendor"] in valid_skus
    }

    return _update_order_lines(
        order,
        adobe_items,
        prices,
        items_map,
        quantity_field,
        valid_skus,
        order_error=order_error,
    )


def _fail_validation_if_items_updated(
    adobe_items: list[dict],
    order: dict,
    quantity_field: str,
    *,
    order_error: bool,
) -> tuple[list[dict], dict, bool]:
    # remove expired items from adobe items
    non_expired_items = [item for item in adobe_items if not is_transferring_item_expired(item)]
    # If the order items has been updated, the validation order will fail
    if len(order["lines"]) and has_order_line_updated(
        order["lines"], non_expired_items, quantity_field
    ):
        order_error = True
        order = set_order_error(order, ERR_UPDATING_TRANSFER_ITEMS.to_dict())

    return non_expired_items, order, order_error


def _get_items(
    adobe_items: list[dict],
    mpt_client,
    order: dict,
) -> dict[str, dict]:
    returned_skus = [get_partial_sku(item["offerId"]) for item in adobe_items]

    return get_product_items_by_skus(mpt_client, order["agreement"]["product"]["id"], returned_skus)


def validate_transfer_not_migrated(mpt_client, order: dict) -> tuple[bool, dict]:
    """
    Validates a transfer that has not been already migrated by the mass migration tool.

    Args:
        mpt_client (MPTClient): The client used to consume the MPT API.
        order: The order to validate.

    Returns:
        (True, order) if there is a validation error, (False, order) otherwise.
    """
    authorization_id = order["authorization"]["id"]
    membership_id = get_adobe_membership_id(order)
    transfer_preview = None

    try:
        adobe_client = get_adobe_client()
        transfer_preview = adobe_client.preview_transfer(
            authorization_id,
            membership_id,
        )
    except AdobeAPIError as e:
        param = get_ordering_parameter(order, Param.MEMBERSHIP_ID.value)
        order = set_ordering_parameter_error(
            order,
            Param.MEMBERSHIP_ID.value,
            ERR_ADOBE_MEMBERSHIP_ID.to_dict(title=param["name"], details=str(e)),
        )
        return True, order
    except AdobeHttpError as he:
        err_msg = (
            ERR_ADOBE_MEMBERSHIP_NOT_FOUND if he.status_code == 404 else ERR_ADOBE_UNEXPECTED_ERROR
        )
        param = get_ordering_parameter(order, Param.MEMBERSHIP_ID.value)
        order = set_ordering_parameter_error(
            order,
            Param.MEMBERSHIP_ID.value,
            ERR_ADOBE_MEMBERSHIP_ID.to_dict(title=param["name"], details=err_msg),
        )
        return True, order
    commitment = get_3yc_commitment(transfer_preview)
    return add_lines_to_order(mpt_client, order, transfer_preview["items"], commitment, "quantity")


class SetupTransferContext(Step):
    """Setups Transfer context."""

    def __call__(self, mpt_client, context, next_step):
        """Setups Transfer context."""
        context.validation_succeeded = True
        context.order["agreement"] = get_agreement(mpt_client, context.order["agreement"]["id"])

        product_id = context.order["agreement"]["product"]["id"]
        authorization_id = context.order["authorization"]["id"]
        context.membership_id = get_adobe_membership_id(context.order)

        if is_migrate_customer(context.order):
            context.transfer = get_transfer_by_authorization_membership_or_customer(
                product_id,
                authorization_id,
                context.membership_id,
            )
        next_step(mpt_client, context)


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


class FetchTransferData(Step):
    """Fetches transfer data from Adobe."""

    def __call__(self, mpt_client, context, next_step):
        """Fetches transfer data from Adobe."""
        if not context.transfer:
            has_error, order = validate_transfer_not_migrated(mpt_client, context.order)
            context.order = order
            context.validation_succeeded = not has_error
            return

        try:
            adobe_client = get_adobe_client()
            subscriptions = adobe_client.get_subscriptions(
                context.order["authorization"]["id"],
                context.transfer.customer_id,
            )
            subscriptions = exclude_subscriptions_with_deployment_id(subscriptions)
            adobe_transfer = adobe_client.get_transfer(
                context.order["authorization"]["id"],
                context.transfer.membership_id,
                context.transfer.transfer_id,
            )
        except AdobeError as e:
            context.order = set_ordering_parameter_error(
                context.order,
                Param.MEMBERSHIP_ID.value,
                ERR_ADOBE_MEMBERSHIP_PROCESSING.to_dict(
                    membership_id=context.transfer.membership_id,
                    error=str(e),
                ),
            )
            context.validation_succeeded = False
            return

        context.subscriptions = subscriptions
        context.adobe_transfer = exclude_items_with_deployment_id(adobe_transfer)

        next_step(mpt_client, context)


class UpdateSubscriptionSkus(Step):
    """Update MPT subscription skus."""

    def __call__(self, mpt_client, context, next_step):
        """Update MPT subscription skus."""
        for subscription in context.subscriptions["items"]:
            correct_sku = get_transfer_item_sku_by_subscription(
                context.adobe_transfer, subscription["subscriptionId"]
            )
            subscription["offerId"] = correct_sku or subscription["offerId"]
        next_step(mpt_client, context)


class FetchCustomerAndValidateEmptySubscriptions(Step):
    """Validates transfer empty subscriptions for account revival."""

    def __call__(self, mpt_client, context, next_step):
        """Validates transfer empty subscriptions for account revival."""
        adobe_client = get_adobe_client()
        customer = adobe_client.get_customer(
            context.order["authorization"]["id"], context.transfer.customer_id
        )
        context.customer = customer

        if len(context.subscriptions["items"]) == 0:
            if customer.get("globalSalesEnabled", False):
                logger.error(ERR_NO_SUBSCRIPTIONS_WITHOUT_DEPLOYMENT)
                param = get_ordering_parameter(context.order, Param.MEMBERSHIP_ID.value)
                context.order = set_ordering_parameter_error(
                    context.order,
                    Param.MEMBERSHIP_ID.value,
                    ERR_ADOBE_MEMBERSHIP_ID.to_dict(
                        title=param["name"], details=ERR_NO_SUBSCRIPTIONS_WITHOUT_DEPLOYMENT
                    ),
                )
                context.validation_succeeded = False
                return
            context.validation_succeeded = True
            return

        next_step(mpt_client, context)


class AddLinesToOrder(Step):
    """Add adobe lines to order."""

    def __call__(self, mpt_client, context, next_step):
        """Add adobe lines to order."""
        commitment = get_3yc_commitment(context.customer)
        has_error, order = add_lines_to_order(
            mpt_client,
            context.order,
            context.subscriptions["items"],
            commitment,
            "currentQuantity",
            is_transferred=True,
        )
        context.order = order
        context.validation_succeeded = not has_error
        next_step(mpt_client, context)


def validate_transfer(mpt_client, order):
    """Validate transfer pipeline."""
    pipeline = Pipeline(
        SetupTransferContext(),
        FetchTransferData(),
        ValidateTransferStatus(),
        UpdateSubscriptionSkus(),
        FetchCustomerAndValidateEmptySubscriptions(),
        AddLinesToOrder(),
    )
    context = Context(order=order)
    pipeline.run(mpt_client, context)
    return not context.validation_succeeded, context.order


def validate_reseller_change(mpt_client, order):
    """Validate reseller change pipeline."""
    pipeline = Pipeline(
        SetupTransferContext(),
        FetchResellerChangeData(),
        ValidateResellerChange(),
        AddResellerChangeLinesToOrder(),
    )
    context = Context(order=order)
    pipeline.run(mpt_client, context)
    return not context.validation_succeeded, context.order


class FetchResellerChangeData(Step):
    """Fetch Adobe reseller change data."""

    def __call__(self, mpt_client, context, next_step):
        """Fetch Adobe reseller change data."""
        authorization_id = context.order["authorization"]["id"]
        seller_id = context.order["agreement"]["seller"]["id"]
        reseller_change_code = get_ordering_parameter(
            context.order, Param.CHANGE_RESELLER_CODE.value
        )
        admin_email = get_ordering_parameter(context.order, Param.ADOBE_CUSTOMER_ADMIN_EMAIL.value)

        adobe_client = get_adobe_client()

        try:
            context.adobe_transfer = adobe_client.preview_reseller_change(
                authorization_id,
                seller_id,
                reseller_change_code.get("value"),
                admin_email.get("value"),
            )
        except AdobeAPIError as e:
            context.order = set_ordering_parameter_error(
                context.order,
                Param.CHANGE_RESELLER_CODE.value,
                ERR_ADOBE_RESSELLER_CHANGE_PREVIEW.to_dict(
                    reseller_change_code=reseller_change_code["value"],
                    error=str(e),
                ),
            )
            context.validation_succeeded = False
            return

        next_step(mpt_client, context)


class ValidateResellerChange(Step):
    """Validates reseller change."""

    def __call__(self, mpt_client, context, next_step):
        """Validates reseller change."""
        expiry_date = context.adobe_transfer["approval"]["expiry"]
        reseller_change_code = get_ordering_parameter(
            context.order, Param.CHANGE_RESELLER_CODE.value
        )["value"
        ]

        parsed_expiry_date = parser.parse(expiry_date)

        if parsed_expiry_date.date() < dt.datetime.now(tz=dt.UTC).date():
            context.order = set_ordering_parameter_error(
                context.order,
                Param.CHANGE_RESELLER_CODE.value,
                ERR_ADOBE_RESSELLER_CHANGE_PREVIEW.to_dict(
                    reseller_change_code=reseller_change_code,
                    error="Reseller change code has expired",
                ),
            )
            context.validation_succeeded = False
            return

        if not context.adobe_transfer["lineItems"]:
            context.order = set_ordering_parameter_error(
                context.order,
                Param.CHANGE_RESELLER_CODE.value,
                ERR_ADOBE_CHANGE_RESELLER_CODE_EMPTY.to_dict(),
            )

        next_step(mpt_client, context)


class AddResellerChangeLinesToOrder(Step):
    """Add lines from reseller change back to the MPT order."""

    def __call__(self, mpt_client, context, next_step):
        """Add lines from reseller change back to the MPT order."""
        reseller_change_item = get_product_items_by_skus(
            mpt_client, context.order["agreement"]["product"]["id"], ["adobe-reseller-transfer"]
        )

        if not reseller_change_item:
            context.order = set_order_error(
                context.order, ERR_ADOBE_RESSELLER_CHANGE_PRODUCT_NOT_CONFIGURED.to_dict()
            )
            context.validation_succeeded = False
            return

        reseller_change_item = reseller_change_item[0]
        context.validation_succeeded = True

        lines = context.order["lines"]
        if lines:
            if len(lines) == 1 and lines[0]["item"]["id"] == reseller_change_item["id"]:
                next_step(mpt_client, context)
                return
            context.order = set_order_error(
                context.order, ERR_ADOBE_RESSELLER_CHANGE_LINES.to_dict()
            )
            context.validation_succeeded = False
        new_line = [
            {
                "item": reseller_change_item,
                "quantity": 1,
                "oldQuantity": 0,
                "price": {"unitPP": 0},
            }
        ]
        context.order["lines"] = new_line
        next_step(mpt_client, context)
