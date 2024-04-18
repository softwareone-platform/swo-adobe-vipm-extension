import logging

from adobe_vipm.adobe.config import get_config
from adobe_vipm.adobe.errors import AdobeAPIError
from adobe_vipm.flows.airtable import (
    STATUS_RUNNING,
    get_transfer_by_authorization_membership,
)
from adobe_vipm.flows.constants import (
    ERR_ADOBE_MEMBERSHIP_ID,
    ERR_ADOBE_MEMBERSHIP_ID_ITEM,
    PARAM_MEMBERSHIP_ID,
)
from adobe_vipm.flows.mpt import get_product_items_by_skus
from adobe_vipm.flows.utils import (
    get_adobe_membership_id,
    get_ordering_parameter,
    set_ordering_parameter_error,
)

logger = logging.getLogger(__name__)


def add_lines_to_order(mpt_client, order, adobe_object, quantity_field):
    returned_skus = [item["offerId"][:10] for item in adobe_object["items"]]

    items_map = {
        item["externalIds"]["vendor"]: item
        for item in get_product_items_by_skus(
            mpt_client, order["agreement"]["product"]["id"], returned_skus
        )
    }
    lines = []
    for adobe_line in adobe_object["items"]:
        item = items_map.get(adobe_line["offerId"][:10])
        if not item:
            param = get_ordering_parameter(order, PARAM_MEMBERSHIP_ID)
            order = set_ordering_parameter_error(
                order,
                PARAM_MEMBERSHIP_ID,
                ERR_ADOBE_MEMBERSHIP_ID_ITEM.to_dict(
                    title=param["name"],
                    item_sku=adobe_line["offerId"][:10],
                ),
            )
            return True, order
        lines.append(
            {
                "item": item,
                "quantity": adobe_line[quantity_field],
                "oldQuantity": 0,
            },
        )
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

    return add_lines_to_order(mpt_client, order, transfer_preview, "quantity")


def validate_transfer(mpt_client, adobe_client, order):
    config = get_config()
    authorization_id = order["authorization"]["id"]
    authorization = config.get_authorization(authorization_id)
    membership_id = get_adobe_membership_id(order)
    product_id = order["agreement"]["product"]["id"]

    transfer = get_transfer_by_authorization_membership(
        product_id,
        authorization.authorization_uk,
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
                title=param["name"], details="Migration in progress, retry later."
            ),
        )
        return True, order

    subscriptions = adobe_client.get_subscriptions(
        authorization_id,
        transfer.customer_id,
    )

    return add_lines_to_order(mpt_client, order, subscriptions, "currentQuantity")
