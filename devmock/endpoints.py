import json
import os
from typing import Annotated
from urllib.parse import unquote

from fastapi import APIRouter, Body, Request

from devmock.filters import OrdersFilter
from devmock.settings import ORDERS_FOLDER
from devmock.utils import (
    generate_random_id,
    get_buyer_or_404,
    get_order_or_404,
    get_seller_or_404,
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
    parameters: Annotated[dict, Body()],
):
    order = get_order_or_404(id)
    order["parameters"] = parameters["parameters"]
    save_order(order)
    return order


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
    name: Annotated[str, Body()],
    parameters: Annotated[dict, Body()],
    items: Annotated[list, Body()],
    startDate: Annotated[str, Body()],
):
    order = get_order_or_404(id)
    order_items = {item["lineNumber"]: item for item in order["items"]}
    subscription = {
        "id": generate_random_id("SUB", 12, 4),
        "name": name,
        "parameters": parameters,
        "items": [order_items[item["lineNumber"]] for item in items],
        "startDate": startDate,
    }
    order["subscriptions"].append(subscription)
    save_subscription(subscription)
    save_order(order)
    return subscription


@router.get("/buyers/{id}")
def get_buyer(id: str):
    return get_buyer_or_404(id)


@router.get("/sellers/{id}")
def get_seller(id: str):
    return get_seller_or_404(id)
