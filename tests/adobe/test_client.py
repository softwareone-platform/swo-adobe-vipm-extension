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
                        "companyName": reseller_data["CompanyName"],
                        "preferredLanguage": reseller_data["PreferredLanguage"],
                        "address": {
                            "country": reseller_data["Address"]["country"],
                            "region": reseller_data["Address"]["state"],
                            "city": reseller_data["Address"]["city"],
                            "addressLine1": reseller_data["Address"]["addressLine1"],
                            "addressLine2": reseller_data["Address"]["addressLine2"],
                            "postalCode": reseller_data["Address"]["postCode"],
                            "phoneNumber": reseller_data["Contact"]["phone"],
                        },
                        "contacts": [
                            {
                                "firstName": reseller_data["Contact"]["firstName"],
                                "lastName": reseller_data["Contact"]["lastName"],
                                "email": reseller_data["Contact"]["email"],
                                "phoneNumber": reseller_data["Contact"]["phone"],
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
                        "companyName": customer_data["CompanyName"],
                        "preferredLanguage": customer_data["PreferredLanguage"],
                        "address": {
                            "country": customer_data["Address"]["country"],
                            "region": customer_data["Address"]["state"],
                            "city": customer_data["Address"]["city"],
                            "addressLine1": customer_data["Address"]["addressLine1"],
                            "addressLine2": customer_data["Address"]["addressLine2"],
                            "postalCode": customer_data["Address"]["postCode"],
                            "phoneNumber": customer_data["Contact"]["phone"],
                        },
                        "contacts": [
                            {
                                "firstName": customer_data["Contact"]["firstName"],
                                "lastName": customer_data["Contact"]["lastName"],
                                "email": customer_data["Contact"]["email"],
                                "phoneNumber": customer_data["Contact"]["phone"],
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


def test_create_preview_order(
    mocker,
    requests_mocker,
    adobe_config_file,
    order,
    adobe_client_factory,
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
                            "extLineItemNumber": order["items"][0]["lineNumber"],
                            "offerId": adobe_full_sku,
                            "quantity": order["items"][0]["quantity"],
                        },
                    ],
                },
            ),
        ],
    )

    preview_order = client.create_preview_order(
        reseller_country,
        customer_id,
        order,
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
            order,
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


def test_search_last_order_by_sku(requests_mocker, adobe_client_factory, adobe_config_file):
    """
    Tests the call to search the last processed order by SKU for a given
    customer.
    """
    reseller_country = adobe_config_file["accounts"][0]["resellers"][0]["country"]
    customer_id = "a-customer"
    product_item_id = adobe_config_file["skus_mapping"][0]["product_item_id"]
    sku = adobe_config_file["skus_mapping"][0]["sku"]

    client, credentials, api_token = adobe_client_factory()

    requests_mocker.get(
        urljoin(
            adobe_config_file["api_base_url"],
            f"/v3/customers/{customer_id}/orders",
        ),
        status=200,
        json={"count": 1, "items": [{"an": "order"}]},
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
                    "offer-id": sku,
                    "order-type": "NEW",
                    "status": STATUS_PROCESSED,
                },
            ),
        ],
    )

    assert client.search_last_order_by_sku(reseller_country, customer_id, product_item_id) == {
        "an": "order"
    }


def test_search_last_order_by_sku_not_found(
    requests_mocker, adobe_client_factory, adobe_config_file
):
    """
    Tests the call to search the last processed order by SKU for a given
    customer when no order is found.
    """
    reseller_country = adobe_config_file["accounts"][0]["resellers"][0]["country"]
    customer_id = "a-customer"
    product_item_id = adobe_config_file["skus_mapping"][0]["product_item_id"]
    sku = adobe_config_file["skus_mapping"][0]["sku"]

    client, credentials, api_token = adobe_client_factory()

    requests_mocker.get(
        urljoin(
            adobe_config_file["api_base_url"],
            f"/v3/customers/{customer_id}/orders",
        ),
        status=200,
        json={"count": 0, "items": []},
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
                    "offer-id": sku,
                    "order-type": "NEW",
                    "status": STATUS_PROCESSED,
                },
            ),
        ],
    )

    assert client.search_last_order_by_sku(reseller_country, customer_id, product_item_id) is None


def test_create_return_order(
    mocker,
    requests_mocker,
    adobe_client_factory,
    adobe_config_file,
    adobe_order_factory,
    adobe_items_factory,
    order_factory,
    items_factory,
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

    order = order_factory(
        items=items_factory(
            old_quantity=10,
            quantity=5,
        )
    )

    expected_body = adobe_order_factory(
        ORDER_TYPE_RETURN,
        reference_order_id="prev-order",
        external_id=order["id"],
        items=adobe_items_factory(quantity=10),
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
                    "x-correlation-id": f"{order['id']}-ret",
                },
            ),
            matchers.json_params_matcher(expected_body),
        ],
    )

    return_order = client.create_return_order(
        reseller_country,
        customer_id,
        "prev-order",
        order,
        order["items"][0],
    )
    assert return_order == {
        "orderId": "adobe-order-id",
    }


def test_create_return_order_bad_request(
    requests_mocker,
    adobe_client_factory,
    adobe_config_file,
    order_factory,
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
    order = order_factory()
    with pytest.raises(AdobeError) as cv:
        client.create_return_order(
            reseller_country,
            customer_id,
            "adobe_order_id",
            order,
            order["items"][0],
        )

    assert repr(cv.value) == str(error)


def test_search_last_return_order_by_order(
    requests_mocker, adobe_client_factory, adobe_config_file
):
    """
    Tests the call to search the last processed return order by the returned
    order id for a given customer.
    """
    reseller_country = adobe_config_file["accounts"][0]["resellers"][0]["country"]
    customer_id = "a-customer"
    adobe_order_id = "an-order-id"

    client, credentials, api_token = adobe_client_factory()

    requests_mocker.get(
        urljoin(
            adobe_config_file["api_base_url"],
            f"/v3/customers/{customer_id}/orders",
        ),
        status=200,
        json={"count": 1, "items": [{"an": "order"}]},
        match=[
            matchers.header_matcher(
                {
                    "X-Api-Key": credentials.client_id,
                    "Authorization": f"Bearer {api_token.token}",
                    "Accept": "application/json",
                    "Content-Type": "application/json",
                },
            ),
            matchers.query_string_matcher(
                "reference-order-id=an-order-id&order-type=RETURN"
                f"&status={STATUS_PROCESSED}&status={STATUS_PENDING}",
            ),
        ],
    )

    assert client.search_last_return_order_by_order(
        reseller_country,
        customer_id,
        adobe_order_id,
    ) == {"an": "order"}


def test_search_last_return_order_by_order_not_found(
    requests_mocker, adobe_client_factory, adobe_config_file
):
    """
    Tests the call to search the last processed return order by the returned
    order id for a given customer when no order is found.
    """
    reseller_country = adobe_config_file["accounts"][0]["resellers"][0]["country"]
    customer_id = "a-customer"
    adobe_order_id = "an-order-id"

    client, credentials, api_token = adobe_client_factory()

    requests_mocker.get(
        urljoin(
            adobe_config_file["api_base_url"],
            f"/v3/customers/{customer_id}/orders",
        ),
        status=200,
        json={"count": 0, "items": []},
        match=[
            matchers.header_matcher(
                {
                    "X-Api-Key": credentials.client_id,
                    "Authorization": f"Bearer {api_token.token}",
                    "Accept": "application/json",
                    "Content-Type": "application/json",
                },
            ),
            matchers.query_string_matcher(
                "reference-order-id=an-order-id&order-type=RETURN&status=1000&status=1002",
            ),
        ],
    )

    assert (
        client.search_last_return_order_by_order(reseller_country, customer_id, adobe_order_id)
        is None
    )


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
