import glob
import json
import os
from typing import Annotated, Any
from urllib.parse import unquote

import requests
from fastapi import APIRouter, Body, Request
from fastapi.responses import JSONResponse

from devmock.filters import ItemsFilter, OrdersFilter
from devmock.models import Order, Subscription
from devmock.settings import ITEMS_FOLDER, ORDERS_FOLDER, WEBHOOK_ENDPOINT
from devmock.utils import (
    base_id_from,
    gen_jwt_token,
    generate_random_id,
    get_line_for_subscription,
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
            order = json.load(f)
            agreement = load_agreement(order["agreement"]["id"])
            order["agreement"] = agreement
            subscriptions = [
                load_subscription(subscription["id"]) for subscription in order["subscriptions"]
            ]
            order["subscriptions"] = subscriptions
            orders.append(order)

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
        current_order["externalIds"] = current_order.get("externalIds", {}) | order.external_ids
    save_order(current_order)
    return current_order


@router.post("/commerce/orders/{id}/complete")
def complete_order(id: str, order: Order):
    current_order = load_order(id)
    agreement = load_agreement(current_order["agreement"]["id"])
    agreement["parameters"] = current_order["parameters"]
    current_order["template"] = order.template
    current_order["status"] = "completed"

    subscriptions = {}

    for subscription in agreement["subscriptions"]:
        full_sub = load_subscription(subscription["id"])
        subscriptions[full_sub["lines"][0]["id"]] = full_sub

    if current_order["type"] == "change":
        for line in current_order["lines"]:
            full_sub = subscriptions[line["id"]]
            full_sub["lines"][0]["quantity"] = line["quantity"]
            full_sub["status"] = "active"
            save_subscription(full_sub)
        agreement["status"] = "active"
    elif current_order["type"] == "termination":
        for line in current_order["lines"]:
            full_sub = subscriptions[line["id"]]
            full_sub["lines"][0]["quantity"] = line["quantity"]
            full_sub["status"] = "terminated"
            save_subscription(full_sub)
        if all(map(lambda x: x["status"] == "terminated", subscriptions.values())):
            agreement["status"] = "terminated"
        else:
            agreement["status"] = "active"
    else:
        agreement["status"] = "active"

    save_agreement(agreement)
    save_order(current_order)
    return current_order


@router.post("/commerce/orders/{id}/fail")
def fail_order(id: str, order: Order):
    current_order = load_order(id)
    current_order["reason"] = order.reason
    current_order["status"] = "failed"
    save_order(current_order)
    agreement = load_agreement(current_order["agreement"]["id"])
    agreement["status"] = "active"
    save_agreement(agreement)
    return current_order


@router.post("/commerce/orders/{id}/query")
def inquire_order(
    id: str,
    templateId: Annotated[str, Body()],
    parameters: Annotated[dict, Body()],
):
    order = load_order(id)
    order["parameters"] = parameters
    order["templateId"] = templateId
    order["status"] = "querying"
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
    order_lines = {line["id"]: line for line in order["lines"]}
    subscription = {
        "id": generate_random_id("SUB", 16, 4),
        "name": subscription.name,
        "parameters": subscription.parameters,
        "lines": [
            get_line_for_subscription(order_lines[line["id"]]) for line in subscription.lines
        ],
        "startDate": subscription.start_date,
        "status": "active",
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


@router.post("/commerce/orders/{order_id}/validate")
def validate_draft_order(order_id: str, order: Order):
    current_order = load_order(order_id)
    agreement = get_agreement(current_order["agreement"]["id"])
    if order.parameters:
        current_order["parameters"] = order.parameters
        save_order(current_order)
    resp = requests.post(
        WEBHOOK_ENDPOINT,
        headers={
            "authorization": f"Bearer {gen_jwt_token()}",
        },
        json=current_order,
    )
    if resp.status_code == 200:
        validated_order = resp.json()
        current_order["parameters"] = validated_order["parameters"]
        current_order["lines"] = []
        for idx, line in enumerate(validated_order["lines"], start=1):
            line["id"] = f"ALI-{base_id_from(agreement['id'])}-{idx:04d}"
            current_order["lines"].append(line)
        save_order(current_order, order_id)
        return JSONResponse(current_order)
    return JSONResponse(
        resp.json() if resp.headers["content-type"] == "application/json" else resp.text,
        status_code=resp.status_code,
    )


@router.get("/product-items")
def list_product_items(request: Request):
    items = []
    response = {
        "data": [],
    }
    items_files = glob.glob(os.path.join(ITEMS_FOLDER, "*.json"))

    for item_file in items_files:
        with open(os.path.join(ITEMS_FOLDER, item_file), "r") as f:
            item = json.load(f)
            items.append(item)

    query = unquote(request.scope.get("query_string", b"").decode())
    filter_instance = ItemsFilter()
    filtered_items, count, limit, offset = filter_instance.apply(query, items)
    response["data"] = filtered_items
    response["$meta"] = {"pagination": {"offset": offset, "limit": limit, "total": count}}
    return response
