import logging

from adobe_vipm.flows.fulfillment.change import fulfill_change_order
from adobe_vipm.flows.fulfillment.purchase import fulfill_purchase_order
from adobe_vipm.flows.fulfillment.termination import fulfill_termination_order
from adobe_vipm.flows.fulfillment.transfer import fulfill_transfer_order
from adobe_vipm.flows.helpers import populate_order_info
from adobe_vipm.flows.utils import (
    is_change_order,
    is_purchase_order,
    is_termination_order,
    is_transfer_order,
)

logger = logging.getLogger(__name__)


def fulfill_order(client, order):
    """
    Fulfills an order of any type by processing the necessary actions
    based on the provided parameters.

    Args:
        client (MPTClient): An instance of the client for consuming the MPT platform API.
        order (dict): The order that needs to be processed.

    Returns:
        None
    """
    logger.info(f'Start processing {order["type"]} order {order["id"]}')
    order = populate_order_info(client, order)
    seller_country = order["agreement"]["seller"]["address"]["country"]
    if is_purchase_order(order):
        fulfill_purchase_order(client, seller_country, order)
    elif is_transfer_order(order):
        fulfill_transfer_order(client, seller_country, order)
    elif is_change_order(order):
        fulfill_change_order(client, seller_country, order)
    elif is_termination_order(order):  # pragma: no branch
        fulfill_termination_order(client, seller_country, order)
