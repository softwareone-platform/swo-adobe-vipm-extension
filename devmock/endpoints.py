import glob
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
    get_item_for_subscription,
    get_reference,
    load_agreement,
    load_buyer,
    load_order,
    load_seller,
    load_subscription,
    save_agreement,
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
    order_files = glob.glob(os.path.join(ORDERS_FOLDER, "*.json"))

    for order_file in order_files:
        with open(os.path.join(ORDERS_FOLDER, order_file), "r") as f:
            orders.append(json.load(f))
    query = unquote(request.scope.get("query_string", b"").decode())
    filter_instance = OrdersFilter()
    filtered_orders, count, limit, offset = filter_instance.apply(query, orders)
    response["data"] = filtered_orders
    response["$meta"] = {"pagination": {"offset": offset, "limit": limit, "total": count}}
    return response


@router.get("/commerce/orders/{id}")
def get_order(id: str):
    return load_order(id)


@router.put("/commerce/orders/{id}")
def update_order(
    id: str,
    order: Order,
):
    current_order = load_order(id)
    if order.parameters:
        current_order["parameters"] = order.parameters
    if order.external_ids:
        current_order["externalIDs"] = current_order.get("externalIDs", {}) | order.external_ids
    save_order(current_order)
    return current_order


@router.post("/commerce/orders/{id}/complete")
def complete_order(id: str, order: Order):
    current_order = load_order(id)
    agreement = load_agreement(current_order["agreement"]["id"])
    agreement["parameters"] = current_order["parameters"]
    current_order["template"] = order.template
    current_order["status"] = "Completed"

    subscriptions = {}

    for subscription in current_order["subscriptions"]:
        full_sub = load_subscription(subscription["id"])
        subscriptions[full_sub["items"][0]["lineNumber"]] = full_sub

    if current_order["type"] == "Change":
        for item in current_order["items"]:
            full_sub = subscriptions[item["lineNumber"]]
            full_sub["items"][0]["quantity"] = item["quantity"]
            save_subscription(full_sub)

    if current_order["type"] == "Termination":
        agreement["status"] = "Terminated"
    else:
        agreement["status"] = "Active"
    save_agreement(agreement)
    save_order(current_order)
    return current_order


@router.post("/commerce/orders/{id}/fail")
def fail_order(id: str, order: Order):
    current_order = load_order(id)
    current_order["reason"] = order.reason
    current_order["status"] = "Failed"
    save_order(current_order)
    agreement = load_agreement(current_order["agreement"]["id"])
    agreement["status"] = "Active"
    save_agreement(agreement)
    return current_order


@router.post("/commerce/orders/{id}/query")
def inquire_order(
    id: str,
    template: Annotated[dict, Body()],
    parameters: Annotated[dict, Body()],
):
    order = load_order(id)
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
    order = load_order(id)
    agreement = load_agreement(order["agreement"]["id"])
    if "subscriptions" not in agreement:
        agreement["subscriptions"] = []
    order_items = {item["lineNumber"]: item for item in order["items"]}
    subscription = {
        "id": generate_random_id("SUB", 16, 4),
        "name": subscription.name,
        "parameters": subscription.parameters,
        "items": [
            get_item_for_subscription(order_items[item["lineNumber"]])
            for item in subscription.items
        ],
        "startDate": subscription.start_date,
    }
    order["subscriptions"].append(get_reference(subscription))
    agreement["subscriptions"].append(get_reference(subscription))

    save_subscription(subscription)
    save_agreement(agreement)
    save_order(order)
    return subscription


@router.get("/accounts/buyers/{id}")
def get_buyer(id: str):
    return load_buyer(id)


@router.get("/accounts/sellers/{id}")
def get_seller(id: str):
    return load_seller(id)


@router.get("/commerce/agreements/{id}")
def get_agreement(id: str):
    return load_agreement(id)


@router.get("/commerce/orders/{order_id}/subscriptions")
def list_subscriptions(order_id: str, limit: int, offset: int):
    subscriptions = []
    response = {
        "data": [],
    }
    order = load_order(order_id)

    for subscription in order["subscriptions"]:
        subscriptions.append(load_subscription(subscription["id"]))

    response["data"] = subscriptions[offset : limit + offset]
    response["$meta"] = {
        "pagination": {"offset": offset, "limit": limit, "total": len(subscriptions)}
    }
    return response
