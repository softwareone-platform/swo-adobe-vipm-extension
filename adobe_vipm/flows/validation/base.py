import logging

from adobe_vipm.adobe.client import get_adobe_client
from adobe_vipm.flows.helpers import (
    populate_order_info,
    prepare_customer_data,
    update_purchase_prices,
)
from adobe_vipm.flows.utils import (
    is_purchase_order,
    is_transfer_order,
)
from adobe_vipm.flows.validation.purchase import validate_customer_data
from adobe_vipm.flows.validation.transfer import validate_transfer

logger = logging.getLogger(__name__)


def validate_order(mpt_client, order):
    adobe_client = get_adobe_client()
    order = populate_order_info(mpt_client, order)
    has_errors = False
    if is_purchase_order(order):
        order, customer_data = prepare_customer_data(mpt_client, order)
        has_errors, order = validate_customer_data(order, customer_data)
    elif is_transfer_order(order):  # pragma: no branch
        has_errors, order = validate_transfer(mpt_client, adobe_client, order)
    if not has_errors:
        order = update_purchase_prices(mpt_client, adobe_client, order)
    logger.info(
        f"Validation of order {order['id']} succeeded with{'out' if not has_errors else ''} errors"
    )
    return order
