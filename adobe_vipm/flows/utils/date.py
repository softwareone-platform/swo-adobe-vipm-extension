import copy
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from django.conf import settings

from adobe_vipm.flows.constants import (
    LAST_TWO_WEEKS_DAYS,
    PARAM_DUE_DATE,
    PARAM_PHASE_FULFILLMENT,
)
from adobe_vipm.flows.utils.parameter import (
    get_coterm_date,
    get_fulfillment_parameter,
)


def set_due_date(order):
    """
    Sets DUE_DATE parameter to the value of today() + EXT_DUE_DATE_DAYS if it is not set yet
    Args:
        order (dict): The order that contains the due date fulfillment
        parameter.

    Returns:
        dict: The updated order.
    """
    updated_order = copy.deepcopy(order)
    param = get_fulfillment_parameter(
        updated_order,
        PARAM_DUE_DATE,
    )
    if not param:
        # in case of there is no any due date parameter
        # when order was in processing status
        # and due date was created and rolled out to the environment
        param = {
            "externalId": PARAM_DUE_DATE,
        }
        updated_order["parameters"][PARAM_PHASE_FULFILLMENT].append(param)

    if not param.get("value"):
        due_date = date.today() + timedelta(
            days=int(settings.EXTENSION_CONFIG.get("DUE_DATE_DAYS"))
        )
        param["value"] = due_date.strftime("%Y-%m-%d")

    return updated_order

def get_due_date(order):
    """
    Gets DUE_DATE parameter
    Args:
        order (dict): The order that contains the due date fulfillment
        parameter.

    Returns:
        date: due date or None
    """
    param = get_fulfillment_parameter(
        order,
        PARAM_DUE_DATE,
    )

    return (
        datetime.strptime(param["value"], "%Y-%m-%d").date()
        if param.get("value")
        else None
    )

def reset_due_date(order):
    """
    Reset the due date fulfillment parameter to None. It is needed to
    have due date empty on next order published
    Args:
        order (dict): The order that contains the due date fulfillment
        parameter.

    Returns:
        dict: The updated order.
    """
    param = get_fulfillment_parameter(
        order,
        PARAM_DUE_DATE,
    )
    param["value"] = None

    return order

def is_within_last_two_weeks(coterm_date):
    last_two_weeks = (
        datetime.fromisoformat(coterm_date) - timedelta(days=LAST_TWO_WEEKS_DAYS)
    ).date()

    return date.today() >= last_two_weeks

def is_coterm_date_within_order_creation_window(order):
    if not get_coterm_date(order):
        return False
    hours = settings.EXTENSION_CONFIG.get("ORDER_CREATION_WINDOW_HOURS")
    coterm_date = datetime.fromisoformat(get_coterm_date(order)).date()
    #The zone is set to Pacific time to match the Adobe order creation window
    #this is for the business logic to be consistent with the Adobe order creation window
    pacific_tz = ZoneInfo('America/Los_Angeles')
    today = datetime.now(pacific_tz).date()
    return today >= coterm_date - timedelta(hours=int(hours))


