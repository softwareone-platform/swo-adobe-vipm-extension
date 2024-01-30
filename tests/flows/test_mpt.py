from urllib.parse import urljoin

import pytest
from responses import Response, matchers

from adobe_vipm.flows.errors import MPTError
from adobe_vipm.flows.mpt import (
    complete_order,
    create_subscription,
    fail_order,
    get_buyer,
    get_order_subscriptions,
    get_seller,
    query_order,
    update_order,
)


def test_fail_order(mpt_client, requests_mocker):
    """Test the call to switch an order to Failed."""
    requests_mocker.post(
        urljoin(mpt_client.base_url, "commerce/orders/ORD-0000/fail"),
        json={"failed": "order"},
        match=[
            matchers.json_params_matcher(
                {
                    "reason": "a-reason",
                },
            ),
        ],
    )

    failed_order = fail_order(mpt_client, "ORD-0000", "a-reason")
    assert failed_order == {"failed": "order"}


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

    assert cv.value.status == 404


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

    assert cv.value.status == 404


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

    assert cv.value.status == 404


def test_query_order(mpt_client, requests_mocker):
    """Test the call to switch an order to Query."""
    requests_mocker.post(
        urljoin(mpt_client.base_url, "commerce/orders/ORD-0000/query"),
        json={"query": "order"},
        match=[
            matchers.json_params_matcher(
                {
                    "parameters": [{"name": "a-param", "value": "a-value"}],
                },
            ),
        ],
    )

    qorder = query_order(
        mpt_client,
        "ORD-0000",
        {
            "parameters": [
                {"name": "a-param", "value": "a-value"},
            ],
        },
    )
    assert qorder == {"query": "order"}


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
        query_order(mpt_client, "ORD-0000", {})

    assert cv.value.status == 404


def test_update_order(mpt_client, requests_mocker):
    """Test the call to update an order."""
    requests_mocker.put(
        urljoin(mpt_client.base_url, "commerce/orders/ORD-0000"),
        json={"updated": "order"},
        match=[
            matchers.json_params_matcher(
                {
                    "parameters": [{"name": "a-param", "value": "a-value"}],
                },
            ),
        ],
    )

    updated_order = update_order(
        mpt_client,
        "ORD-0000",
        {
            "parameters": [
                {"name": "a-param", "value": "a-value"},
            ],
        },
    )
    assert updated_order == {"updated": "order"}


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
        update_order(mpt_client, "ORD-0000", {})

    assert cv.value.status == 404


def test_complete_order(mpt_client, requests_mocker):
    """Test the call to switch an order to Completed."""
    requests_mocker.post(
        urljoin(mpt_client.base_url, "commerce/orders/ORD-0000/complete"),
        json={"completed": "order"},
        match=[
            matchers.json_params_matcher(
                {
                    "template": {"id": "template_id"},
                },
            ),
        ],
    )

    completed_order = complete_order(
        mpt_client,
        "ORD-0000",
        "template_id",
    )
    assert completed_order == {"completed": "order"}


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
        complete_order(mpt_client, "ORD-0000", {})

    assert cv.value.status == 404


def test_create_subscription(mpt_client, requests_mocker):
    """Test the call to create a subscription."""
    requests_mocker.post(
        urljoin(mpt_client.base_url, "commerce/orders/ORD-0000/subscriptions"),
        json={"a": "subscription"},
        status=201,
        match=[
            matchers.json_params_matcher({"subscription": "payload"}),
        ],
    )

    subscription = create_subscription(
        mpt_client,
        "ORD-0000",
        {"subscription": "payload"},
    )
    assert subscription == {"a": "subscription"}


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

    assert cv.value.status == 404


def test_get_order_subscriptions(mpt_client, requests_mocker):
    """
    Test the call to retrieve all the subscriptions of an order.
    """

    subscriptions = [{"id": f"SUB-{i}"} for i in range(20)]

    page1 = Response(
        "GET",
        urljoin(mpt_client.base_url, "commerce/orders/ORD-0000/subscriptions?limit=10&offset=0"),
        status=200,
        match=[matchers.query_param_matcher({"limit": "10", "offset": "0"})],
        json={
            "$meta": {
                "pagination": {
                    "total": 20,
                    "limit": 10,
                    "offset": 0,
                },
            },
            "data": subscriptions[0:10],
        },
    )

    page2 = Response(
        "GET",
        urljoin(mpt_client.base_url, "commerce/orders/ORD-0000/subscriptions?limit=10&offset=10"),
        status=200,
        match=[matchers.query_param_matcher({"limit": "10", "offset": "10"})],
        json={
            "$meta": {
                "pagination": {
                    "total": 20,
                    "limit": 10,
                    "offset": 10,
                },
            },
            "data": subscriptions[10:],
        },
    )

    requests_mocker.add(page1)
    requests_mocker.add(page2)

    assert get_order_subscriptions(mpt_client, "ORD-0000") == subscriptions


def test_get_order_subscriptions_error(mpt_client, requests_mocker, mpt_error_factory):
    """
    Test the call to retrieve all the subscriptions of an order when it fails.
    """
    requests_mocker.get(
        urljoin(mpt_client.base_url, "commerce/orders/ORD-0000/subscriptions"),
        status=404,
        json=mpt_error_factory(404, "Not Found", "Order not found"),
    )

    with pytest.raises(MPTError) as cv:
        get_order_subscriptions(mpt_client, "ORD-0000")

    assert cv.value.status == 404
