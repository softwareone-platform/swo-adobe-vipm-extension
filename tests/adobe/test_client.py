import copy
from datetime import datetime, timedelta
from urllib.parse import urljoin

import pytest
import requests
from freezegun import freeze_time
from responses import matchers

from adobe_vipm.adobe.client import AdobeClient, AdobeError, get_adobe_client
from adobe_vipm.adobe.dataclasses import APIToken, Credentials


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

    customer_id = client.create_customer_account(
        reseller_country, "external_id", customer_data
    )
    assert customer_id == "A-customer-id"


def test_create_customer_account_bad_request(
    requests_mocker,
    adobe_config_file,
    customer_data,
    adobe_error_factory,
    adobe_client_factory,
):
    """
    Test the call to Adobe API to create a customer when the response is 400 bad request.
    """
    reseller_country = adobe_config_file["accounts"][0]["resellers"][0]["country"]

    client, _, _ = adobe_client_factory()

    error = adobe_error_factory("1234", "An error")

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
    customer_id = "a-customer"

    client, credentials, api_token = adobe_client_factory()

    requests_mocker.post(
        urljoin(
            adobe_config_file["api_base_url"], f"/v3/customers/{customer_id}/orders"
        ),
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
                            "offerId": adobe_config_file["skus_mapping"][0][
                                "default_sku"
                            ],
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
    adobe_error_factory,
    adobe_client_factory,
    order,
):
    """
    Test the call to Adobe API to create a preview order when the response is 400 bad request.
    """
    reseller_country = adobe_config_file["accounts"][0]["resellers"][0]["country"]
    customer_id = "a-customer"

    client, _, _ = adobe_client_factory()

    error = adobe_error_factory("1234", "An error")

    requests_mocker.post(
        urljoin(
            adobe_config_file["api_base_url"], f"/v3/customers/{customer_id}/orders"
        ),
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
    adobe_preview_order,
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

    expected_body = copy.deepcopy(adobe_preview_order)
    expected_body["orderType"] = "NEW"

    requests_mocker.post(
        urljoin(
            adobe_config_file["api_base_url"], f"/v3/customers/{customer_id}/orders"
        ),
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
                    "x-correlation-id": "order_id",
                },
            ),
            matchers.json_params_matcher(expected_body),
        ],
    )

    new_order = client.create_new_order(
        reseller_country,
        customer_id,
        "order_id",
        adobe_preview_order,
    )
    assert new_order == {
        "orderId": "adobe-order-id",
    }


def test_create_new_order_bad_request(
    requests_mocker,
    adobe_client_factory,
    adobe_config_file,
    adobe_preview_order,
    adobe_error_factory,
):
    """
    Test the call to Adobe API to create a new order when the response is 400 bad request.
    """
    reseller_country = adobe_config_file["accounts"][0]["resellers"][0]["country"]
    customer_id = "a-customer"

    client, _, _ = adobe_client_factory()

    error = adobe_error_factory("1234", "An error")

    requests_mocker.post(
        urljoin(
            adobe_config_file["api_base_url"], f"/v3/customers/{customer_id}/orders"
        ),
        status=400,
        json=error,
    )

    with pytest.raises(AdobeError) as cv:
        client.create_new_order(
            reseller_country,
            customer_id,
            "order_id",
            adobe_preview_order,
        )

    assert repr(cv.value) == str(error)


def test_get_order(requests_mocker, adobe_client_factory, adobe_config_file):
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
    requests_mocker, adobe_client_factory, adobe_config_file, adobe_error_factory
):
    reseller_country = adobe_config_file["accounts"][0]["resellers"][0]["country"]
    customer_id = "a-customer"
    order_id = "an-order-id"

    client, credentials, api_token = adobe_client_factory()

    requests_mocker.get(
        urljoin(
            adobe_config_file["api_base_url"],
            f"/v3/customers/{customer_id}/orders/{order_id}",
        ),
        status=404,
        json=adobe_error_factory("404", "Not Found"),
    )

    with pytest.raises(AdobeError) as cv:
        client.get_order(reseller_country, customer_id, order_id)

    assert cv.value.code == "404"


def test_get_subscription(requests_mocker, adobe_client_factory, adobe_config_file):
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

    assert client.get_subscription(reseller_country, customer_id, sub_id) == {
        "a": "subscription"
    }


def test_get_subscription_not_found(
    requests_mocker, adobe_client_factory, adobe_config_file, adobe_error_factory
):
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
        json=adobe_error_factory("404", "Not Found"),
    )

    with pytest.raises(AdobeError) as cv:
        client.get_subscription(reseller_country, customer_id, sub_id)

    assert cv.value.code == "404"


def test_get_auth_token(requests_mocker, mock_adobe_config, adobe_config_file):
    """
    Test issuing of authentication token.
    """
    credentials = Credentials(
        "client_id",
        "client_secret",
        "NA",
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
