import copy


def find_first(func, iterable, default=None):
    return next(filter(func, iterable), default)


def get_parameter(order, parameter_phase, parameter_name):
    return find_first(
        lambda x: x["name"] == parameter_name,
        order["parameters"][parameter_phase],
        default={},
    )


def is_purchase_order(order):
    return order["type"] == "Purchase" and not get_parameter(
        order,
        "fulfillment",
        "MembershipId",
    ).get("value")


def get_adobe_customer_id(source):
    return get_parameter(
        source,
        "fulfillment",
        "CustomerId",
    ).get("value")


def set_adobe_customer_id(order, customer_id):
    """
    Create a copy of the order. Set the CustomerId
    fulfillment parameter on the copy of the original order.
    Return the copy of the original order with the
    CustomerId parameter filled.
    """
    updated_order = copy.deepcopy(order)
    customer_ff_param = get_parameter(
        updated_order,
        "fulfillment",
        "CustomerId",
    )
    customer_ff_param["value"] = customer_id
    return updated_order


def get_adobe_order_id(order):
    return order.get("externalIDs", {}).get("vendor")


def set_adobe_order_id(order, adobe_order_id):
    updated_order = copy.deepcopy(order)
    updated_order["externalIDs"] = updated_order.get("externalIDs", {}) | {
        "vendor": adobe_order_id
    }
    return updated_order


def get_customer_data(order):
    customer_data = {}
    for param_name in (
        "CompanyName",
        "PreferredLanguage",
        "Address",
        "Contact",
    ):
        customer_data[param_name] = get_parameter(
            order,
            "order",
            param_name,
        ).get("value")

    return customer_data


def set_customer_data(order, customer_data):
    updated_order = copy.deepcopy(order)
    for param_name, value in customer_data.items():
        get_parameter(
            updated_order,
            "order",
            param_name,
        )["value"] = value
    return updated_order


def set_ordering_parameter_error(order, param_name, error):
    updated_order = copy.deepcopy(order)
    get_parameter(
        updated_order,
        "order",
        param_name,
    )["error"] = error
    return updated_order


def get_order_item(order, sku):
    return find_first(
        lambda item: sku.startswith(item["productItemId"]),
        order["items"],
    )


def increment_retry_count(order):
    updated_order = copy.deepcopy(order)
    param = get_parameter(
        updated_order,
        "fulfillment",
        "RetryCount",
    )
    param["value"] = str(int(param["value"]) + 1) if param["value"] else "1"
    return updated_order


def reset_retry_count(order):
    updated_order = copy.deepcopy(order)
    param = get_parameter(
        updated_order,
        "fulfillment",
        "RetryCount",
    )
    param["value"] = "0"
    return updated_order


def get_retry_count(order):
    return int(
        get_parameter(
            order,
            "fulfillment",
            "RetryCount",
        ).get("value", "0")
        or "0",
    )


def is_upsizing_order(order):
    return order["type"] == "Change" and all(
        list(map(lambda item: item["quantity"] > item["oldQuantity"], order["items"]))
    )


def get_order_subscription(order, line_number, product_item_id):
    for subscription in order["subscriptions"]:
        item = find_first(
            lambda x: x["lineNumber"] == line_number
            and x["productItemId"] == product_item_id,
            subscription["items"],
        )

        if item:
            return subscription


def update_subscription_item(subscription, line_number, product_item_id, quantity):
    upd_subscription = copy.deepcopy(subscription)
    item = find_first(
        lambda x: x["lineNumber"] == line_number
        and x["productItemId"] == product_item_id,
        upd_subscription["items"],
    )
    item["quantity"] = quantity
    return upd_subscription
