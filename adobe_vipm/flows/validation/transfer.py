import logging
from datetime import date

from adobe_vipm.adobe.config import get_config
from adobe_vipm.adobe.constants import (
    STATUS_3YC_COMMITTED,
    STATUS_TRANSFER_INACTIVE_ACCOUNT,
)
from adobe_vipm.adobe.errors import AdobeAPIError, AdobeHttpError
from adobe_vipm.adobe.utils import get_3yc_commitment
from adobe_vipm.flows.airtable import (
    STATUS_RUNNING,
    STATUS_SYNCHRONIZED,
    get_prices_for_3yc_skus,
    get_prices_for_skus,
    get_transfer_by_authorization_membership_or_customer,
)
from adobe_vipm.flows.constants import (
    ERR_ADOBE_MEMBERSHIP_ID,
    ERR_ADOBE_MEMBERSHIP_ID_EMPTY,
    ERR_ADOBE_MEMBERSHIP_ID_INACTIVE_ACCOUNT,
    ERR_ADOBE_MEMBERSHIP_ID_ITEM,
    ERR_ADOBE_MEMBERSHIP_NOT_FOUND,
    ERR_ADOBE_UNEXPECTED_ERROR,
    PARAM_MEMBERSHIP_ID,
)
from adobe_vipm.flows.mpt import get_product_items_by_skus
from adobe_vipm.flows.utils import (
    get_adobe_membership_id,
    get_order_line_by_sku,
    get_ordering_parameter,
    get_transfer_item_sku_by_subscription,
    is_transferring_item_expired,
    set_ordering_parameter_error,
)
from adobe_vipm.utils import get_partial_sku

logger = logging.getLogger(__name__)


def get_prices(order, commitment, adobe_skus):
    """
    Get the purchase prices for the provided SKUs from airtable
    thanking into account if the customer has committed for 3y.

    Args:
        order (dict): The order for which the prices must be retrieved for determining
        the product and the currency.
        commitment (dict): Customer 3YC data if any, None otherwise.
        adobe_skus (list): list of SKUs for which the prices must be retrieved.

    Returns:
        dict: a dictionary with SKU, purchase price items.
    """
    currency = order["agreement"]["listing"]["priceList"]["currency"]
    product_id = order["agreement"]["product"]["id"]
    if (
        commitment
        and commitment["status"] in (STATUS_3YC_COMMITTED, "ACTIVE")
        and date.fromisoformat(commitment["endDate"]) >= date.today()
    ):
        return get_prices_for_3yc_skus(
            product_id,
            currency,
            date.fromisoformat(commitment["startDate"]),
            adobe_skus,
        )
    else:
        return get_prices_for_skus(product_id, currency, adobe_skus)



def add_lines_to_order(mpt_client, order, adobe_object, commitment, quantity_field):
    """
    Add the lines that belongs to the provided Adobe VIP membership to the current order.
    Updates the purchase price of each line according to the customer discount level/benefits.


    Args:
        mpt_client (MPTClient): The client used to consume the MPT API.
        order (dict): The order to validate.
        adobe_object (dict): Either a transfer preview object or a list of subscriptions object.
        commitment (dict): Either the customer 3y commitment data or None if the customer doesn't
        have such benefit.
        quantity_field (str): The name of the field that contains the quantity depending on the
        provided `adobe_object` argument.

    Returns:
        tuple: (True, order) if there is an error adding the lines, (False, order) otherwise.
    """
    returned_skus = [
        get_partial_sku(item["offerId"])
        for item in adobe_object["items"]
        if not is_transferring_item_expired(item)
    ]
    returned_full_skus = [
        item["offerId"]
        for item in adobe_object["items"]
        if not is_transferring_item_expired(item)
    ]

    if not returned_skus:
        param = get_ordering_parameter(order, PARAM_MEMBERSHIP_ID)
        order = set_ordering_parameter_error(
            order,
            PARAM_MEMBERSHIP_ID,
            ERR_ADOBE_MEMBERSHIP_ID_EMPTY.to_dict(),
        )
        return True, order

    prices = get_prices(order, commitment, returned_full_skus)

    items_map = {
        item["externalIds"]["vendor"]: item
        for item in get_product_items_by_skus(
            mpt_client, order["agreement"]["product"]["id"], returned_skus
        )
    }
    valid_adobe_lines = []
    for adobe_line in adobe_object["items"]:
        if is_transferring_item_expired(adobe_line):
            continue
        item = items_map.get(get_partial_sku(adobe_line["offerId"]))
        if not item:
            param = get_ordering_parameter(order, PARAM_MEMBERSHIP_ID)
            order = set_ordering_parameter_error(
                order,
                PARAM_MEMBERSHIP_ID,
                ERR_ADOBE_MEMBERSHIP_ID_ITEM.to_dict(
                    title=param["name"],
                    item_sku=get_partial_sku(adobe_line["offerId"]),
                ),
            )
            return True, order
        current_line = get_order_line_by_sku(
            order, get_partial_sku(adobe_line["offerId"])
        )
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

        valid_adobe_lines.append(adobe_line)

    lines = [
        line
        for line in order["lines"]
        if line["item"]["externalIds"]["vendor"] in returned_skus
    ]
    order["lines"] = lines

    return False, order


def validate_transfer_not_migrated(mpt_client, adobe_client, order):
    """
    Validates a transfer that has not been already migrated by the mass migration tool

    Args:
        mpt_client (MPTClient): The client used to consume the MPT API.
        adobe_client (AdobeClient): The client used to consume the Adobe VIPM API.
        order (dict): The order to validate.

    Returns:
        tuple: (True, order) if there is a validation error, (False, order) otherwise.
    """
    authorization_id = order["authorization"]["id"]
    membership_id = get_adobe_membership_id(order)
    transfer_preview = None

    try:
        transfer_preview = adobe_client.preview_transfer(
            authorization_id,
            membership_id,
        )
    except AdobeAPIError as e:
        param = get_ordering_parameter(order, PARAM_MEMBERSHIP_ID)
        order = set_ordering_parameter_error(
            order,
            PARAM_MEMBERSHIP_ID,
            ERR_ADOBE_MEMBERSHIP_ID.to_dict(title=param["name"], details=str(e)),
        )
        return True, order
    except AdobeHttpError as he:
        err_msg = (
            ERR_ADOBE_MEMBERSHIP_NOT_FOUND
            if he.status_code == 404
            else ERR_ADOBE_UNEXPECTED_ERROR
        )
        param = get_ordering_parameter(order, PARAM_MEMBERSHIP_ID)
        order = set_ordering_parameter_error(
            order,
            PARAM_MEMBERSHIP_ID,
            ERR_ADOBE_MEMBERSHIP_ID.to_dict(title=param["name"], details=err_msg),
        )
        return True, order
    commitment = get_3yc_commitment(transfer_preview)
    return add_lines_to_order(mpt_client, order, transfer_preview, commitment, "quantity")


def validate_transfer(mpt_client, adobe_client, order):
    """
    Validates a transfer order.

    Args:
        mpt_client (MPTClient): The client used to consume the MPT API.
        adobe_client (AdobeClient): The client used to consume the Adobe VIPM API.
        order (dict): The order to validate.

    Returns:
        tuple: (True, order) if there is a validation error, (False, order) otherwise.
    """
    config = get_config()
    authorization_id = order["authorization"]["id"]
    authorization = config.get_authorization(authorization_id)
    membership_id = get_adobe_membership_id(order)
    product_id = order["agreement"]["product"]["id"]

    transfer = get_transfer_by_authorization_membership_or_customer(
        product_id,
        authorization.authorization_id,
        membership_id,
    )

    if not transfer:
        return validate_transfer_not_migrated(mpt_client, adobe_client, order)

    if transfer.status == STATUS_RUNNING:
        param = get_ordering_parameter(order, PARAM_MEMBERSHIP_ID)
        order = set_ordering_parameter_error(
            order,
            PARAM_MEMBERSHIP_ID,
            ERR_ADOBE_MEMBERSHIP_ID.to_dict(
                title=param["name"], details="Migration in progress, retry later"
            ),
        )
        return True, order

    if transfer.status == STATUS_SYNCHRONIZED:
        param = get_ordering_parameter(order, PARAM_MEMBERSHIP_ID)
        order = set_ordering_parameter_error(
            order,
            PARAM_MEMBERSHIP_ID,
            ERR_ADOBE_MEMBERSHIP_ID.to_dict(
                title=param["name"], details="Membership has already been migrated"
            ),
        )
        return True, order

    subscriptions = adobe_client.get_subscriptions(
        authorization_id,
        transfer.customer_id,
    )
    adobe_transfer = adobe_client.get_transfer(
        authorization_id,
        transfer.membership_id,
        transfer.transfer_id,
    )

    if adobe_transfer["status"] == STATUS_TRANSFER_INACTIVE_ACCOUNT:
        param = get_ordering_parameter(order, PARAM_MEMBERSHIP_ID)
        order = set_ordering_parameter_error(
            order,
            PARAM_MEMBERSHIP_ID,
            ERR_ADOBE_MEMBERSHIP_ID_INACTIVE_ACCOUNT.to_dict(
                status=adobe_transfer["status"],
            ),
        )
        return True, order

    for subscription in subscriptions["items"]:
        correct_sku = get_transfer_item_sku_by_subscription(
            adobe_transfer, subscription["subscriptionId"]
        )
        subscription["offerId"] = correct_sku or subscription["offerId"]
    customer = adobe_client.get_customer(authorization_id, transfer.customer_id)
    commitment = get_3yc_commitment(customer)
    return add_lines_to_order(mpt_client, order, subscriptions, commitment, "currentQuantity")
