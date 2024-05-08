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
def get_licensee(mpt_client, licensee_id):
    response = mpt_client.get(f"/accounts/licensees/{licensee_id}")
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
def complete_order(mpt_client, order_id, template):
    response = mpt_client.post(
        f"/commerce/orders/{order_id}/complete",
        json={"template": template},
    )
    response.raise_for_status()
    return response.json()


@wrap_http_error
def set_processing_template(mpt_client, order_id, template):
    response = mpt_client.put(
        f"/commerce/orders/{order_id}",
        json={"template": template},
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
def get_subscription_by_external_id(mpt_client, order_id, subscription_external_id):
    response = mpt_client.get(
        f"/commerce/orders/{order_id}/subscriptions?eq(externalIds.vendor,{subscription_external_id})&limit=1",
    )
    response.raise_for_status()
    subscriptions = response.json()
    if subscriptions["$meta"]["pagination"]["total"] == 1:
        return subscriptions["data"][0]


@wrap_http_error
def get_product_items_by_skus(mpt_client, product_id, skus):
    items = []
    rql_query = (
        f"and(eq(product.id,{product_id}),in(externalIds.vendor,({','.join(skus)})))"
    )
    url = f"/items?{rql_query}"
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
    url = f"/price-lists/{pricelist_id}/items?{rql_query}"
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
    response = mpt_client.get(f"/notifications/webhooks/{webhook_id}?select=criteria")
    response.raise_for_status()

    return response.json()


@wrap_http_error
def get_product_template_or_default(mpt_client, product_id, status, name=None):
    name_or_default_filter = "eq(default,true)"
    if name:
        name_or_default_filter = f"or({name_or_default_filter},eq(name,{name}))"
    rql_filter = f"and(eq(type,Order{status}),{name_or_default_filter})"
    url = f"/products/{product_id}/templates?{rql_filter}&limit=1"
    response = mpt_client.get(url)
    response.raise_for_status()
    templates = response.json()
    return templates["data"][0]
