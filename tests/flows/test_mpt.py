from urllib.parse import urljoin

import pytest
from freezegun import freeze_time
from responses import matchers

from adobe_vipm.adobe.constants import (
    STATUS_3YC_ACCEPTED,
    STATUS_3YC_COMMITTED,
    STATUS_3YC_DECLINED,
    STATUS_3YC_EXPIRED,
    STATUS_3YC_NONCOMPLIANT,
    STATUS_3YC_REQUESTED,
)
from adobe_vipm.flows.constants import (
    PARAM_3YC,
    PARAM_3YC_COMMITMENT_REQUEST_STATUS,
    PARAM_3YC_END_DATE,
    PARAM_3YC_ENROLL_STATUS,
    PARAM_3YC_RECOMMITMENT,
    PARAM_3YC_RECOMMITMENT_REQUEST_STATUS,
    PARAM_NEXT_SYNC_DATE,
)
from adobe_vipm.flows.errors import MPTAPIError
from adobe_vipm.flows.mpt import (
    complete_order,
    create_subscription,
    fail_order,
    get_agreement_subscription,
    get_agreements_by_3yc_commitment_request_status,
    get_agreements_by_next_sync,
    get_agreements_by_query,
    get_agreements_for_3yc_recommitment,
    get_agreements_for_3yc_resubmit,
    get_pricelist_items_by_product_items,
    get_product_items_by_skus,
    get_product_template_or_default,
    get_rendered_template,
    get_subscription_by_external_id,
    get_webhook,
    query_order,
    update_agreement,
    update_agreement_subscription,
    update_order,
    update_subscription,
)


def test_fail_order(mpt_client, requests_mocker, order_factory):
    """Test the call to switch an order to Failed."""
    order = order_factory()
    requests_mocker.post(
        urljoin(mpt_client.base_url, "commerce/orders/ORD-0000/fail"),
        json=order,
        match=[
            matchers.json_params_matcher(
                {
                    "statusNotes": {
                        "id": "VIPM001",
                        "message": "Order can't be processed. Failure reason: a-reason",
                    },
                },
            ),
        ],
    )

    failed_order = fail_order(mpt_client, "ORD-0000", "a-reason")
    assert failed_order == order


def test_fail_order_error(mpt_client, requests_mocker, mpt_error_factory):
    """
    Test the call to switch an order to Failed when it fails.
    """
    requests_mocker.post(
        urljoin(mpt_client.base_url, "commerce/orders/ORD-0000/fail"),
        status=404,
        json=mpt_error_factory(404, "Not Found", "Order not found"),
    )

    with pytest.raises(MPTAPIError) as cv:
        fail_order(mpt_client, "ORD-0000", "a-reason")

    assert cv.value.payload["status"] == 404


def test_query_order(mpt_client, requests_mocker, order_factory):
    """Test the call to switch an order to Query."""
    order = order_factory()
    requests_mocker.post(
        urljoin(mpt_client.base_url, "commerce/orders/ORD-0000/query"),
        json=order,
        match=[
            matchers.json_params_matcher(
                {
                    "parameters": {
                        "ordering": [
                            {
                                "externalId": "a-param",
                                "name": "a-param",
                                "value": "a-value",
                                "type": "SingleLineText",
                            }
                        ],
                    },
                },
            ),
        ],
    )

    qorder = query_order(
        mpt_client,
        "ORD-0000",
        parameters={
            "ordering": [
                {
                    "externalId": "a-param",
                    "name": "a-param",
                    "value": "a-value",
                    "type": "SingleLineText",
                }
            ]
        },
    )
    assert qorder == order


def test_query_order_error(mpt_client, requests_mocker, mpt_error_factory):
    """
    Test the call to switch an order to Query when it fails.
    """
    requests_mocker.post(
        urljoin(mpt_client.base_url, "commerce/orders/ORD-0000/query"),
        status=404,
        json=mpt_error_factory(404, "Not Found", "Order not found"),
    )

    with pytest.raises(MPTAPIError) as cv:
        query_order(mpt_client, "ORD-0000", parameters={})

    assert cv.value.payload["status"] == 404


def test_update_order(mpt_client, requests_mocker, order_factory):
    """Test the call to update an order."""
    order = order_factory()
    requests_mocker.put(
        urljoin(mpt_client.base_url, "commerce/orders/ORD-0000"),
        json=order,
        match=[
            matchers.json_params_matcher(
                {
                    "parameters": {
                        "ordering": [
                            {
                                "externalId": "a-param",
                                "name": "a-param",
                                "value": "a-value",
                                "type": "SingleLineText",
                            }
                        ],
                    },
                },
            ),
        ],
    )

    updated_order = update_order(
        mpt_client,
        "ORD-0000",
        parameters={
            "ordering": [
                {
                    "externalId": "a-param",
                    "name": "a-param",
                    "value": "a-value",
                    "type": "SingleLineText",
                }
            ]
        },
    )
    assert updated_order == order


def test_update_order_error(mpt_client, requests_mocker, mpt_error_factory):
    """
    Test the call to update an order when it fails.
    """
    requests_mocker.put(
        urljoin(mpt_client.base_url, "commerce/orders/ORD-0000"),
        status=404,
        json=mpt_error_factory(404, "Not Found", "Order not found"),
    )

    with pytest.raises(MPTAPIError) as cv:
        update_order(mpt_client, "ORD-0000", parameters={})

    assert cv.value.payload["status"] == 404


def test_complete_order(mpt_client, requests_mocker, order_factory):
    """Test the call to switch an order to Completed."""
    order = order_factory()
    requests_mocker.post(
        urljoin(mpt_client.base_url, "commerce/orders/ORD-0000/complete"),
        json=order,
        match=[
            matchers.json_params_matcher(
                {
                    "template": {"id": "templateId"},
                },
            ),
        ],
    )

    completed_order = complete_order(
        mpt_client,
        "ORD-0000",
        {"id": "templateId"},
    )
    assert completed_order == order


def test_complete_order_error(mpt_client, requests_mocker, mpt_error_factory):
    """
    Test the call to switch an order to Completed when it fails.
    """
    requests_mocker.post(
        urljoin(mpt_client.base_url, "commerce/orders/ORD-0000/complete"),
        status=404,
        json=mpt_error_factory(404, "Not Found", "Order not found"),
    )

    with pytest.raises(MPTAPIError) as cv:
        complete_order(mpt_client, "ORD-0000", {"id": "templateId"})

    assert cv.value.payload["status"] == 404


def test_create_subscription(mpt_client, requests_mocker, subscriptions_factory):
    """Test the call to create a subscription."""
    subscription = subscriptions_factory()[0]
    requests_mocker.post(
        urljoin(mpt_client.base_url, "commerce/orders/ORD-0000/subscriptions"),
        json=subscription,
        status=201,
        match=[
            matchers.json_params_matcher(subscription),
        ],
    )

    created_subscription = create_subscription(
        mpt_client,
        "ORD-0000",
        subscription,
    )
    assert created_subscription == subscription


def test_create_subscription_error(mpt_client, requests_mocker, mpt_error_factory):
    """
    Test the call to create a subscription when it fails.
    """
    requests_mocker.post(
        urljoin(mpt_client.base_url, "commerce/orders/ORD-0000/subscriptions"),
        status=404,
        json=mpt_error_factory(404, "Not Found", "Order not found"),
    )

    with pytest.raises(MPTAPIError) as cv:
        create_subscription(mpt_client, "ORD-0000", {})

    assert cv.value.payload["status"] == 404


def test_update_subscription(mpt_client, requests_mocker, subscriptions_factory):
    """Test the call to update a subscription."""
    subscription = subscriptions_factory()
    requests_mocker.put(
        urljoin(
            mpt_client.base_url,
            "commerce/orders/ORD-0000/subscriptions/SUB-1234",
        ),
        json=subscription,
        match=[
            matchers.json_params_matcher(
                {
                    "parameters": {
                        "fulfillment": [
                            {
                                "externalId": "a-param",
                                "name": "a-param",
                                "value": "a-value",
                                "type": "SingleLineText",
                            }
                        ],
                    },
                },
            ),
        ],
    )

    updated_subscription = update_subscription(
        mpt_client,
        "ORD-0000",
        "SUB-1234",
        parameters={
            "fulfillment": [
                {
                    "externalId": "a-param",
                    "name": "a-param",
                    "value": "a-value",
                    "type": "SingleLineText",
                }
            ]
        },
    )
    assert updated_subscription == subscription


def test_update_subscription_error(mpt_client, requests_mocker, mpt_error_factory):
    """
    Test the call to update a subscription when it fails.
    """
    requests_mocker.put(
        urljoin(mpt_client.base_url, "commerce/orders/ORD-0000/subscriptions/SUB-1234"),
        status=404,
        json=mpt_error_factory(404, "Not Found", "Order not found"),
    )

    with pytest.raises(MPTAPIError) as cv:
        update_subscription(mpt_client, "ORD-0000", "SUB-1234", parameters={})

    assert cv.value.payload["status"] == 404


def test_get_product_items_by_skus(mpt_client, requests_mocker):
    """
    Tests the call to retrieve all the item of a given product
    that matches a list of vendor SKUs.
    """
    product_id = "PRD-1234-5678"
    skus = ["sku1", "sku2"]
    rql_query = (
        f"and(eq(product.id,{product_id}),in(externalIds.vendor,({','.join(skus)})))"
    )
    url = f"items?{rql_query}"
    page1_url = f"{url}&limit=10&offset=0"
    page2_url = f"{url}&limit=10&offset=10"
    data = [{"id": f"ITM-{idx}"} for idx in range(13)]
    requests_mocker.get(
        urljoin(mpt_client.base_url, page1_url),
        json={
            "$meta": {
                "pagination": {
                    "offset": 0,
                    "limit": 10,
                    "total": 12,
                },
            },
            "data": data[:10],
        },
    )
    requests_mocker.get(
        urljoin(mpt_client.base_url, page2_url),
        json={
            "$meta": {
                "pagination": {
                    "offset": 10,
                    "limit": 10,
                    "total": 12,
                },
            },
            "data": data[10:],
        },
    )

    assert get_product_items_by_skus(mpt_client, product_id, skus) == data


def test_get_product_items_by_skus_error(
    mpt_client, requests_mocker, mpt_error_factory
):
    """
    Tests the call to retrieve all the item of a given product
    that matches a list of vendor SKUs.
    """
    product_id = "PRD-1234-5678"
    skus = ["sku1", "sku2"]
    rql_query = (
        f"and(eq(product.id,{product_id}),in(externalIds.vendor,({','.join(skus)})))"
    )
    url = f"items?{rql_query}&limit=10&offset=0"

    requests_mocker.get(
        urljoin(mpt_client.base_url, url),
        status=500,
        json=mpt_error_factory(500, "Internal server error", "Whatever"),
    )

    with pytest.raises(MPTAPIError) as cv:
        get_product_items_by_skus(mpt_client, product_id, skus)

    assert cv.value.payload["status"] == 500


def test_get_pricelist_items_by_product_items(mpt_client, requests_mocker):
    """
    Tests the call to retrieve the pricelist items given the pricelist id and
    the product item ids.
    """

    url = "price-lists/PRC-1234/items?in(item.id,(ITM-5678,ITM-9012))"
    page1_url = f"{url}&limit=10&offset=0"
    page2_url = f"{url}&limit=10&offset=10"
    data = [{"id": f"PRI-{idx}"} for idx in range(13)]
    requests_mocker.get(
        urljoin(mpt_client.base_url, page1_url),
        json={
            "$meta": {
                "pagination": {
                    "offset": 0,
                    "limit": 10,
                    "total": 12,
                },
            },
            "data": data[:10],
        },
    )
    requests_mocker.get(
        urljoin(mpt_client.base_url, page2_url),
        json={
            "$meta": {
                "pagination": {
                    "offset": 10,
                    "limit": 10,
                    "total": 12,
                },
            },
            "data": data[10:],
        },
    )

    assert (
        get_pricelist_items_by_product_items(
            mpt_client,
            "PRC-1234",
            ["ITM-5678", "ITM-9012"],
        )
        == data
    )


def test_get_pricelist_item_by_product_item_error(
    mpt_client, requests_mocker, mpt_error_factory
):
    """
    Tests the call to retrieve a pricelist item given the pricelist id and
    the product item id when it fails.
    """
    url = "price-lists/PRC-1234/items?in(item.id,(ITM-5678))"
    url = f"{url}&limit=10&offset=0"
    requests_mocker.get(
        urljoin(mpt_client.base_url, url),
        status=500,
        json=mpt_error_factory(500, "Internal server error", "Whatever"),
    )

    with pytest.raises(MPTAPIError) as cv:
        get_pricelist_items_by_product_items(mpt_client, "PRC-1234", ["ITM-5678"])

    assert cv.value.payload["status"] == 500


def test_get_webhoook(mpt_client, requests_mocker, webhook):
    requests_mocker.get(
        urljoin(mpt_client.base_url, f"notifications/webhooks/{webhook["id"]}"),
        json=webhook,
    )

    api_webhook = get_webhook(mpt_client, webhook["id"])
    assert api_webhook == webhook


@pytest.mark.parametrize(
    ("total", "data", "expected"),
    [
        (0, [], None),
        (1, [{"id": "SUB-1234"}], {"id": "SUB-1234"}),
    ],
)
def test_get_subscription_by_external_id(
    mpt_client, requests_mocker, total, data, expected
):
    requests_mocker.get(
        urljoin(
            mpt_client.base_url,
            "/v1/commerce/orders/ORD-1234/subscriptions?eq(externalIds.vendor,a-sub-id)&limit=1",
        ),
        json={
            "$meta": {
                "pagination": {
                    "offset": 0,
                    "limit": 0,
                    "total": total,
                },
            },
            "data": data,
        },
    )

    assert (
        get_subscription_by_external_id(mpt_client, "ORD-1234", "a-sub-id") == expected
    )


@pytest.mark.parametrize("name", ["template_name", None])
def test_get_product_template_or_default(mpt_client, requests_mocker, name):
    name_or_default_filter = "eq(default,true)"
    if name:
        name_or_default_filter = f"or({name_or_default_filter},eq(name,{name}))"
    rql_filter = f"and(eq(type,OrderProcessing),{name_or_default_filter})"
    url = f"/v1/products/PRD-1111/templates?{rql_filter}&order=default&limit=1"
    requests_mocker.get(
        urljoin(
            mpt_client.base_url,
            url,
        ),
        json={
            "data": [
                {"id": "TPL-0000"},
            ]
        },
    )

    assert get_product_template_or_default(
        mpt_client,
        "PRD-1111",
        "Processing",
        name,
    ) == {"id": "TPL-0000"}


def test_update_agreement(mpt_client, requests_mocker):
    """Test the call to update an agreement."""
    requests_mocker.put(
        urljoin(mpt_client.base_url, "commerce/agreements/AGR-1111"),
        json={"id": "AGR-1111"},
        match=[
            matchers.json_params_matcher(
                {
                    "externalIds": {
                        "vendor": "1234",
                    },
                },
            ),
        ],
    )

    updated_agreement = update_agreement(
        mpt_client,
        "AGR-1111",
        externalIds={"vendor": "1234"},
    )
    assert updated_agreement == {"id": "AGR-1111"}


def test_update_agreement_error(mpt_client, requests_mocker, mpt_error_factory):
    """
    Test the call to update an order when it fails.
    """
    requests_mocker.put(
        urljoin(mpt_client.base_url, "commerce/agreements/AGR-1111"),
        status=404,
        json=mpt_error_factory(404, "Not Found", "Order not found"),
    )

    with pytest.raises(MPTAPIError) as cv:
        update_agreement(mpt_client, "AGR-1111", externalIds={"vendor": "1234"})

    assert cv.value.payload["status"] == 404


def test_update_agreement_subscription(
    mpt_client, requests_mocker, subscriptions_factory
):
    subscription = subscriptions_factory()
    requests_mocker.put(
        urljoin(
            mpt_client.base_url,
            "commerce/subscriptions/SUB-1234",
        ),
        json=subscription,
        match=[
            matchers.json_params_matcher(
                {
                    "parameters": {
                        "fulfillment": [
                            {
                                "externalId": "a-param",
                                "name": "a-param",
                                "value": "a-value",
                                "type": "SingleLineText",
                            }
                        ],
                    },
                },
            ),
        ],
    )

    updated_subscription = update_agreement_subscription(
        mpt_client,
        "SUB-1234",
        parameters={
            "fulfillment": [
                {
                    "externalId": "a-param",
                    "name": "a-param",
                    "value": "a-value",
                    "type": "SingleLineText",
                }
            ]
        },
    )
    assert updated_subscription == subscription


def test_update_agreement_subscription_error(
    mpt_client, requests_mocker, mpt_error_factory
):
    requests_mocker.put(
        urljoin(mpt_client.base_url, "commerce/subscriptions/SUB-1234"),
        status=404,
        json=mpt_error_factory(404, "Not Found", "Order not found"),
    )

    with pytest.raises(MPTAPIError) as cv:
        update_agreement_subscription(mpt_client, "SUB-1234", parameters={})

    assert cv.value.payload["status"] == 404


def test_get_agreement_subscription(mpt_client, requests_mocker, subscriptions_factory):
    sub = subscriptions_factory()[0]
    requests_mocker.get(
        urljoin(mpt_client.base_url, f"commerce/subscriptions/{sub["id"]}"),
        json=sub,
    )

    assert get_agreement_subscription(mpt_client, sub["id"]) == sub


def test_get_agreement_subscription_error(
    mpt_client, requests_mocker, mpt_error_factory
):
    requests_mocker.get(
        urljoin(mpt_client.base_url, "commerce/subscriptions/SUB-1234"),
        status=404,
        json=mpt_error_factory(404, "Not Found", "Order not found"),
    )

    with pytest.raises(MPTAPIError) as cv:
        get_agreement_subscription(mpt_client, "SUB-1234")

    assert cv.value.payload["status"] == 404


def test_get_agreements_by_query(mpt_client, requests_mocker):
    rql_query = "any-rql-query&select=any-obj"
    url = f"commerce/agreements?{rql_query}"

    page1_url = f"{url}&limit=10&offset=0"
    page2_url = f"{url}&limit=10&offset=10"
    data = [{"id": f"AGR-{idx}"} for idx in range(13)]
    requests_mocker.get(
        urljoin(mpt_client.base_url, page1_url),
        json={
            "$meta": {
                "pagination": {
                    "offset": 0,
                    "limit": 10,
                    "total": 12,
                },
            },
            "data": data[:10],
        },
    )
    requests_mocker.get(
        urljoin(mpt_client.base_url, page2_url),
        json={
            "$meta": {
                "pagination": {
                    "offset": 10,
                    "limit": 10,
                    "total": 12,
                },
            },
            "data": data[10:],
        },
    )

    assert get_agreements_by_query(mpt_client, rql_query) == data


def test_get_agreements_by_query_error(mpt_client, requests_mocker, mpt_error_factory):
    rql_query = "any-rql-query&select=any-obj"
    url = f"commerce/agreements?{rql_query}"

    url = f"{url}&limit=10&offset=0"
    requests_mocker.get(
        urljoin(mpt_client.base_url, url),
        status=500,
        json=mpt_error_factory(500, "Internal server error", "Whatever"),
    )

    with pytest.raises(MPTAPIError) as cv:
        get_agreements_by_query(mpt_client, rql_query)

    assert cv.value.payload["status"] == 500


@freeze_time("2024-01-04 03:00:00")
def test_get_agreements_by_next_sync(mocker):
    param_condition = (
        f"any(parameters.fulfillment,and(eq(externalId,{PARAM_NEXT_SYNC_DATE})"
        f",lt(displayValue,2024-01-04)))"
    )
    status_condition = "eq(status,Active)"

    rql_query = (
        f"and({status_condition},{param_condition})&select=subscriptions,parameters,listing,product"
    )


    mocked_get_by_query = mocker.patch(
        "adobe_vipm.flows.mpt.get_agreements_by_query",
        return_value=[{"id": "AGR-0001"}],
    )

    mocked_client = mocker.MagicMock()

    assert get_agreements_by_next_sync(mocked_client) == [{"id": "AGR-0001"}]
    mocked_get_by_query.assert_called_once_with(mocked_client, rql_query)


@pytest.mark.parametrize("is_recommitment", [True, False])
def test_get_agreements_by_3yc_commitment_request_status(mocker, is_recommitment):
    param_external_id = (
        PARAM_3YC_COMMITMENT_REQUEST_STATUS
        if not is_recommitment
        else PARAM_3YC_RECOMMITMENT_REQUEST_STATUS
    )
    request_type_param_ext_id = PARAM_3YC if not is_recommitment else PARAM_3YC_RECOMMITMENT
    request_type_param_phase = (
        "ordering" if not is_recommitment else "fulfillment"
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

    mocked_get_by_query = mocker.patch(
        "adobe_vipm.flows.mpt.get_agreements_by_query",
        return_value=[{"id": "AGR-0001"}],
    )

    mocked_client = mocker.MagicMock()

    assert get_agreements_by_3yc_commitment_request_status(
        mocked_client, is_recommitment=is_recommitment
    ) == [{"id": "AGR-0001"}]
    mocked_get_by_query.assert_called_once_with(mocked_client, rql_query)


@freeze_time("2024-01-01 03:00:00")
def test_get_agreements_for_3yc_recommitment(mocker):
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
        f"gt(displayValue,2024-01-31)"
        ")"
        ")"
    )
    enddate_le_condition = (
        "any(parameters.ordering,and("
        f"eq(externalId,{PARAM_3YC_END_DATE}),"
        f"le(displayValue,2024-01-01)"
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

    mocked_get_by_query = mocker.patch(
        "adobe_vipm.flows.mpt.get_agreements_by_query",
        return_value=[{"id": "AGR-0001"}],
    )

    mocked_client = mocker.MagicMock()

    assert get_agreements_for_3yc_recommitment(mocked_client) == [{"id": "AGR-0001"}]
    mocked_get_by_query.assert_called_once_with(mocked_client, rql_query)


@pytest.mark.parametrize("is_recommitment", [True, False])
def test_get_agreements_for_3yc_resubmit(mocker, is_recommitment):
    param_external_id = (
        PARAM_3YC_COMMITMENT_REQUEST_STATUS
        if not is_recommitment
        else PARAM_3YC_RECOMMITMENT_REQUEST_STATUS
    )

    request_type_param_ext_id = PARAM_3YC if not is_recommitment else PARAM_3YC_RECOMMITMENT
    request_type_param_phase = (
        "ordering" if not is_recommitment else "fulfillment"
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

    mocked_get_by_query = mocker.patch(
        "adobe_vipm.flows.mpt.get_agreements_by_query",
        return_value=[{"id": "AGR-0001"}],
    )

    mocked_client = mocker.MagicMock()

    assert get_agreements_for_3yc_resubmit(
        mocked_client, is_recommitment=is_recommitment,
    ) == [{"id": "AGR-0001"}]
    mocked_get_by_query.assert_called_once_with(mocked_client, rql_query)


def test_get_rendered_template(mpt_client, requests_mocker):
    requests_mocker.get(
        urljoin(mpt_client.base_url, "commerce/orders/ORD-1234/template"),
        json="rendered-template",
    )

    assert get_rendered_template(mpt_client, "ORD-1234") == "rendered-template"


def test_get_rendered_template_error(
    mpt_client, requests_mocker, mpt_error_factory
):
    requests_mocker.get(
        urljoin(mpt_client.base_url, "commerce/orders/ORD-1234/template"),
        status=404,
        json=mpt_error_factory(404, "Not Found", "Order not found"),
    )

    with pytest.raises(MPTAPIError) as cv:
        get_rendered_template(mpt_client, "ORD-1234")

    assert cv.value.payload["status"] == 404
