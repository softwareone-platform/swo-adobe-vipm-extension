import logging

from adobe_vipm.adobe.client import get_adobe_client
from adobe_vipm.flows.constants import (
    PARAM_ADDRESS,
    PARAM_COMPANY_NAME,
    PARAM_CONTACT,
    PARAM_MEMBERSHIP_ID,
    PARAM_PREFERRED_LANGUAGE,
)
from adobe_vipm.flows.helpers import (
    populate_order_info,
    prepare_customer_data,
    update_purchase_prices,
    update_purchase_prices_for_transfer,
)
from adobe_vipm.flows.utils import (
    is_new_customer,
    is_purchase_order,
    is_transfer_order,
    reset_ordering_parameters_error,
    set_parameter_hidden,
    set_parameter_visible,
)
from adobe_vipm.flows.validation.purchase import validate_customer_data
from adobe_vipm.flows.validation.transfer import validate_transfer

NEW_CUSTOMER_PARAMETERS = (
    PARAM_COMPANY_NAME,
    PARAM_PREFERRED_LANGUAGE,
    PARAM_ADDRESS,
    PARAM_CONTACT,
)

logger = logging.getLogger(__name__)


def update_parameters_visibility(order):
    if is_new_customer(order):
        for param in NEW_CUSTOMER_PARAMETERS:
            order = set_parameter_visible(order, param)
        order = set_parameter_hidden(order, PARAM_MEMBERSHIP_ID)
    else:
        for param in NEW_CUSTOMER_PARAMETERS:
            order = set_parameter_hidden(order, param)
        order = set_parameter_visible(order, PARAM_MEMBERSHIP_ID)
    return order


def validate_order(mpt_client, order):
    adobe_client = get_adobe_client()
    order = populate_order_info(mpt_client, order)
    has_errors = False
    order = reset_ordering_parameters_error(order)
    if is_purchase_order(order):
        order, customer_data = prepare_customer_data(mpt_client, order)
        has_errors, order = validate_customer_data(order, customer_data)
        if not has_errors and order["lines"]:
            order = update_purchase_prices(mpt_client, adobe_client, order)
    elif is_transfer_order(order):  # pragma: no branch
        has_errors, order, adobe_object = validate_transfer(
            mpt_client, adobe_client, order
        )
        if not has_errors:
            order = update_purchase_prices_for_transfer(mpt_client, order, adobe_object)

    order = update_parameters_visibility(order)

    if not order["lines"]:  # pragma: no cover
        del order["lines"]

    logger.info(
        f"Validation of order {order['id']} succeeded with{'out' if not has_errors else ''} errors"
    )
    return order
