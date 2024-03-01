import copy
import logging

from adobe_vipm.flows.errors import wrap_http_error

logger = logging.getLogger(__name__)


@wrap_http_error
def get_agreement(mpt_client, agreement_id):
    response = mpt_client.get(f"/commerce/agreements/{agreement_id}?select=seller,buyer")
    response.raise_for_status()
    return response.json()


@wrap_http_error
def get_seller(mpt_client, seller_id):
    response = mpt_client.get(f"/accounts/sellers/{seller_id}")
    response.raise_for_status()
    return response.json()


@wrap_http_error
def get_buyer(mpt_client, buyer_id):
    response = mpt_client.get(f"/accounts/buyers/{buyer_id}")
    response.raise_for_status()
    return response.json()


@wrap_http_error
def update_order(mpt_client, order_id, **kwargs):
    json_body = copy.deepcopy(kwargs)

    response = mpt_client.put(
        f"/commerce/orders/{order_id}",
        json=json_body,
    )
    response.raise_for_status()
    return response.json()


@wrap_http_error
def query_order(mpt_client, order_id, **kwargs):
    response = mpt_client.post(
        f"/commerce/orders/{order_id}/query",
        json=kwargs,
    )
    response.raise_for_status()
    return response.json()


@wrap_http_error
def fail_order(mpt_client, order_id, reason):
    response = mpt_client.post(
        f"/commerce/orders/{order_id}/fail",
        json={"reason": reason},
    )
    response.raise_for_status()
    return response.json()


@wrap_http_error
def complete_order(mpt_client, order_id, template_id):
    response = mpt_client.post(
        f"/commerce/orders/{order_id}/complete",
        json={"template": {"id": template_id}},
    )
    response.raise_for_status()
    return response.json()


@wrap_http_error
def create_subscription(mpt_client, order_id, subscription):
    response = mpt_client.post(
        f"/commerce/orders/{order_id}/subscriptions",
        json=subscription,
    )
    response.raise_for_status()
    return response.json()


@wrap_http_error
def get_product_items(mpt_client, product_id, item_ids):
    item_filter = f"product.id={product_id}&in(id,({','.join(item_ids)}))"

    response = mpt_client.get(f"/product-items?{item_filter}")
    response.raise_for_status()
    data = response.json()

    return data["data"]
