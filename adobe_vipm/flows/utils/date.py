import copy
import datetime as dt
from zoneinfo import ZoneInfo

from django.conf import settings

from adobe_vipm.flows.constants import LAST_TWO_WEEKS_DAYS, Param
from adobe_vipm.flows.utils.parameter import (
    get_coterm_date,
    get_fulfillment_parameter,
)


def set_due_date(order: dict) -> dict:
    """
    Sets DUE_DATE parameter to the value of today() + EXT_DUE_DATE_DAYS if it is not set yet.

    Args:
        order (dict): The order that contains the due date fulfillment
        parameter.

    Returns:
        dict: Updated MPT order.
    """
    updated_order = copy.deepcopy(order)
    param = get_fulfillment_parameter(
        updated_order,
        Param.DUE_DATE,
    )
    if not param:
        # in case of there is no any due date parameter
        # when order was in processing status
        # and due date was created and rolled out to the environment
        param = {
            "externalId": Param.DUE_DATE,
        }
        updated_order["parameters"][Param.PHASE_FULFILLMENT].append(param)

    if not param.get("value"):
        now = dt.datetime.now(tz=dt.UTC).date()
        due_date = now + dt.timedelta(days=int(settings.EXTENSION_CONFIG.get("DUE_DATE_DAYS")))
        param["value"] = due_date.strftime("%Y-%m-%d")

    return updated_order


def get_due_date(order: dict) -> dt.date | None:
    """
    Gets DUE_DATE parameter.

    Args:
        order: The order that contains the due date fulfillment parameter.

    Returns:
        Due date or None.
    """
    param = get_fulfillment_parameter(
        order,
        Param.DUE_DATE,
    )

    if param.get("value"):
        return dt.datetime.strptime(param["value"], "%Y-%m-%d").replace(tzinfo=dt.UTC).date()

    return None


def reset_due_date(order: dict) -> dict:
    """
    Reset the due date fulfillment parameter to None.

    It is needed to have due date empty on next order published.

    Args:
        order: The order that contains the due date fulfillment parameter.

    Returns:
        Updated MPT order.
    """
    param = get_fulfillment_parameter(
        order,
        Param.DUE_DATE,
    )
    param["value"] = None

    return order


def is_within_last_two_weeks(coterm_date: str) -> bool:
    """
    Checks if date is within two weeks from now.

    Args:
        coterm_date: Date to check.

    Returns:
        True if provided date is within two weeks from now.
    """
    last_two_weeks = (
        dt.datetime.fromisoformat(coterm_date) - dt.timedelta(days=LAST_TWO_WEEKS_DAYS)
    ).date()

    return dt.datetime.now(tz=dt.UTC).date() >= last_two_weeks


def is_coterm_date_within_order_creation_window(order: dict) -> bool:
    """
    Checks if coterm date is within the order creation window.

    Args:
        order: MPT order.

    Returns:
        True if order's coterm date is withing ORDER_CREATION_WINDOW_HOURS from now.
    """
    if not get_coterm_date(order):
        return False

    hours = settings.EXTENSION_CONFIG.get("ORDER_CREATION_WINDOW_HOURS")
    coterm_date = dt.datetime.fromisoformat(get_coterm_date(order)).date()
    # The zone is set to Pacific time to match the Adobe order creation window
    # this is for the business logic to be consistent with the Adobe order creation window
    pacific_tz = ZoneInfo("America/Los_Angeles")
    today = dt.datetime.now(pacific_tz).date()
    return today >= coterm_date - dt.timedelta(hours=int(hours))
