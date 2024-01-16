import json
import os
from typing import Annotated
from urllib.parse import unquote

from fastapi import APIRouter, Body, Request

from devmock.filters import OrdersFilter
from devmock.models import Order, Subscription
from devmock.settings import ORDERS_FOLDER
from devmock.utils import (
    generate_random_id,
    get_buyer_or_404,
    get_order_or_404,
    get_seller_or_404,
    get_subscription_or_404,
    save_order,
    save_subscription,
)

router = APIRouter()


@router.get("/commerce/orders")
def list_orders(request: Request):
    orders = []
    response = {
        "data": [],
    }
    order_files = os.listdir(ORDERS_FOLDER)

    for order_file in order_files:
        with open(os.path.join(ORDERS_FOLDER, order_file), "r") as f:
            orders.append(json.load(f))
    query = unquote(request.scope.get("query_string", b"").decode())
    filter_instance = OrdersFilter()
    filtered_orders, count, limit, offset = filter_instance.apply(query, orders)
    response["data"] = filtered_orders
    response["$meta"] = {
        "pagination": {"offset": offset, "limit": limit, "total": count}
    }
    return response


@router.get("/commerce/orders/{id}")
def get_order(id: str):
    return get_order_or_404(id)


@router.put("/commerce/orders/{id}")
def update_order(
    id: str,
    order: Order,
):
    current_order = get_order_or_404(id)
    if order.parameters:
        current_order["parameters"] = order.parameters
    if order.external_ids:
        current_order["externalIDs"] = (
            current_order.get("externalIDs", {}) | order.external_ids
        )
    save_order(current_order)
    return current_order


@router.post("/commerce/orders/{id}/complete")
def complete_order(id: str, template: Annotated[dict, Body()]):
    order = get_order_or_404(id)
    order["template"] = template["template"]
    order["status"] = "Completed"
    save_order(order)
    return order


@router.post("/commerce/orders/{id}/fail")
def fail_order(id: str, reason: Annotated[str, Body()]):
    order = get_order_or_404(id)
    order["reason"] = reason
    order["status"] = "Failed"
    save_order(order)
    return order


@router.post("/commerce/orders/{id}/query")
def inquire_order(
    id: str,
    template: Annotated[dict, Body()],
    parameters: Annotated[dict, Body()],
):
    order = get_order_or_404(id)
    order["parameters"] = parameters
    order["template"] = template
    order["status"] = "Querying"
    save_order(order)
    return order


@router.post(
    "/commerce/orders/{id}/subscriptions",
    status_code=201,
)
def create_subscription(
    id: str,
    subscription: Subscription,
):
    order = get_order_or_404(id)
    order_items = {item["lineNumber"]: item for item in order["items"]}
    subscription = {
        "id": generate_random_id("SUB", 12, 4),
        "name": subscription.name,
        "parameters": subscription.parameters,
        "items": [order_items[item["lineNumber"]] for item in subscription.items],
        "startDate": subscription.start_date,
    }
    order["subscriptions"].append(subscription)
    save_subscription(subscription)
    save_order(order)
    return subscription


@router.get("/accounts/buyers/{id}")
def get_buyer(id: str):
    return get_buyer_or_404(id)


@router.get("/accounts/sellers/{id}")
def get_seller(id: str):
    return get_seller_or_404(id)


@router.put(
    "/commerce/orders/{order_id}/subscriptions/{id}",
)
def update_subscription(
    order_id: str,
    id: str,
    payload: Subscription,
):
    order = get_order_or_404(order_id)
    subscription = get_subscription_or_404(id)

    order_subscription = next(
        filter(
            lambda x: x["id"] == id,
            order["subscriptions"],
        ),
        None,
    )

    for item in payload.items:
        sub_item = next(
            filter(
                lambda x: x["lineNumber"] == item["lineNumber"],
                subscription["items"],
            ),
            None,
        )
        order_sub_item = next(
            filter(
                lambda x: x["lineNumber"] == item["lineNumber"],
                order_subscription["items"],
            ),
            None,
        )
        if sub_item:
            sub_item["quantity"] = item["quantity"]
            order_sub_item["quantity"] = item["quantity"]

    save_subscription(subscription)
    save_order(order)
    return subscription
