from urllib.parse import urljoin

import pytest
from responses import matchers

from adobe_vipm.flows.errors import MPTError
from adobe_vipm.flows.mpt import (
    complete_order,
    create_subscription,
    fail_order,
    get_buyer,
    get_product_items,
    get_seller,
    query_order,
    update_order,
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
                    "reason": "a-reason",
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

    with pytest.raises(MPTError) as cv:
        fail_order(mpt_client, "ORD-0000", "a-reason")

    assert cv.value.payload["status"] == 404


def test_get_buyer(mpt_client, requests_mocker):
    """Test the call to retrieve a buyer."""
    requests_mocker.get(
        urljoin(mpt_client.base_url, "accounts/buyers/BUY-0000"),
        json={"a": "buyer"},
    )

    buyer = get_buyer(mpt_client, "BUY-0000")
    assert buyer == {"a": "buyer"}


def test_get_buyer_error(mpt_client, requests_mocker, mpt_error_factory):
    """
    Test the call to to retrieve a buyer when it fails.
    """
    requests_mocker.get(
        urljoin(mpt_client.base_url, "accounts/buyers/BUY-0000"),
        status=404,
        json=mpt_error_factory(404, "Not Found", "Buyer not found"),
    )

    with pytest.raises(MPTError) as cv:
        get_buyer(mpt_client, "BUY-0000")

    assert cv.value.payload["status"] == 404


def test_get_seller(mpt_client, requests_mocker):
    """Test the call to retrieve a seller."""
    requests_mocker.get(
        urljoin(mpt_client.base_url, "accounts/sellers/SEL-0000"),
        json={"a": "seller"},
    )

    seller = get_seller(mpt_client, "SEL-0000")
    assert seller == {"a": "seller"}


def test_get_seller_error(mpt_client, requests_mocker, mpt_error_factory):
    """
    Test the call to to retrieve a seller when it fails.
    """
    requests_mocker.get(
        urljoin(mpt_client.base_url, "accounts/sellers/SEL-0000"),
        status=404,
        json=mpt_error_factory(404, "Not Found", "Buyer not found"),
    )

    with pytest.raises(MPTError) as cv:
        get_seller(mpt_client, "SEL-0000")

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

    with pytest.raises(MPTError) as cv:
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

    with pytest.raises(MPTError) as cv:
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
        "templateId",
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

    with pytest.raises(MPTError) as cv:
        complete_order(mpt_client, "ORD-0000", "templateId")

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

    with pytest.raises(MPTError) as cv:
        create_subscription(mpt_client, "ORD-0000", {})

    assert cv.value.payload["status"] == 404


def test_get_product_items(
    mpt_client, requests_mocker, settings, product_item_factory, mpt_list_response
):
    """Test the call to create a subscription."""
    item = product_item_factory()

    requests_mocker.get(
        urljoin(
            mpt_client.base_url,
            f"product-items?product.id={settings.PRODUCT_ID}&in(externalIds.vendor,({item['id']}))",
        ),
        json=mpt_list_response([item]),
        status=200,
    )

    product_items = get_product_items(mpt_client, settings.PRODUCT_ID, [it["id"] for it in [item]])
    assert product_items == [item]
