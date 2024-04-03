import logging
from functools import cache

from adobe_vipm.flows.constants import ERR_VIPM_UNHANDLED_EXCEPTION
from adobe_vipm.flows.errors import wrap_http_error

logger = logging.getLogger(__name__)


def _has_more_pages(page):
    if not page:
        return True
    pagination = page["$meta"]["pagination"]
    return pagination["total"] > pagination["limit"] + pagination["offset"]


@wrap_http_error
def get_agreement(mpt_client, agreement_id):
    response = mpt_client.get(
        f"/commerce/agreements/{agreement_id}?select=seller,buyer,listing,product"
    )
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
    response = mpt_client.put(
        f"/commerce/orders/{order_id}",
        json=kwargs,
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
        json={"statusNotes": ERR_VIPM_UNHANDLED_EXCEPTION.to_dict(error=reason)},
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
def update_subscription(mpt_client, order_id, subscription_id, **kwargs):
    response = mpt_client.put(
        f"/commerce/orders/{order_id}/subscriptions/{subscription_id}",
        json=kwargs,
    )
    response.raise_for_status()
    return response.json()


@wrap_http_error
def get_product_items_by_skus(mpt_client, product_id, skus):
    items = []
    rql_query = (
        f"and(eq(product.id,{product_id}),in(externalIds.vendor,({','.join(skus)})))"
    )
    url = f"/product-items?{rql_query}"
    page = None
    limit = 10
    offset = 0
    while _has_more_pages(page):
        response = mpt_client.get(f"{url}&limit={limit}&offset={offset}")
        response.raise_for_status()
        page = response.json()
        items.extend(page["data"])
        offset += limit

    return items


@wrap_http_error
def get_pricelist_items_by_product_items(mpt_client, pricelist_id, product_item_ids):
    items = []
    rql_query = f"in(item.id,({",".join(product_item_ids)}))"
    url = f"/price-lists/{pricelist_id}/price-items?{rql_query}"
    page = None
    limit = 10
    offset = 0
    while _has_more_pages(page):
        response = mpt_client.get(f"{url}&limit={limit}&offset={offset}")
        response.raise_for_status()
        page = response.json()
        items.extend(page["data"])
        offset += limit

    return items


@cache
@wrap_http_error
def get_webhook(mpt_client, webhook_id):
    response = mpt_client.get(f"/notifications/webhooks/{webhook_id}")
    response.raise_for_status()

    return response.json()
