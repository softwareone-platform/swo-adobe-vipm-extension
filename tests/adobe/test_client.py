from datetime import datetime, timedelta
from urllib.parse import urljoin

import pytest
import requests
from freezegun import freeze_time
from responses import matchers

from adobe_vipm.adobe.client import AdobeClient, get_adobe_client
from adobe_vipm.adobe.constants import (
    ORDER_TYPE_NEW,
    ORDER_TYPE_PREVIEW,
    ORDER_TYPE_RETURN,
    STATUS_ORDER_INACTIVE_CUSTOMER,
    STATUS_PENDING,
    STATUS_PROCESSED,
)
from adobe_vipm.adobe.dataclasses import APIToken, Credentials
from adobe_vipm.adobe.errors import AdobeError


def test_create_reseller_account(
    mocker,
    requests_mocker,
    adobe_config_file,
    reseller_data,
    adobe_client_factory,
):
    """
    Test the call to Adobe API to create a reselled within a given distributor.
    """
    mocker.patch(
        "adobe_vipm.adobe.client.uuid4",
        return_value="uuid-1",
    )
    distributor_id = adobe_config_file["accounts"][0]["distributor_id"]
    region = adobe_config_file["accounts"][0]["region"]

    client, credentials, api_token = adobe_client_factory()

    requests_mocker.post(
        urljoin(adobe_config_file["api_base_url"], "/v3/resellers"),
        status=201,
        json={
            "resellerId": "a-reseller-id",
        },
        match=[
            matchers.header_matcher(
                {
                    "X-Api-Key": credentials.client_id,
                    "Authorization": f"Bearer {api_token.token}",
                    "Accept": "application/json",
                    "Content-Type": "application/json",
                    "X-Request-Id": "uuid-1",
                    "x-correlation-id": "external_id",
                },
            ),
            matchers.json_params_matcher(
                {
                    "distributorId": distributor_id,
                    "externalReferenceId": "external_id",
                    "companyProfile": {
                        "companyName": reseller_data["companyName"],
                        "preferredLanguage": reseller_data["preferredLanguage"],
                        "address": {
                            "country": reseller_data["address"]["country"],
                            "region": reseller_data["address"]["state"],
                            "city": reseller_data["address"]["city"],
                            "addressLine1": reseller_data["address"]["addressLine1"],
                            "addressLine2": reseller_data["address"]["addressLine2"],
                            "postalCode": reseller_data["address"]["postCode"],
                            "phoneNumber": reseller_data["contact"]["phoneNumber"],
                        },
                        "contacts": [
                            {
                                "firstName": reseller_data["contact"]["firstName"],
                                "lastName": reseller_data["contact"]["lastName"],
                                "email": reseller_data["contact"]["email"],
                                "phoneNumber": reseller_data["contact"]["phoneNumber"],
                            }
                        ],
                    },
                },
            ),
        ],
    )

    reseller_id = client.create_reseller_account(region, "external_id", reseller_data)
    assert reseller_id == "a-reseller-id"


def test_create_reseller_account_bad_request(
    requests_mocker,
    adobe_config_file,
    reseller_data,
    adobe_api_error_factory,
    adobe_client_factory,
):
    """
    Test the call to Adobe API to create a reseller when the response is 400 bad request.
    """
    region = adobe_config_file["accounts"][0]["region"]

    client, _, _ = adobe_client_factory()

    error = adobe_api_error_factory("1234", "An error")

    requests_mocker.post(
        urljoin(adobe_config_file["api_base_url"], "/v3/resellers"),
        status=400,
        json=error,
    )

    with pytest.raises(AdobeError) as cv:
        client.create_reseller_account(region, "external_id", reseller_data)

    assert repr(cv.value) == str(error)


def test_create_customer_account(
    mocker,
    requests_mocker,
    adobe_config_file,
    customer_data,
    adobe_client_factory,
):
    """
    Test the call to Adobe API to create a customer.
    """
    mocker.patch(
        "adobe_vipm.adobe.client.uuid4",
        return_value="uuid-1",
    )
    reseller_id = adobe_config_file["accounts"][0]["resellers"][0]["id"]
    reseller_country = adobe_config_file["accounts"][0]["resellers"][0]["country"]

    client, credentials, api_token = adobe_client_factory()

    company_name = f"{customer_data['companyName']} (external_id)"

    requests_mocker.post(
        urljoin(adobe_config_file["api_base_url"], "/v3/customers"),
        status=201,
        json={
            "customerId": "A-customer-id",
        },
        match=[
            matchers.header_matcher(
                {
                    "X-Api-Key": credentials.client_id,
                    "Authorization": f"Bearer {api_token.token}",
                    "Accept": "application/json",
                    "Content-Type": "application/json",
                    "X-Request-Id": "uuid-1",
                    "x-correlation-id": "external_id",
                },
            ),
            matchers.json_params_matcher(
                {
                    "resellerId": reseller_id,
                    "externalReferenceId": "external_id",
                    "companyProfile": {
                        "companyName": company_name,
                        "preferredLanguage": customer_data["preferredLanguage"],
                        "address": {
                            "country": customer_data["address"]["country"],
                            "region": customer_data["address"]["state"],
                            "city": customer_data["address"]["city"],
                            "addressLine1": customer_data["address"]["addressLine1"],
                            "addressLine2": customer_data["address"]["addressLine2"],
                            "postalCode": customer_data["address"]["postCode"],
                            "phoneNumber": customer_data["contact"]["phoneNumber"],
                        },
                        "contacts": [
                            {
                                "firstName": customer_data["contact"]["firstName"],
                                "lastName": customer_data["contact"]["lastName"],
                                "email": customer_data["contact"]["email"],
                                "phoneNumber": customer_data["contact"]["phoneNumber"],
                            }
                        ],
                    },
                },
            ),
        ],
    )

    customer_id = client.create_customer_account(reseller_country, "external_id", customer_data)
    assert customer_id == "A-customer-id"


def test_create_customer_account_bad_request(
    requests_mocker,
    adobe_config_file,
    customer_data,
    adobe_api_error_factory,
    adobe_client_factory,
):
    """
    Test the call to Adobe API to create a customer when the response is 400 bad request.
    """
    reseller_country = adobe_config_file["accounts"][0]["resellers"][0]["country"]

    client, _, _ = adobe_client_factory()

    error = adobe_api_error_factory("1234", "An error")

    requests_mocker.post(
        urljoin(adobe_config_file["api_base_url"], "/v3/customers"),
        status=400,
        json=error,
    )

    with pytest.raises(AdobeError) as cv:
        client.create_customer_account(reseller_country, "external_id", customer_data)

    assert repr(cv.value) == str(error)


@pytest.mark.parametrize(
    ("quantity", "old_quantity", "expected_quantity"),
    [
        (10, 0, 10),
        (10, 2, 8),
        (5, 10, 5),
    ],
)
def test_create_preview_order(
    mocker,
    requests_mocker,
    adobe_config_file,
    order_factory,
    lines_factory,
    adobe_client_factory,
    quantity,
    old_quantity,
    expected_quantity,
):
    """
    Test the call to Adobe API to create a preview order.
    """
    mocker.patch(
        "adobe_vipm.adobe.client.uuid4",
        side_effect=["uuid-1", "uuid-2"],
    )
    reseller_country = adobe_config_file["accounts"][0]["resellers"][0]["country"]
    adobe_full_sku = adobe_config_file["skus_mapping"][0]["sku"]
    customer_id = "a-customer"

    client, credentials, api_token = adobe_client_factory()

    order = order_factory(lines=lines_factory(old_quantity=old_quantity, quantity=quantity))

    requests_mocker.post(
        urljoin(adobe_config_file["api_base_url"], f"/v3/customers/{customer_id}/orders"),
        status=200,
        json={
            "orderId": "adobe-order-id",
        },
        match=[
            matchers.header_matcher(
                {
                    "X-Api-Key": credentials.client_id,
                    "Authorization": f"Bearer {api_token.token}",
                    "Accept": "application/json",
                    "Content-Type": "application/json",
                    "X-Request-Id": "uuid-1",
                    "x-correlation-id": "uuid-2",
                },
            ),
            matchers.json_params_matcher(
                {
                    "externalReferenceId": order["id"],
                    "currencyCode": "USD",
                    "orderType": "PREVIEW",
                    "lineItems": [
                        {
                            "extLineItemNumber": order["lines"][0]["id"],
                            "offerId": adobe_full_sku,
                            "quantity": expected_quantity,
                        },
                    ],
                },
            ),
        ],
    )

    preview_order = client.create_preview_order(
        reseller_country,
        customer_id,
        order["id"],
        order["lines"],
    )
    assert preview_order == {
        "orderId": "adobe-order-id",
    }


def test_create_preview_order_bad_request(
    requests_mocker,
    adobe_config_file,
    adobe_api_error_factory,
    adobe_client_factory,
    order,
):
    """
    Test the call to Adobe API to create a preview order when the response is 400 bad request.
    """
    reseller_country = adobe_config_file["accounts"][0]["resellers"][0]["country"]
    customer_id = "a-customer"

    client, _, _ = adobe_client_factory()

    error = adobe_api_error_factory("1234", "An error")

    requests_mocker.post(
        urljoin(adobe_config_file["api_base_url"], f"/v3/customers/{customer_id}/orders"),
        status=400,
        json=error,
    )

    with pytest.raises(AdobeError) as cv:
        client.create_preview_order(
            reseller_country,
            customer_id,
            order["id"],
            order["lines"],
        )

    assert repr(cv.value) == str(error)


def test_create_new_order(
    mocker,
    requests_mocker,
    adobe_client_factory,
    adobe_config_file,
    adobe_order_factory,
):
    """
    Test the call to Adobe API to create a new order.
    """
    mocker.patch(
        "adobe_vipm.adobe.client.uuid4",
        return_value="uuid-1",
    )
    reseller_country = adobe_config_file["accounts"][0]["resellers"][0]["country"]
    customer_id = "a-customer"

    client, credentials, api_token = adobe_client_factory()

    adobe_order = adobe_order_factory(ORDER_TYPE_NEW, external_id="mpt-order-id")

    requests_mocker.post(
        urljoin(adobe_config_file["api_base_url"], f"/v3/customers/{customer_id}/orders"),
        status=202,
        json={
            "orderId": "adobe-order-id",
        },
        match=[
            matchers.header_matcher(
                {
                    "X-Api-Key": credentials.client_id,
                    "Authorization": f"Bearer {api_token.token}",
                    "Accept": "application/json",
                    "Content-Type": "application/json",
                    "X-Request-Id": "uuid-1",
                    "x-correlation-id": adobe_order["externalReferenceId"],
                },
            ),
            matchers.json_params_matcher(adobe_order),
        ],
    )

    new_order = client.create_new_order(
        reseller_country,
        customer_id,
        adobe_order,
    )
    assert new_order == {
        "orderId": "adobe-order-id",
    }


def test_create_new_order_bad_request(
    requests_mocker,
    adobe_client_factory,
    adobe_config_file,
    adobe_order_factory,
    adobe_api_error_factory,
):
    """
    Test the call to Adobe API to create a new order when the response is 400 bad request.
    """
    reseller_country = adobe_config_file["accounts"][0]["resellers"][0]["country"]
    customer_id = "a-customer"

    client, _, _ = adobe_client_factory()

    error = adobe_api_error_factory("1234", "An error")

    requests_mocker.post(
        urljoin(adobe_config_file["api_base_url"], f"/v3/customers/{customer_id}/orders"),
        status=400,
        json=error,
    )

    with pytest.raises(AdobeError) as cv:
        client.create_new_order(
            reseller_country,
            customer_id,
            adobe_order_factory(order_type=ORDER_TYPE_PREVIEW),
        )

    assert repr(cv.value) == str(error)


def test_get_order(requests_mocker, adobe_client_factory, adobe_config_file):
    """
    Tests the retrieval of an order.
    """
    reseller_country = adobe_config_file["accounts"][0]["resellers"][0]["country"]
    customer_id = "a-customer"
    order_id = "an-order-id"

    client, credentials, api_token = adobe_client_factory()

    requests_mocker.get(
        urljoin(
            adobe_config_file["api_base_url"],
            f"/v3/customers/{customer_id}/orders/{order_id}",
        ),
        status=200,
        json={"an": "order"},
        match=[
            matchers.header_matcher(
                {
                    "X-Api-Key": credentials.client_id,
                    "Authorization": f"Bearer {api_token.token}",
                    "Accept": "application/json",
                    "Content-Type": "application/json",
                },
            ),
        ],
    )

    assert client.get_order(reseller_country, customer_id, order_id) == {"an": "order"}


def test_get_order_not_found(
    requests_mocker, adobe_client_factory, adobe_config_file, adobe_api_error_factory
):
    """
    Tests the retrieval of an order when it doesn't exist.
    """
    reseller_country = adobe_config_file["accounts"][0]["resellers"][0]["country"]
    customer_id = "a-customer"
    order_id = "an-order-id"

    client, _, _ = adobe_client_factory()

    requests_mocker.get(
        urljoin(
            adobe_config_file["api_base_url"],
            f"/v3/customers/{customer_id}/orders/{order_id}",
        ),
        status=404,
        json=adobe_api_error_factory("404", "Not Found"),
    )

    with pytest.raises(AdobeError) as cv:
        client.get_order(reseller_country, customer_id, order_id)

    assert cv.value.code == "404"


def test_get_subscription(requests_mocker, adobe_client_factory, adobe_config_file):
    """
    Tests the retrieval of a subscription.
    """
    reseller_country = adobe_config_file["accounts"][0]["resellers"][0]["country"]
    customer_id = "a-customer"
    sub_id = "a-sub-id"

    client, credentials, api_token = adobe_client_factory()

    requests_mocker.get(
        urljoin(
            adobe_config_file["api_base_url"],
            f"/v3/customers/{customer_id}/subscriptions/{sub_id}",
        ),
        status=200,
        json={"a": "subscription"},
        match=[
            matchers.header_matcher(
                {
                    "X-Api-Key": credentials.client_id,
                    "Authorization": f"Bearer {api_token.token}",
                    "Accept": "application/json",
                    "Content-Type": "application/json",
                },
            ),
        ],
    )

    assert client.get_subscription(reseller_country, customer_id, sub_id) == {"a": "subscription"}


def test_get_subscription_not_found(
    requests_mocker, adobe_client_factory, adobe_config_file, adobe_api_error_factory
):
    """
    Tests the retrieval of a subscription when it doesn't exist.
    """
    reseller_country = adobe_config_file["accounts"][0]["resellers"][0]["country"]
    customer_id = "a-customer"
    sub_id = "a-sub-id"

    client, _, _ = adobe_client_factory()

    requests_mocker.get(
        urljoin(
            adobe_config_file["api_base_url"],
            f"/v3/customers/{customer_id}/subscriptions/{sub_id}",
        ),
        status=404,
        json=adobe_api_error_factory("404", "Not Found"),
    )

    with pytest.raises(AdobeError) as cv:
        client.get_subscription(reseller_country, customer_id, sub_id)

    assert cv.value.code == "404"


def test_search_new_and_returned_orders_by_sku_line_number(
    requests_mocker,
    adobe_client_factory,
    adobe_config_file,
    adobe_order_factory,
    adobe_items_factory,
):
    """
    Tests the call to search the last processed order by SKU for a given
    customer.
    """
    reseller_country = adobe_config_file["accounts"][0]["resellers"][0]["country"]
    customer_id = "a-customer"
    vendor_external_id = adobe_config_file["skus_mapping"][0]["vendor_external_id"]

    client, credentials, api_token = adobe_client_factory()

    new_order_0 = adobe_order_factory(
        ORDER_TYPE_NEW,
        order_id="sku-not-contained",
        items=adobe_items_factory(offer_id="another-sku"),
        external_id="ORD-0000",
        status=STATUS_PROCESSED,
    )
    new_order_1 = adobe_order_factory(
        ORDER_TYPE_NEW,
        order_id="order-already-returned",
        external_id="ORD-1111",
        status=STATUS_PROCESSED,
    )
    new_order_2 = adobe_order_factory(
        ORDER_TYPE_NEW,
        order_id="order-to-return",
        external_id="ORD-2222",
        status=STATUS_PROCESSED,
    )

    new_order_3 = adobe_order_factory(
        ORDER_TYPE_NEW,
        order_id="another-order-to-return",
        external_id="ORD-3333",
        status=STATUS_PROCESSED,
    )

    new_order_4 = adobe_order_factory(
        ORDER_TYPE_NEW,
        order_id="order-on-inactive-customer",
        external_id="ORD-4444",
        status=STATUS_ORDER_INACTIVE_CUSTOMER,
    )

    return_order_1 = adobe_order_factory(
        ORDER_TYPE_RETURN,
        order_id="returned-order",
        reference_order_id="order-already-returned",
        external_id="ORD-1111-1",
        status=STATUS_PROCESSED,
    )

    return_order_3 = adobe_order_factory(
        ORDER_TYPE_RETURN,
        order_id="prev-returned-order",
        reference_order_id="prev-order-already-returned",
        external_id="ORD-4444-1",
        status=STATUS_PROCESSED,
    )

    requests_mocker.get(
        urljoin(
            adobe_config_file["api_base_url"],
            f"/v3/customers/{customer_id}/orders",
        ),
        status=200,
        json={
            "totalCount": 3,
            "items": [new_order_0, new_order_1, new_order_2, new_order_3, new_order_4],
            "links": {},
        },
        match=[
            matchers.header_matcher(
                {
                    "X-Api-Key": credentials.client_id,
                    "Authorization": f"Bearer {api_token.token}",
                    "Accept": "application/json",
                    "Content-Type": "application/json",
                },
            ),
            matchers.query_param_matcher(
                {
                    "order-type": ORDER_TYPE_NEW,
                    "limit": 100,
                    "offset": 0,
                },
            ),
        ],
    )

    requests_mocker.get(
        urljoin(
            adobe_config_file["api_base_url"],
            f"/v3/customers/{customer_id}/orders",
        ),
        status=200,
        json={
            "totalCount": 1,
            "items": [return_order_1],
        },
        match=[
            matchers.header_matcher(
                {
                    "X-Api-Key": credentials.client_id,
                    "Authorization": f"Bearer {api_token.token}",
                    "Accept": "application/json",
                    "Content-Type": "application/json",
                },
            ),
            matchers.query_param_matcher(
                {
                    "reference-order-id": new_order_1["orderId"],
                    "offer-id": new_order_1["lineItems"][0]["offerId"],
                    "order-type": ORDER_TYPE_RETURN,
                    "status": [STATUS_PROCESSED, STATUS_PENDING],
                    "limit": 1,
                    "offset": 0,
                },
            ),
        ],
    )

    requests_mocker.get(
        urljoin(
            adobe_config_file["api_base_url"],
            f"/v3/customers/{customer_id}/orders",
        ),
        status=200,
        json={
            "totalCount": 0,
            "items": [],
        },
        match=[
            matchers.header_matcher(
                {
                    "X-Api-Key": credentials.client_id,
                    "Authorization": f"Bearer {api_token.token}",
                    "Accept": "application/json",
                    "Content-Type": "application/json",
                },
            ),
            matchers.query_param_matcher(
                {
                    "reference-order-id": new_order_2["orderId"],
                    "offer-id": new_order_2["lineItems"][0]["offerId"],
                    "order-type": ORDER_TYPE_RETURN,
                    "status": [STATUS_PROCESSED, STATUS_PENDING],
                    "limit": 1,
                    "offset": 0,
                },
            ),
        ],
    )

    requests_mocker.get(
        urljoin(
            adobe_config_file["api_base_url"],
            f"/v3/customers/{customer_id}/orders",
        ),
        status=200,
        json={
            "totalCount": 1,
            "items": [return_order_3],
        },
        match=[
            matchers.header_matcher(
                {
                    "X-Api-Key": credentials.client_id,
                    "Authorization": f"Bearer {api_token.token}",
                    "Accept": "application/json",
                    "Content-Type": "application/json",
                },
            ),
            matchers.query_param_matcher(
                {
                    "reference-order-id": new_order_3["orderId"],
                    "offer-id": new_order_3["lineItems"][0]["offerId"],
                    "order-type": ORDER_TYPE_RETURN,
                    "status": [STATUS_PROCESSED, STATUS_PENDING],
                    "limit": 1,
                    "offset": 0,
                },
            ),
        ],
    )

    result = client.search_new_and_returned_orders_by_sku_line_number(
        reseller_country,
        customer_id,
        vendor_external_id,
        1,
    )

    assert result == [
        (new_order_1, new_order_1["lineItems"][0], return_order_1),
        (new_order_2, new_order_2["lineItems"][0], None),
        (new_order_3, new_order_3["lineItems"][0], None),
    ]


def test_search_new_and_returned_orders_by_sku_line_number_not_found(
    requests_mocker, adobe_client_factory, adobe_config_file
):
    """
    Tests the call to search the last processed order by SKU for a given
    customer when no order is found.
    """
    reseller_country = adobe_config_file["accounts"][0]["resellers"][0]["country"]
    customer_id = "a-customer"
    vendor_external_id = adobe_config_file["skus_mapping"][0]["vendor_external_id"]

    client, credentials, api_token = adobe_client_factory()

    requests_mocker.get(
        urljoin(
            adobe_config_file["api_base_url"],
            f"/v3/customers/{customer_id}/orders",
        ),
        status=200,
        json={"totalCount": 0, "items": [], "links": {}},
        match=[
            matchers.header_matcher(
                {
                    "X-Api-Key": credentials.client_id,
                    "Authorization": f"Bearer {api_token.token}",
                    "Accept": "application/json",
                    "Content-Type": "application/json",
                },
            ),
            matchers.query_param_matcher(
                {
                    "order-type": ORDER_TYPE_NEW,
                    "limit": 100,
                    "offset": 0,
                },
            ),
        ],
    )

    results = client.search_new_and_returned_orders_by_sku_line_number(
        reseller_country,
        customer_id,
        vendor_external_id,
        1,
    )

    assert results == []


def test_create_return_order(
    mocker,
    requests_mocker,
    adobe_client_factory,
    adobe_config_file,
    adobe_order_factory,
    adobe_items_factory,
):
    """
    Test the call to Adobe API to create a return order.
    """
    mocker.patch(
        "adobe_vipm.adobe.client.uuid4",
        return_value="uuid-1",
    )
    reseller_country = adobe_config_file["accounts"][0]["resellers"][0]["country"]
    customer_id = "a-customer"

    client, credentials, api_token = adobe_client_factory()

    returning_order = adobe_order_factory(
        ORDER_TYPE_NEW,
        external_id="ORD-1234",
        order_id="returning-order-id",
        status=STATUS_PROCESSED,
    )

    returning_item = returning_order["lineItems"][0]

    expected_external_id = (
        f"{returning_order['externalReferenceId']}-{returning_item['extLineItemNumber']}"
    )

    expected_body = adobe_order_factory(
        ORDER_TYPE_RETURN,
        reference_order_id=returning_order["orderId"],
        external_id=expected_external_id,
        items=adobe_items_factory(),
    )

    requests_mocker.post(
        urljoin(adobe_config_file["api_base_url"], f"/v3/customers/{customer_id}/orders"),
        status=202,
        json={
            "orderId": "adobe-order-id",
        },
        match=[
            matchers.header_matcher(
                {
                    "X-Api-Key": credentials.client_id,
                    "Authorization": f"Bearer {api_token.token}",
                    "Accept": "application/json",
                    "Content-Type": "application/json",
                    "X-Request-Id": "uuid-1",
                    "x-correlation-id": expected_external_id,
                },
            ),
            matchers.json_params_matcher(expected_body),
        ],
    )

    return_order = client.create_return_order(
        reseller_country,
        customer_id,
        returning_order,
        returning_item,
    )
    assert return_order == {
        "orderId": "adobe-order-id",
    }


def test_create_return_order_bad_request(
    requests_mocker,
    adobe_client_factory,
    adobe_config_file,
    adobe_order_factory,
    adobe_api_error_factory,
):
    """
    Test the call to Adobe API to create a return order when the response is 400 bad request.
    """
    reseller_country = adobe_config_file["accounts"][0]["resellers"][0]["country"]
    customer_id = "a-customer"

    client, _, _ = adobe_client_factory()

    error = adobe_api_error_factory("1234", "An error")

    requests_mocker.post(
        urljoin(adobe_config_file["api_base_url"], f"/v3/customers/{customer_id}/orders"),
        status=400,
        json=error,
    )
    returning_order = adobe_order_factory(ORDER_TYPE_NEW, status=STATUS_PROCESSED)

    with pytest.raises(AdobeError) as cv:
        client.create_return_order(
            reseller_country,
            customer_id,
            returning_order,
            returning_order["lineItems"][0],
        )

    assert repr(cv.value) == str(error)


@pytest.mark.parametrize(
    "update_params",
    [
        {"auto_renewal": True},
        {"auto_renewal": False},
        {"auto_renewal": True, "quantity": 3},
        {"auto_renewal": False, "quantity": 6},
        {"quantity": 3},
        {"quantity": 6},
    ],
)
def test_update_subscription(
    requests_mocker, adobe_client_factory, adobe_config_file, update_params
):
    """
    Tests the update of a subscription.
    """
    reseller_country = adobe_config_file["accounts"][0]["resellers"][0]["country"]
    customer_id = "a-customer"
    sub_id = "a-sub-id"

    client, credentials, api_token = adobe_client_factory()

    body_to_match = {
        "autoRenewal": {
            "enabled": update_params.get("auto_renewal", True),
        },
    }
    if "quantity" in update_params:
        body_to_match["autoRenewal"]["quantity"] = update_params["quantity"]

    requests_mocker.patch(
        urljoin(
            adobe_config_file["api_base_url"],
            f"/v3/customers/{customer_id}/subscriptions/{sub_id}",
        ),
        status=200,
        json={"a": "subscription"},
        match=[
            matchers.header_matcher(
                {
                    "X-Api-Key": credentials.client_id,
                    "Authorization": f"Bearer {api_token.token}",
                    "Accept": "application/json",
                    "Content-Type": "application/json",
                },
            ),
            matchers.json_params_matcher(body_to_match),
        ],
    )

    assert client.update_subscription(
        reseller_country,
        customer_id,
        sub_id,
        **update_params,
    ) == {"a": "subscription"}


def test_update_subscription_not_found(
    requests_mocker, adobe_client_factory, adobe_config_file, adobe_api_error_factory
):
    """
    Tests the update of a subscription when it doesn't exist.
    """
    reseller_country = adobe_config_file["accounts"][0]["resellers"][0]["country"]
    customer_id = "a-customer"
    sub_id = "a-sub-id"

    client, _, _ = adobe_client_factory()

    requests_mocker.patch(
        urljoin(
            adobe_config_file["api_base_url"],
            f"/v3/customers/{customer_id}/subscriptions/{sub_id}",
        ),
        status=404,
        json=adobe_api_error_factory("404", "Not Found"),
    )

    with pytest.raises(AdobeError) as cv:
        client.update_subscription(reseller_country, customer_id, sub_id, quantity=10)

    assert cv.value.code == "404"


def test_get_auth_token(requests_mocker, mock_adobe_config, adobe_config_file):
    """
    Test issuing of authentication token.
    """
    credentials = Credentials(
        "client_id",
        "client_secret",
        "NA",
        "distributor_id",
    )

    requests_mocker.post(
        adobe_config_file["authentication_endpoint_url"],
        json={
            "access_token": "an-access-token",
            "expires_in": 83000,
        },
        match=[
            matchers.urlencoded_params_matcher(
                {
                    "grant_type": "client_credentials",
                    "client_id": credentials.client_id,
                    "client_secret": credentials.client_secret,
                    "scope": ",".join(adobe_config_file["scopes"]),
                },
            ),
        ],
    )

    client = AdobeClient()
    with freeze_time("2024-01-01 12:00:00"):
        token = client._get_auth_token(credentials)
        assert isinstance(token, APIToken)
        assert token.token == "an-access-token"
        assert token.expires == datetime.now() + timedelta(seconds=83000 - 180)
        assert client._token_cache[credentials] == token


def test_get_auth_token_error(requests_mocker, mock_adobe_config, adobe_config_file):
    """
    Test error issuing of authentication token.
    """
    credentials = Credentials(
        "client_id",
        "client_secret",
        "NA",
        "distributor_id",
    )

    requests_mocker.post(
        adobe_config_file["authentication_endpoint_url"],
        status=403,
    )

    client = AdobeClient()
    with pytest.raises(requests.HTTPError):
        client._get_auth_token(credentials)


def test_get_adobe_client(mocker):
    """
    Test AdobeClient is cached per process.
    """
    mocked_client = mocker.MagicMock()
    mocked_client_constructor = mocker.patch(
        "adobe_vipm.adobe.client.AdobeClient",
        return_value=mocked_client,
    )
    get_adobe_client()
    get_adobe_client()
    assert mocked_client_constructor.call_count == 1
    from adobe_vipm.adobe import client

    assert client._ADOBE_CLIENT == mocked_client
