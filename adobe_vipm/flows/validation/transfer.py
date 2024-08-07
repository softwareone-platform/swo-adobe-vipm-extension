import logging
from datetime import date

from adobe_vipm.adobe.config import get_config
from adobe_vipm.adobe.constants import STATUS_3YC_COMMITTED
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
    get_partial_sku,
    get_transfer_item_sku_by_subscription,
    is_transferring_item_expired,
    set_ordering_parameter_error,
)

logger = logging.getLogger(__name__)


def get_prices(order, commitment, adobe_skus):
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
            logger.info(f"new line: {new_line}")
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
    for subscription in subscriptions["items"]:
        correct_sku = get_transfer_item_sku_by_subscription(
            adobe_transfer, subscription["subscriptionId"]
        )
        subscription["offerId"] = correct_sku or subscription["offerId"]
    customer = adobe_client.get_customer(authorization_id, transfer.customer_id)
    commitment = get_3yc_commitment(customer)
    return add_lines_to_order(mpt_client, order, subscriptions, commitment, "currentQuantity")
