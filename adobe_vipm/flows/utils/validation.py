from adobe_vipm.flows.constants import (
    PARAM_AGREEMENT_TYPE,
    PARAM_MEMBERSHIP_ID,
    REQUIRED_CUSTOMER_ORDER_PARAMS,
)
from adobe_vipm.flows.utils.parameter import (
    get_ordering_parameter,
    is_ordering_param_required,
)
from adobe_vipm.flows.utils.subscription import (
    is_line_item_active_subscription,
)


def validate_subscription_and_returnable_orders(
    adobe_client,
    context,
    line,
    sku,
    return_orders=None
):
    """
    Validates if the subscription is active and has valid returnable orders.
    Returnable orders are the orders that has been created in a period
    of 2 weeks before the current date.

    Args:
        adobe_client: The Adobe client instance
        context: The context object
        line: The order line to validate
        sku: The SKU to validate
        return_orders: Optional return orders to pass to get_returnable_orders_by_sku

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

    returnable_orders = adobe_client.get_returnable_orders_by_sku(
        context.authorization_id,
        context.adobe_customer_id,
        sku,
        context.adobe_customer["cotermDate"],
        return_orders=return_orders,
    )

    if not returnable_orders:
        return False, []

    if not has_valid_returnable_quantity(line, returnable_orders):
        return False, []

    return True, returnable_orders

def has_valid_returnable_quantity(line, returnable_orders):
    delta = line["oldQuantity"] - line["quantity"]
    total_quantity_returnable = sum(roi.quantity for roi in returnable_orders)
    return delta == total_quantity_returnable


def is_purchase_validation_enabled(order):
    return all(
        is_ordering_param_required(order, param_external_id)
        for param_external_id in REQUIRED_CUSTOMER_ORDER_PARAMS
    )

def is_migrate_customer(order):
    agreement_type = get_ordering_parameter(order, PARAM_AGREEMENT_TYPE).get("value")
    return agreement_type == "Migrate" and is_ordering_param_required(order, PARAM_MEMBERSHIP_ID)
