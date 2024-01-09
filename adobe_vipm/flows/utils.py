import copy


def get_parameter(order, parameter_type, parameter_name):
    return next(
        filter(
            lambda x: x["name"] == parameter_name,
            order["parameters"][parameter_type],
        ),
        {},
    )


def is_purchase_order(order):
    return order["type"] == "Purchase" and not get_parameter(
        order,
        "fulfillment",
        "MembershipId",
    ).get("value")


def get_adobe_customer_id(order):
    return get_parameter(
        order,
        "fulfillment",
        "CustomerId",
    ).get("value")


def set_adobe_customer_id(order, customer_id):
    updated_order = copy.deepcopy(order)
    get_parameter(
        updated_order,
        "fulfillment",
        "CustomerId",
    )["value"] = customer_id
    return updated_order


def get_adobe_order_id(order):
    return get_parameter(
        order,
        "fulfillment",
        "OrderId",
    ).get("value")


def set_adobe_order_id(order, adobe_order_id):
    updated_order = copy.deepcopy(order)
    get_parameter(
        updated_order,
        "fulfillment",
        "OrderId",
    )["value"] = adobe_order_id
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
    return next(
        filter(
            lambda item: sku.startswith(item["productItemId"]),
            order["items"],
        ),
        None,
    )
