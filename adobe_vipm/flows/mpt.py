import logging
from datetime import date, timedelta
from functools import cache

from adobe_vipm.adobe.constants import (
    STATUS_3YC_ACCEPTED,
    STATUS_3YC_COMMITTED,
    STATUS_3YC_DECLINED,
    STATUS_3YC_EXPIRED,
    STATUS_3YC_NONCOMPLIANT,
    STATUS_3YC_REQUESTED,
)
from adobe_vipm.flows.constants import (
    ERR_VIPM_UNHANDLED_EXCEPTION,
    PARAM_3YC,
    PARAM_3YC_COMMITMENT_REQUEST_STATUS,
    PARAM_3YC_END_DATE,
    PARAM_3YC_ENROLL_STATUS,
    PARAM_3YC_RECOMMITMENT,
    PARAM_3YC_RECOMMITMENT_REQUEST_STATUS,
    PARAM_NEXT_SYNC_DATE,
    PARAM_PHASE_FULFILLMENT,
    PARAM_PHASE_ORDERING,
)
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


@wrap_http_error
def update_agreement(mpt_client, agreement_id, **kwargs):
    response = mpt_client.put(
        f"/commerce/agreements/{agreement_id}",
        json=kwargs,
    )
    response.raise_for_status()
    return response.json()


@wrap_http_error
def get_agreements_by_query(mpt_client, query):
    agreements = []
    url = f"/commerce/agreements?{query}"
    page = None
    limit = 10
    offset = 0
    while _has_more_pages(page):
        response = mpt_client.get(f"{url}&limit={limit}&offset={offset}")
        response.raise_for_status()
        page = response.json()
        agreements.extend(page["data"])
        offset += limit

    return agreements


def get_agreements_by_next_sync(mpt_client):
    today = date.today().isoformat()
    param_condition = (
        f"any(parameters.fulfillment,and(eq(externalId,{PARAM_NEXT_SYNC_DATE})"
        f",lt(displayValue,{today})))"
    )
    status_condition = "eq(status,Active)"

    rql_query = (
        f"and({status_condition},{param_condition})&select=subscriptions,parameters,listing,product"
    )
    return get_agreements_by_query(mpt_client, rql_query)


@wrap_http_error
def update_agreement_subscription(mpt_client, subscription_id, **kwargs):
    response = mpt_client.put(
        f"/commerce/subscriptions/{subscription_id}",
        json=kwargs,
    )
    response.raise_for_status()
    return response.json()


@wrap_http_error
def get_agreement_subscription(mpt_client, subscription_id):
    response = mpt_client.get(
        f"/commerce/subscriptions/{subscription_id}",
    )
    response.raise_for_status()
    return response.json()


def get_agreements_by_3yc_commitment_request_status(mpt_client, is_recommitment=False):
    param_external_id = (
        PARAM_3YC_COMMITMENT_REQUEST_STATUS
        if not is_recommitment
        else PARAM_3YC_RECOMMITMENT_REQUEST_STATUS
    )
    request_type_param_ext_id = PARAM_3YC if not is_recommitment else PARAM_3YC_RECOMMITMENT
    request_type_param_phase = (
        PARAM_PHASE_ORDERING if not is_recommitment else PARAM_PHASE_FULFILLMENT
    )

    enroll_status_condition = (
        "any(parameters.fulfillment,and("
        f"eq(externalId,{param_external_id}),"
        f"in(displayValue,({STATUS_3YC_REQUESTED},{STATUS_3YC_ACCEPTED}))"
        ")"
        ")"
    )
    request_3yc_condition = (
        f"any(parameters.{request_type_param_phase},and("
        f"eq(externalId,{request_type_param_ext_id}),"
        "like(displayValue,*Yes*)"
        ")"
        ")"
    )
    status_condition = "eq(status,Active)"

    rql_query = (
        f"and({status_condition},{enroll_status_condition},{request_3yc_condition})&select=parameters"
    )
    return get_agreements_by_query(mpt_client, rql_query)


@wrap_http_error
def get_agreements_for_3yc_resubmit(mpt_client, is_recommitment=False):
    param_external_id = (
        PARAM_3YC_COMMITMENT_REQUEST_STATUS
        if not is_recommitment
        else PARAM_3YC_RECOMMITMENT_REQUEST_STATUS
    )

    request_type_param_ext_id = PARAM_3YC if not is_recommitment else PARAM_3YC_RECOMMITMENT
    request_type_param_phase = (
        PARAM_PHASE_ORDERING if not is_recommitment else PARAM_PHASE_FULFILLMENT
    )

    error_statuses = [STATUS_3YC_DECLINED, STATUS_3YC_NONCOMPLIANT, STATUS_3YC_EXPIRED]

    enroll_status_condition = (
        "any(parameters.fulfillment,and("
        f"eq(externalId,{param_external_id}),"
        f"in(displayValue,({','.join(error_statuses)}))"
        ")"
        ")"
    )
    request_3yc_condition = (
        f"any(parameters.{request_type_param_phase},and("
        f"eq(externalId,{request_type_param_ext_id}),"
        "like(displayValue,*Yes*)"
        ")"
        ")"
    )
    status_condition = "eq(status,Active)"

    rql_query = (
        f"and({status_condition},{enroll_status_condition},{request_3yc_condition})&select=parameters"
    )
    return get_agreements_by_query(mpt_client, rql_query)


def get_agreements_for_3yc_recommitment(mpt_client):
    today = date.today()
    limit_date = today + timedelta(days=30)
    enroll_status_condition = (
        "any(parameters.fulfillment,and("
        f"eq(externalId,{PARAM_3YC_ENROLL_STATUS}),"
        f"eq(displayValue,{STATUS_3YC_COMMITTED})"
        ")"
        ")"
    )
    recommitment_condition = (
        "any(parameters.fulfillment,and("
        f"eq(externalId,{PARAM_3YC_RECOMMITMENT}),"
        "like(displayValue,*Yes*)"
        ")"
        ")"
    )
    enddate_gt_condition = (
        "any(parameters.ordering,and("
        f"eq(externalId,{PARAM_3YC_END_DATE}),"
        f"gt(displayValue,{limit_date.isoformat()})"
        ")"
        ")"
    )
    enddate_le_condition = (
        "any(parameters.ordering,and("
        f"eq(externalId,{PARAM_3YC_END_DATE}),"
        f"le(displayValue,{today.isoformat()})"
        ")"
        ")"
    )
    status_condition = "eq(status,Active)"

    all_conditions = (
        enroll_status_condition,
        recommitment_condition,
        enddate_gt_condition,
        enddate_le_condition,
        status_condition,
    )

    rql_query = f"and({','.join(all_conditions)})&select=parameters"
    return get_agreements_by_query(mpt_client, rql_query)


@wrap_http_error
def get_rendered_template(mpt_client, order_id):
    response = mpt_client.get(
        f"/commerce/orders/{order_id}/template",
    )
    response.raise_for_status()
    return response.json()
