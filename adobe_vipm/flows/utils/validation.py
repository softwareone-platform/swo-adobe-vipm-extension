from adobe_vipm.flows.constants import (
    PARAM_REQUIRED_CUSTOMER_ORDER,
    Param,
)
from adobe_vipm.flows.utils.parameter import get_ordering_parameter, is_ordering_param_required
from adobe_vipm.flows.utils.subscription import is_line_item_active_subscription


def validate_subscription_and_returnable_orders(
    adobe_client, context, line, subscription_id, return_orders=None
):
    """
    Validates if the subscription is active and has valid returnable orders.

    Returnable orders are the orders that has been created in a period
    of 2 weeks before the current date.

    Args:
        adobe_client (MPTClient): The Adobe client instance
        context (Context): The context object
        line (dict): The order line to validate
        sku (str): The SKU to validate
        return_orders (list[dict] | None): Optional return orders to pass to
        get_returnable_orders_by_sku

    Returns:
        tuple: (is_valid, returnable_orders)
        - is_valid: True if validation passed, False otherwise
        - returnable_orders: List of returnable orders if validation passed, None otherwise
    """
    subscriptions = adobe_client.get_subscriptions(
        context.authorization_id,
        context.adobe_customer_id,
    )

    if not is_line_item_active_subscription(subscriptions, line):
        return True, []

    returnable_orders = adobe_client.get_returnable_orders_by_subscription_id(
        context.authorization_id,
        context.adobe_customer_id,
        subscription_id,
        context.adobe_customer["cotermDate"],
        return_orders=return_orders,
    )

    if not returnable_orders:
        return False, []

    if not _has_valid_returnable_quantity(line, returnable_orders):
        return False, []

    return True, returnable_orders


def _has_valid_returnable_quantity(line, returnable_orders):
    delta = line["oldQuantity"] - line["quantity"]
    total_quantity_returnable = sum(roi.quantity for roi in returnable_orders)
    return delta == total_quantity_returnable


# TODO: rename it? doesn't make sense the naming, since it check that parameters are marked as
# required
def is_purchase_validation_enabled(order: dict) -> bool:
    """
    Checks if customer parameters are marked as required.

    Args:
        order: MPT Order

    Returns:
        if all customer parameters marked as required
    """
    return all(
        is_ordering_param_required(order, param_external_id)
        for param_external_id in PARAM_REQUIRED_CUSTOMER_ORDER
    )


def is_migrate_customer(order: dict) -> bool:
    """
    Checks if order is a VIP -> VIPM migration order.

    Args:
        order: MPT order

    Returns:
        if parameter of Agreement Type is marked as 'Migrate'
    """
    agreement_type = get_ordering_parameter(order, Param.AGREEMENT_TYPE).get("value")
    return agreement_type == "Migrate" and is_ordering_param_required(order, Param.MEMBERSHIP_ID)


def is_reseller_change(order: dict) -> bool:
    """
    Checks if order is a transfer order from another distributor.

    Args:
        order: MPT order

    Returns:
        if parameter of Agreement Type is marked as 'Transfer'
    """
    agreement_type = get_ordering_parameter(order, Param.AGREEMENT_TYPE).get("value")
    return agreement_type == "Transfer" and is_ordering_param_required(
        order, Param.CHANGE_RESELLER_CODE
    )
