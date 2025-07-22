import copy
import datetime as dt
import json
from hashlib import sha256
from urllib.parse import urljoin

import pytest
import requests
from freezegun import freeze_time
from responses import matchers

from adobe_vipm.adobe import client as adobe_client
from adobe_vipm.adobe.config import REQUIRED_API_SCOPES
from adobe_vipm.adobe.constants import (
    ORDER_TYPE_NEW,
    ORDER_TYPE_PREVIEW,
    ORDER_TYPE_PREVIEW_RENEWAL,
    ORDER_TYPE_RENEWAL,
    ORDER_TYPE_RETURN,
    AdobeStatus,
)
from adobe_vipm.adobe.dataclasses import APIToken, Authorization, ReturnableOrderInfo
from adobe_vipm.adobe.errors import AdobeError, AdobeProductNotFoundError
from adobe_vipm.adobe.utils import join_phone_number, to_adobe_line_id
from adobe_vipm.flows.constants import Param


def test_create_reseller_account(
    mocker,
    settings,
    requests_mocker,
    adobe_authorizations_file,
    reseller_data,
    adobe_client_factory,
):
    mocker.patch(
        "adobe_vipm.adobe.client.uuid4",
        return_value="uuid-1",
    )
    distributor_id = adobe_authorizations_file["authorizations"][0]["distributor_id"]
    authorization_uk = adobe_authorizations_file["authorizations"][0]["authorization_uk"]

    client, authorization, api_token = adobe_client_factory()
    payload = {
        "externalReferenceId": "external_id",
        "distributorId": distributor_id,
        "companyProfile": {
            "companyName": reseller_data["companyName"],
            "preferredLanguage": "en-US",
            "address": {
                "country": reseller_data["address"]["country"],
                "region": reseller_data["address"]["state"],
                "city": reseller_data["address"]["city"],
                "addressLine1": reseller_data["address"]["addressLine1"],
                "addressLine2": reseller_data["address"]["addressLine2"],
                "postalCode": reseller_data["address"]["postCode"],
                "phoneNumber": join_phone_number(reseller_data["contact"]["phone"]),
            },
            "contacts": [
                {
                    "firstName": reseller_data["contact"]["firstName"],
                    "lastName": reseller_data["contact"]["lastName"],
                    "email": reseller_data["contact"]["email"],
                    "phoneNumber": join_phone_number(reseller_data["contact"]["phone"]),
                }
            ],
        },
    }
    correlation_id = sha256(json.dumps(payload).encode()).hexdigest()

    requests_mocker.post(
        urljoin(settings.EXTENSION_CONFIG["ADOBE_API_BASE_URL"], "/v3/resellers"),
        status=201,
        json={
            "resellerId": "a-reseller-id",
        },
        match=[
            matchers.header_matcher(
                {
                    "X-Api-Key": authorization.client_id,
                    "Authorization": f"Bearer {api_token.token}",
                    "Accept": "application/json",
                    "Content-Type": "application/json",
                    "X-Request-Id": "uuid-1",
                    "x-correlation-id": correlation_id,
                },
            ),
            matchers.json_params_matcher(payload),
        ],
    )

    reseller_id = client.create_reseller_account(authorization_uk, "external_id", reseller_data)
    assert reseller_id == "a-reseller-id"


def test_create_reseller_account_bad_request(
    requests_mocker,
    settings,
    adobe_authorizations_file,
    reseller_data,
    adobe_api_error_factory,
    adobe_client_factory,
):
    authorization_uk = adobe_authorizations_file["authorizations"][0]["authorization_uk"]

    client, _, _ = adobe_client_factory()

    error = adobe_api_error_factory("1234", "An error")

    requests_mocker.post(
        urljoin(settings.EXTENSION_CONFIG["ADOBE_API_BASE_URL"], "/v3/resellers"),
        status=400,
        json=error,
    )

    with pytest.raises(AdobeError) as cv:
        client.create_reseller_account(authorization_uk, "external_id", reseller_data)

    assert repr(cv.value) == str(error)


def test_create_customer_account(
    mocker,
    settings,
    requests_mocker,
    adobe_authorizations_file,
    customer_data,
    adobe_client_factory,
):
    mocker.patch(
        "adobe_vipm.adobe.client.uuid4",
        return_value="uuid-1",
    )
    seller_id = adobe_authorizations_file["authorizations"][0]["resellers"][0]["seller_id"]
    reseller_id = adobe_authorizations_file["authorizations"][0]["resellers"][0]["id"]
    authorization_uk = adobe_authorizations_file["authorizations"][0]["authorization_uk"]

    client, authorization, api_token = adobe_client_factory()

    company_name = f"{customer_data['companyName']} (external_id)"

    payload = {
        "resellerId": reseller_id,
        "externalReferenceId": "external_id",
        "companyProfile": {
            "companyName": company_name,
            "preferredLanguage": "en-US",
            "marketSegment": "COM",
            "address": {
                "country": customer_data["address"]["country"],
                "region": customer_data["address"]["state"],
                "city": customer_data["address"]["city"],
                "addressLine1": customer_data["address"]["addressLine1"],
                "addressLine2": customer_data["address"]["addressLine2"],
                "postalCode": customer_data["address"]["postCode"],
                "phoneNumber": join_phone_number(customer_data["contact"]["phone"]),
            },
            "contacts": [
                {
                    "firstName": customer_data["contact"]["firstName"],
                    "lastName": customer_data["contact"]["lastName"],
                    "email": customer_data["contact"]["email"],
                    "phoneNumber": join_phone_number(customer_data["contact"]["phone"]),
                }
            ],
        },
    }
    correlation_id = sha256(json.dumps(payload).encode()).hexdigest()
    requests_mocker.post(
        urljoin(settings.EXTENSION_CONFIG["ADOBE_API_BASE_URL"], "/v3/customers"),
        status=201,
        json={
            "customerId": "A-customer-id",
        },
        match=[
            matchers.header_matcher(
                {
                    "X-Api-Key": authorization.client_id,
                    "Authorization": f"Bearer {api_token.token}",
                    "Accept": "application/json",
                    "Content-Type": "application/json",
                    "X-Request-Id": "uuid-1",
                    "x-correlation-id": correlation_id,
                },
            ),
            matchers.json_params_matcher(payload),
        ],
    )

    customer_id = client.create_customer_account(
        authorization_uk, seller_id, "external_id", "COM", customer_data
    )
    assert customer_id == {"customerId": "A-customer-id"}


def test_create_customer_account_bad_request(
    requests_mocker,
    settings,
    adobe_authorizations_file,
    customer_data,
    adobe_api_error_factory,
    adobe_client_factory,
):
    authorization_uk = adobe_authorizations_file["authorizations"][0]["authorization_uk"]
    seller_id = adobe_authorizations_file["authorizations"][0]["resellers"][0]["seller_id"]

    client, _, _ = adobe_client_factory()

    error = adobe_api_error_factory("1234", "An error")

    requests_mocker.post(
        urljoin(settings.EXTENSION_CONFIG["ADOBE_API_BASE_URL"], "/v3/customers"),
        status=400,
        json=error,
    )

    with pytest.raises(AdobeError) as cv:
        client.create_customer_account(
            authorization_uk, seller_id, "external_id", "GOV", customer_data
        )

    assert repr(cv.value) == str(error)


@pytest.mark.parametrize(
    (
        "old_quantity",
        "quantity",
        "current_quantity",
        "renewal_quantity",
        "expected_quantity",
    ),
    [
        pytest.param(5, 10, 5, 5, 5, id="upsize_only"),
        pytest.param(8, 12, 10, 8, 2, id="upsize_after_downsize"),
    ],
)
def test_create_preview_order_upsize(
    mocker,
    settings,
    requests_mocker,
    adobe_config_file,
    adobe_authorizations_file,
    adobe_subscription_factory,
    order_factory,
    lines_factory,
    adobe_client_factory,
    mock_get_adobe_product_by_marketplace_sku,
    old_quantity,
    quantity,
    current_quantity,
    renewal_quantity,
    expected_quantity,
):
    mocker.patch(
        "adobe_vipm.adobe.mixins.order.get_adobe_product_by_marketplace_sku",
        side_effect=mock_get_adobe_product_by_marketplace_sku,
    )

    mocker.patch(
        "adobe_vipm.adobe.client.uuid4",
        side_effect=["uuid-1", "uuid-2", "uuid-3", "uuid-4"],
    )
    authorization_uk = adobe_authorizations_file["authorizations"][0]["authorization_uk"]
    adobe_full_sku = adobe_config_file["skus_mapping"][0]["sku"]
    customer_id = "a-customer"
    deployment_id = "a_deployment_id"

    client, authorization, api_token = adobe_client_factory()

    order = order_factory(lines=lines_factory(old_quantity=old_quantity, quantity=quantity))
    order["lines"][0]["item"]["externalIds"] = {"vendor": "65304578CA"}
    adobe_subscription = adobe_subscription_factory(
        current_quantity=current_quantity,
        renewal_quantity=renewal_quantity,
    )

    requests_mocker.get(
        urljoin(
            settings.EXTENSION_CONFIG["ADOBE_API_BASE_URL"],
            f"/v3/customers/{customer_id}/subscriptions",
        ),
        status=200,
        json={"items": [adobe_subscription]},
    )

    requests_mocker.post(
        urljoin(
            settings.EXTENSION_CONFIG["ADOBE_API_BASE_URL"],
            f"/v3/customers/{customer_id}/orders",
        ),
        status=200,
        json={
            "orderId": "adobe-order-id",
        },
        match=[
            matchers.header_matcher(
                {
                    "X-Api-Key": authorization.client_id,
                    "Authorization": f"Bearer {api_token.token}",
                    "Accept": "application/json",
                    "Content-Type": "application/json",
                    "X-Request-Id": "uuid-3",
                    "x-correlation-id": "uuid-4",
                },
            ),
            matchers.json_params_matcher(
                {
                    "externalReferenceId": order["id"],
                    "orderType": "PREVIEW",
                    "lineItems": [
                        {
                            "extLineItemNumber": to_adobe_line_id(order["lines"][0]["id"]),
                            "offerId": adobe_full_sku,
                            "quantity": expected_quantity,
                            "deploymentId": deployment_id,
                            "currencyCode": "USD",
                        },
                    ],
                },
            ),
        ],
    )

    preview_order = client.create_preview_order(
        authorization_uk,
        customer_id,
        order["id"],
        order["lines"],
        [],
        deployment_id,
    )
    assert preview_order == {
        "orderId": "adobe-order-id",
    }


def test_create_preview_order_upsize_product_not_found(
    mocker,
    settings,
    requests_mocker,
    adobe_config_file,
    adobe_authorizations_file,
    adobe_subscription_factory,
    order_factory,
    lines_factory,
    adobe_client_factory,
    mock_get_adobe_product_by_marketplace_sku,
):
    mocker.patch(
        "adobe_vipm.adobe.mixins.order.get_adobe_product_by_marketplace_sku",
        side_effect=mock_get_adobe_product_by_marketplace_sku,
    )

    mocker.patch(
        "adobe_vipm.adobe.client.uuid4",
        side_effect=["uuid-1", "uuid-2", "uuid-3", "uuid-4"],
    )
    authorization_uk = adobe_authorizations_file["authorizations"][0]["authorization_uk"]
    customer_id = "a-customer"
    deployment_id = "a_deployment_id"

    client, _, _ = adobe_client_factory()

    # Create an order with a non-existent product SKU
    order = order_factory(lines=lines_factory(old_quantity=5, quantity=10))
    order["lines"][0]["item"]["externalIds"] = {"vendor": "NONEXISTENT-SKU"}

    # Mock the subscriptions endpoint to return an empty list
    requests_mocker.get(
        urljoin(
            settings.EXTENSION_CONFIG["ADOBE_API_BASE_URL"],
            f"/v3/customers/{customer_id}/subscriptions",
        ),
        status=200,
        json={"items": []},
    )

    with pytest.raises(AdobeProductNotFoundError) as exc_info:
        client.create_preview_order(
            authorization_uk,
            customer_id,
            order["id"],
            order["lines"],
            [],
            deployment_id,
        )

    assert str(exc_info.value) == (
        "Product NONEXISTENT-SKU not found in Adobe to make the upsize."
        "This could be because the product is not available for this customer "
        "or the subscription has been terminated."
    )


def test_create_preview_order_upsize_after_downsize_lower(
    mocker,
    settings,
    requests_mocker,
    adobe_config_file,
    adobe_authorizations_file,
    adobe_subscription_factory,
    order_factory,
    lines_factory,
    adobe_client_factory,
    mock_get_adobe_product_by_marketplace_sku,
):
    mocker.patch(
        "adobe_vipm.adobe.mixins.order.get_adobe_product_by_marketplace_sku",
        side_effect=mock_get_adobe_product_by_marketplace_sku,
    )

    mocker.patch(
        "adobe_vipm.adobe.client.uuid4",
        side_effect=["uuid-1", "uuid-2", "uuid-3", "uuid-4"],
    )
    authorization_uk = adobe_authorizations_file["authorizations"][0]["authorization_uk"]
    customer_id = "a-customer"
    deployment_id = "a_deployment_id"

    client, _, _ = adobe_client_factory()

    order = order_factory(lines=lines_factory(old_quantity=8, quantity=9))
    order["lines"][0]["item"]["externalIds"] = {"vendor": "65304578CA"}
    adobe_subscription = adobe_subscription_factory(
        current_quantity=10,
        renewal_quantity=8,
    )

    requests_mocker.get(
        urljoin(
            settings.EXTENSION_CONFIG["ADOBE_API_BASE_URL"],
            f"/v3/customers/{customer_id}/subscriptions",
        ),
        status=200,
        json={"items": [adobe_subscription]},
    )

    preview_order = client.create_preview_order(
        authorization_uk,
        customer_id,
        order["id"],
        order["lines"],
        [],
        deployment_id,
    )
    assert preview_order is None


def test_create_preview_newlines(
    mocker,
    settings,
    requests_mocker,
    adobe_config_file,
    adobe_authorizations_file,
    order_factory,
    lines_factory,
    adobe_client_factory,
    mock_get_adobe_product_by_marketplace_sku,
):
    mocker.patch(
        "adobe_vipm.adobe.mixins.order.get_adobe_product_by_marketplace_sku",
        side_effect=mock_get_adobe_product_by_marketplace_sku,
    )

    mocker.patch(
        "adobe_vipm.adobe.client.uuid4",
        side_effect=["uuid-1", "uuid-2"],
    )
    authorization_uk = adobe_authorizations_file["authorizations"][0]["authorization_uk"]
    adobe_full_sku = adobe_config_file["skus_mapping"][0]["sku"]
    customer_id = "a-customer"
    deployment_id = "a_deployment_id"

    client, authorization, api_token = adobe_client_factory()

    order = order_factory(lines=lines_factory(old_quantity=0, quantity=5))
    order["lines"][0]["item"]["externalIds"] = {"vendor": "65304578CA"}

    requests_mocker.post(
        urljoin(
            settings.EXTENSION_CONFIG["ADOBE_API_BASE_URL"],
            f"/v3/customers/{customer_id}/orders",
        ),
        status=200,
        json={
            "orderId": "adobe-order-id",
        },
        match=[
            matchers.header_matcher(
                {
                    "X-Api-Key": authorization.client_id,
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
                    "orderType": "PREVIEW",
                    "lineItems": [
                        {
                            "extLineItemNumber": to_adobe_line_id(order["lines"][0]["id"]),
                            "offerId": adobe_full_sku,
                            "quantity": 5,
                            "deploymentId": deployment_id,
                            "currencyCode": "USD",
                        },
                    ],
                },
            ),
        ],
    )

    preview_order = client.create_preview_order(
        authorization_uk,
        customer_id,
        order["id"],
        [],
        order["lines"],
        deployment_id,
    )
    assert preview_order == {
        "orderId": "adobe-order-id",
    }


def test_create_preview_newlines_wo_deployment(
    mocker,
    settings,
    requests_mocker,
    adobe_config_file,
    adobe_authorizations_file,
    order_factory,
    lines_factory,
    adobe_client_factory,
    mock_get_adobe_product_by_marketplace_sku,
):
    mocker.patch(
        "adobe_vipm.adobe.mixins.order.get_adobe_product_by_marketplace_sku",
        side_effect=mock_get_adobe_product_by_marketplace_sku,
    )

    mocker.patch(
        "adobe_vipm.adobe.client.uuid4",
        side_effect=["uuid-1", "uuid-2"],
    )
    authorization_uk = adobe_authorizations_file["authorizations"][0]["authorization_uk"]
    adobe_full_sku = adobe_config_file["skus_mapping"][0]["sku"]
    customer_id = "a-customer"

    client, authorization, api_token = adobe_client_factory()

    order = order_factory(lines=lines_factory(old_quantity=0, quantity=5))
    order["lines"][0]["item"]["externalIds"] = {"vendor": "65304578CA"}

    requests_mocker.post(
        urljoin(
            settings.EXTENSION_CONFIG["ADOBE_API_BASE_URL"],
            f"/v3/customers/{customer_id}/orders",
        ),
        status=200,
        json={
            "orderId": "adobe-order-id",
        },
        match=[
            matchers.header_matcher(
                {
                    "X-Api-Key": authorization.client_id,
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
                    "orderType": "PREVIEW",
                    "lineItems": [
                        {
                            "extLineItemNumber": to_adobe_line_id(order["lines"][0]["id"]),
                            "offerId": adobe_full_sku,
                            "quantity": 5,
                        },
                    ],
                    "currencyCode": "USD",
                },
            ),
        ],
    )

    preview_order = client.create_preview_order(
        authorization_uk,
        customer_id,
        order["id"],
        [],
        order["lines"],
    )
    assert preview_order == {
        "orderId": "adobe-order-id",
    }


def test_create_preview_order_bad_request(
    mocker,
    requests_mocker,
    settings,
    adobe_authorizations_file,
    adobe_api_error_factory,
    adobe_client_factory,
    order,
    mock_get_adobe_product_by_marketplace_sku,
):
    mocker.patch(
        "adobe_vipm.adobe.mixins.order.get_adobe_product_by_marketplace_sku",
        side_effect=mock_get_adobe_product_by_marketplace_sku,
    )

    order["lines"][0]["item"]["externalIds"] = {"vendor": "65304578CA"}
    authorization_uk = adobe_authorizations_file["authorizations"][0]["authorization_uk"]
    customer_id = "a-customer"
    deployment_id = "a_deployment_id"

    client, _, _ = adobe_client_factory()

    error = adobe_api_error_factory("1234", "An error")

    requests_mocker.post(
        urljoin(
            settings.EXTENSION_CONFIG["ADOBE_API_BASE_URL"],
            f"/v3/customers/{customer_id}/orders",
        ),
        status=400,
        json=error,
    )

    with pytest.raises(AdobeError) as cv:
        client.create_preview_order(
            authorization_uk,
            customer_id,
            order["id"],
            [],
            order["lines"],
            deployment_id=deployment_id,
        )

    assert repr(cv.value) == str(error)


def test_create_new_order(
    mocker,
    settings,
    requests_mocker,
    adobe_client_factory,
    adobe_authorizations_file,
    adobe_order_factory,
):
    mocker.patch(
        "adobe_vipm.adobe.client.uuid4",
        return_value="uuid-1",
    )
    authorization_uk = adobe_authorizations_file["authorizations"][0]["authorization_uk"]
    customer_id = "a-customer"

    deployment_id = "a_deployment_id"

    client, authorization, api_token = adobe_client_factory()

    adobe_order = adobe_order_factory(
        ORDER_TYPE_NEW, external_id="mpt-order-id", deployment_id=deployment_id
    )

    requests_mocker.post(
        urljoin(
            settings.EXTENSION_CONFIG["ADOBE_API_BASE_URL"],
            f"/v3/customers/{customer_id}/orders",
        ),
        status=202,
        json={
            "orderId": "adobe-order-id",
        },
        match=[
            matchers.header_matcher(
                {
                    "X-Api-Key": authorization.client_id,
                    "Authorization": f"Bearer {api_token.token}",
                    "Accept": "application/json",
                    "Content-Type": "application/json",
                    "X-Request-Id": "uuid-1",
                    "x-correlation-id": (
                        "dc133932f3e590ba2f958174213a688e50ac782e1650f8fcb6884a941622d1f2"
                    ),
                },
            ),
            matchers.json_params_matcher(adobe_order),
        ],
    )

    new_order = client.create_new_order(
        authorization_uk,
        customer_id,
        adobe_order,
        deployment_id=deployment_id,
    )
    assert new_order == {
        "orderId": "adobe-order-id",
    }


def test_create_new_order_no_deployment(
    mocker,
    settings,
    requests_mocker,
    adobe_client_factory,
    adobe_authorizations_file,
    adobe_order_factory,
):
    mocker.patch(
        "adobe_vipm.adobe.client.uuid4",
        return_value="uuid-1",
    )
    authorization_uk = adobe_authorizations_file["authorizations"][0]["authorization_uk"]
    customer_id = "a-customer"

    deployment_id = None

    client, authorization, api_token = adobe_client_factory()

    adobe_order = adobe_order_factory(
        ORDER_TYPE_NEW, external_id="mpt-order-id", deployment_id=deployment_id
    )

    requests_mocker.post(
        urljoin(
            settings.EXTENSION_CONFIG["ADOBE_API_BASE_URL"],
            f"/v3/customers/{customer_id}/orders",
        ),
        status=202,
        json={
            "orderId": "adobe-order-id",
        },
        match=[
            matchers.header_matcher(
                {
                    "X-Api-Key": authorization.client_id,
                    "Authorization": f"Bearer {api_token.token}",
                    "Accept": "application/json",
                    "Content-Type": "application/json",
                    "X-Request-Id": "uuid-1",
                    "x-correlation-id": (
                        "ac4eb5538ad0d84c816b61cfd73d39e82cc81085ace1a397c19318c4be1726a4"
                    ),
                },
            ),
            matchers.json_params_matcher(adobe_order),
        ],
    )

    new_order = client.create_new_order(
        authorization_uk,
        customer_id,
        adobe_order,
        deployment_id=deployment_id,
    )
    assert new_order == {
        "orderId": "adobe-order-id",
    }


def test_create_new_order_bad_request(
    requests_mocker,
    settings,
    adobe_client_factory,
    adobe_authorizations_file,
    adobe_order_factory,
    adobe_api_error_factory,
):
    authorization_uk = adobe_authorizations_file["authorizations"][0]["authorization_uk"]
    customer_id = "a-customer"

    client, _, _ = adobe_client_factory()

    error = adobe_api_error_factory("1234", "An error")

    requests_mocker.post(
        urljoin(
            settings.EXTENSION_CONFIG["ADOBE_API_BASE_URL"],
            f"/v3/customers/{customer_id}/orders",
        ),
        status=400,
        json=error,
    )

    with pytest.raises(AdobeError) as cv:
        client.create_new_order(
            authorization_uk,
            customer_id,
            adobe_order_factory(order_type=ORDER_TYPE_PREVIEW),
        )

    assert repr(cv.value) == str(error)


def test_create_preview_renewal(
    mocker,
    settings,
    requests_mocker,
    adobe_authorizations_file,
    adobe_client_factory,
    adobe_order_factory,
):
    mocker.patch(
        "adobe_vipm.adobe.client.uuid4",
        side_effect=["uuid-1", "uuid-2"],
    )
    authorization_uk = adobe_authorizations_file["authorizations"][0]["authorization_uk"]
    customer_id = "a-customer"

    client, authorization, api_token = adobe_client_factory()

    adobe_order = adobe_order_factory(ORDER_TYPE_PREVIEW_RENEWAL)

    requests_mocker.post(
        urljoin(
            settings.EXTENSION_CONFIG["ADOBE_API_BASE_URL"],
            f"/v3/customers/{customer_id}/orders",
        ),
        status=200,
        json=adobe_order,
        match=[
            matchers.header_matcher(
                {
                    "X-Api-Key": authorization.client_id,
                    "Authorization": f"Bearer {api_token.token}",
                    "Accept": "application/json",
                    "Content-Type": "application/json",
                    "X-Request-Id": "uuid-1",
                    "x-correlation-id": "uuid-2",
                },
            ),
            matchers.json_params_matcher(
                {
                    "orderType": ORDER_TYPE_PREVIEW_RENEWAL,
                },
            ),
        ],
    )

    preview_renewal = client.create_preview_renewal(
        authorization_uk,
        customer_id,
    )
    assert preview_renewal == adobe_order


def test_create_preview_renewal_bad_request(
    requests_mocker,
    settings,
    adobe_authorizations_file,
    adobe_api_error_factory,
    adobe_client_factory,
):
    authorization_uk = adobe_authorizations_file["authorizations"][0]["authorization_uk"]
    customer_id = "a-customer"

    client, _, _ = adobe_client_factory()

    error = adobe_api_error_factory("1234", "An error")

    requests_mocker.post(
        urljoin(
            settings.EXTENSION_CONFIG["ADOBE_API_BASE_URL"],
            f"/v3/customers/{customer_id}/orders",
        ),
        status=400,
        json=error,
    )

    with pytest.raises(AdobeError) as cv:
        client.create_preview_renewal(
            authorization_uk,
            customer_id,
        )

    assert repr(cv.value) == str(error)


def test_get_order(requests_mocker, settings, adobe_client_factory, adobe_authorizations_file):
    authorization_uk = adobe_authorizations_file["authorizations"][0]["authorization_uk"]
    customer_id = "a-customer"
    order_id = "an-order-id"

    client, authorization, api_token = adobe_client_factory()

    requests_mocker.get(
        urljoin(
            settings.EXTENSION_CONFIG["ADOBE_API_BASE_URL"],
            f"/v3/customers/{customer_id}/orders/{order_id}",
        ),
        status=200,
        json={"an": "order"},
        match=[
            matchers.header_matcher(
                {
                    "X-Api-Key": authorization.client_id,
                    "Authorization": f"Bearer {api_token.token}",
                    "Accept": "application/json",
                    "Content-Type": "application/json",
                },
            ),
        ],
    )

    assert client.get_order(authorization_uk, customer_id, order_id) == {"an": "order"}


def test_get_order_not_found(
    requests_mocker,
    settings,
    adobe_client_factory,
    adobe_authorizations_file,
    adobe_api_error_factory,
):
    authorization_uk = adobe_authorizations_file["authorizations"][0]["authorization_uk"]
    customer_id = "a-customer"
    order_id = "an-order-id"

    client, _, _ = adobe_client_factory()

    requests_mocker.get(
        urljoin(
            settings.EXTENSION_CONFIG["ADOBE_API_BASE_URL"],
            f"/v3/customers/{customer_id}/orders/{order_id}",
        ),
        status=404,
        json=adobe_api_error_factory("404", "Not Found"),
    )

    with pytest.raises(AdobeError) as cv:
        client.get_order(authorization_uk, customer_id, order_id)

    assert cv.value.code == "404"


def test_get_subscription(
    requests_mocker, settings, adobe_client_factory, adobe_authorizations_file
):
    authorization_uk = adobe_authorizations_file["authorizations"][0]["authorization_uk"]
    customer_id = "a-customer"
    sub_id = "a-sub-id"

    client, authorization, api_token = adobe_client_factory()

    requests_mocker.get(
        urljoin(
            settings.EXTENSION_CONFIG["ADOBE_API_BASE_URL"],
            f"/v3/customers/{customer_id}/subscriptions/{sub_id}",
        ),
        status=200,
        json={"a": "subscription"},
        match=[
            matchers.header_matcher(
                {
                    "X-Api-Key": authorization.client_id,
                    "Authorization": f"Bearer {api_token.token}",
                    "Accept": "application/json",
                    "Content-Type": "application/json",
                },
            ),
        ],
    )

    assert client.get_subscription(authorization_uk, customer_id, sub_id) == {"a": "subscription"}


def test_get_subscription_not_found(
    requests_mocker,
    settings,
    adobe_client_factory,
    adobe_authorizations_file,
    adobe_api_error_factory,
):
    authorization_uk = adobe_authorizations_file["authorizations"][0]["authorization_uk"]
    customer_id = "a-customer"
    sub_id = "a-sub-id"

    client, _, _ = adobe_client_factory()

    requests_mocker.get(
        urljoin(
            settings.EXTENSION_CONFIG["ADOBE_API_BASE_URL"],
            f"/v3/customers/{customer_id}/subscriptions/{sub_id}",
        ),
        status=404,
        json=adobe_api_error_factory("404", "Not Found"),
    )

    with pytest.raises(AdobeError) as cv:
        client.get_subscription(authorization_uk, customer_id, sub_id)

    assert cv.value.code == "404"


def test_create_return_order(
    mocker,
    settings,
    requests_mocker,
    adobe_client_factory,
    adobe_authorizations_file,
    adobe_order_factory,
    adobe_items_factory,
):
    mocker.patch(
        "adobe_vipm.adobe.client.uuid4",
        return_value="uuid-1",
    )
    authorization_uk = adobe_authorizations_file["authorizations"][0]["authorization_uk"]
    customer_id = "a-customer"

    deployment_id = "a_deployment_id"

    client, authorization, api_token = adobe_client_factory()

    returning_order = adobe_order_factory(
        ORDER_TYPE_NEW,
        external_id="ORD-1234",
        order_id="returning-order-id",
        status=AdobeStatus.PROCESSED.value,
        deployment_id=deployment_id,
    )

    returning_item = returning_order["lineItems"][0]

    ext_ref_prefix = "ext-ref-prefix"

    ext_reference_id = returning_order["externalReferenceId"]
    ext_item_number = returning_item["extLineItemNumber"]
    expected_external_id = f"{ext_ref_prefix}_{ext_reference_id}_{ext_item_number}"

    expected_body = adobe_order_factory(
        ORDER_TYPE_RETURN,
        reference_order_id=returning_order["orderId"],
        external_id=expected_external_id,
        items=adobe_items_factory(deployment_id=deployment_id, deployment_currency_code="USD"),
        deployment_id=deployment_id,
    )

    requests_mocker.post(
        urljoin(
            settings.EXTENSION_CONFIG["ADOBE_API_BASE_URL"],
            f"/v3/customers/{customer_id}/orders",
        ),
        status=202,
        json={
            "orderId": "adobe-order-id",
        },
        match=[
            matchers.header_matcher(
                {
                    "X-Api-Key": authorization.client_id,
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
        authorization_uk,
        customer_id,
        returning_order,
        returning_item,
        ext_ref_prefix,
        deployment_id=deployment_id,
    )
    assert return_order == {
        "orderId": "adobe-order-id",
    }


def test_create_return_order_bad_request(
    requests_mocker,
    settings,
    adobe_client_factory,
    adobe_authorizations_file,
    adobe_order_factory,
    adobe_api_error_factory,
):
    authorization_uk = adobe_authorizations_file["authorizations"][0]["authorization_uk"]
    customer_id = "a-customer"

    client, _, _ = adobe_client_factory()

    error = adobe_api_error_factory("1234", "An error")

    requests_mocker.post(
        urljoin(
            settings.EXTENSION_CONFIG["ADOBE_API_BASE_URL"],
            f"/v3/customers/{customer_id}/orders",
        ),
        status=400,
        json=error,
    )
    returning_order = adobe_order_factory(ORDER_TYPE_NEW, status=AdobeStatus.PROCESSED.value)

    with pytest.raises(AdobeError) as cv:
        client.create_return_order(
            authorization_uk,
            customer_id,
            returning_order,
            returning_order["lineItems"][0],
            "ext-ref-prefix",
        )

    assert repr(cv.value) == str(error)


def test_create_return_order_by_adobe_order(
    mocker,
    settings,
    requests_mocker,
    adobe_client_factory,
    adobe_authorizations_file,
    adobe_order_factory,
):
    mocker.patch(
        "adobe_vipm.adobe.client.uuid4",
        return_value="uuid-1",
    )
    authorization_uk = adobe_authorizations_file["authorizations"][0]["authorization_uk"]
    customer_id = "a-customer"

    client, authorization, api_token = adobe_client_factory()

    order_created = adobe_order_factory(
        ORDER_TYPE_NEW,
        external_id="ORD-1234",
        order_id="order-id",
        status=AdobeStatus.PROCESSED.value,
    )

    expected_body = {
        "externalReferenceId": f"{order_created['externalReferenceId']}_{order_created['orderId']}",
        "referenceOrderId": order_created["orderId"],
        "orderType": ORDER_TYPE_RETURN,
        "currencyCode": "USD",
        "lineItems": order_created["lineItems"],
    }

    requests_mocker.post(
        urljoin(
            settings.EXTENSION_CONFIG["ADOBE_API_BASE_URL"],
            f"/v3/customers/{customer_id}/orders",
        ),
        status=202,
        json={
            "orderId": "adobe-order-id",
        },
        match=[
            matchers.header_matcher(
                {
                    "X-Api-Key": authorization.client_id,
                    "Authorization": f"Bearer {api_token.token}",
                    "Accept": "application/json",
                    "Content-Type": "application/json",
                    "X-Request-Id": "uuid-1",
                    "x-correlation-id": "uuid-1",
                },
            ),
            matchers.json_params_matcher(expected_body),
        ],
    )

    return_order = client.create_return_order_by_adobe_order(
        authorization_uk,
        customer_id,
        order_created,
    )
    assert return_order == {
        "orderId": "adobe-order-id",
    }


def test_create_return_order_by_adobe_order_bad_request(
    requests_mocker,
    settings,
    adobe_client_factory,
    adobe_authorizations_file,
    adobe_order_factory,
    adobe_api_error_factory,
):
    authorization_uk = adobe_authorizations_file["authorizations"][0]["authorization_uk"]
    customer_id = "a-customer"

    client, _, _ = adobe_client_factory()

    error = adobe_api_error_factory("1234", "An error")

    requests_mocker.post(
        urljoin(
            settings.EXTENSION_CONFIG["ADOBE_API_BASE_URL"],
            f"/v3/customers/{customer_id}/orders",
        ),
        status=400,
        json=error,
    )
    order_created = adobe_order_factory(ORDER_TYPE_NEW, status=AdobeStatus.PROCESSED.value)

    with pytest.raises(AdobeError) as cv:
        client.create_return_order_by_adobe_order(
            authorization_uk,
            customer_id,
            order_created,
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
    requests_mocker,
    settings,
    adobe_client_factory,
    adobe_authorizations_file,
    update_params,
):
    authorization_uk = adobe_authorizations_file["authorizations"][0]["authorization_uk"]
    customer_id = "a-customer"
    sub_id = "a-sub-id"

    client, authorization, api_token = adobe_client_factory()

    body_to_match = {
        "autoRenewal": {
            "enabled": update_params.get("auto_renewal", True),
        },
    }
    if "quantity" in update_params:
        body_to_match["autoRenewal"][Param.RENEWAL_QUANTITY.value] = update_params["quantity"]

    requests_mocker.patch(
        urljoin(
            settings.EXTENSION_CONFIG["ADOBE_API_BASE_URL"],
            f"/v3/customers/{customer_id}/subscriptions/{sub_id}",
        ),
        status=200,
        json={"a": "subscription"},
        match=[
            matchers.header_matcher(
                {
                    "X-Api-Key": authorization.client_id,
                    "Authorization": f"Bearer {api_token.token}",
                    "Accept": "application/json",
                    "Content-Type": "application/json",
                },
            ),
            matchers.json_params_matcher(body_to_match),
        ],
    )

    requests_mocker.get(
        urljoin(
            settings.EXTENSION_CONFIG["ADOBE_API_BASE_URL"],
            f"/v3/customers/{customer_id}/subscriptions/{sub_id}",
        ),
        status=200,
        json={"b": "subscription"},
        match=[
            matchers.header_matcher(
                {
                    "X-Api-Key": authorization.client_id,
                    "Authorization": f"Bearer {api_token.token}",
                    "Accept": "application/json",
                    "Content-Type": "application/json",
                },
            ),
        ],
    )

    assert client.update_subscription(
        authorization_uk,
        customer_id,
        sub_id,
        **update_params,
    ) == {"b": "subscription"}


def test_update_subscription_not_found(
    requests_mocker,
    settings,
    adobe_client_factory,
    adobe_authorizations_file,
    adobe_api_error_factory,
):
    authorization_uk = adobe_authorizations_file["authorizations"][0]["authorization_uk"]
    customer_id = "a-customer"
    sub_id = "a-sub-id"

    client, _, _ = adobe_client_factory()

    requests_mocker.patch(
        urljoin(
            settings.EXTENSION_CONFIG["ADOBE_API_BASE_URL"],
            f"/v3/customers/{customer_id}/subscriptions/{sub_id}",
        ),
        status=404,
        json=adobe_api_error_factory("404", "Not Found"),
    )

    with pytest.raises(AdobeError) as cv:
        client.update_subscription(authorization_uk, customer_id, sub_id, quantity=10)

    assert cv.value.code == "404"


def test_preview_transfer(
    requests_mocker, settings, adobe_client_factory, adobe_authorizations_file
):
    authorization_uk = adobe_authorizations_file["authorizations"][0]["authorization_uk"]
    membership_id = "a-membership-id"

    client, authorization, api_token = adobe_client_factory()

    requests_mocker.get(
        urljoin(
            settings.EXTENSION_CONFIG["ADOBE_API_BASE_URL"],
            f"/v3/memberships/{membership_id}/offers",
        ),
        status=200,
        json={"a": "transfer-preview"},
        match=[
            matchers.header_matcher(
                {
                    "X-Api-Key": authorization.client_id,
                    "Authorization": f"Bearer {api_token.token}",
                    "Accept": "application/json",
                    "Content-Type": "application/json",
                },
            ),
            matchers.query_param_matcher(
                {
                    "ignore-order-return": "true",
                    "expire-open-pas": "true",
                },
            ),
        ],
    )

    assert client.preview_transfer(authorization_uk, membership_id) == {"a": "transfer-preview"}


def test_preview_transfer_not_found(
    requests_mocker,
    settings,
    adobe_client_factory,
    adobe_authorizations_file,
    adobe_api_error_factory,
):
    authorization_uk = adobe_authorizations_file["authorizations"][0]["authorization_uk"]
    membership_id = "a-membership-id"

    client, _, _ = adobe_client_factory()

    requests_mocker.get(
        urljoin(
            settings.EXTENSION_CONFIG["ADOBE_API_BASE_URL"],
            f"/v3/memberships/{membership_id}/offers",
        ),
        status=404,
        json=adobe_api_error_factory("404", "Not Found"),
    )

    with pytest.raises(AdobeError) as cv:
        client.preview_transfer(authorization_uk, membership_id)

    assert cv.value.code == "404"


def test_create_transfer(
    mocker,
    settings,
    requests_mocker,
    adobe_client_factory,
    adobe_authorizations_file,
):
    mocker.patch(
        "adobe_vipm.adobe.client.uuid4",
        return_value="uuid-1",
    )
    authorization_uk = adobe_authorizations_file["authorizations"][0]["authorization_uk"]
    reseller_id = adobe_authorizations_file["authorizations"][0]["resellers"][0]["id"]
    seller_id = adobe_authorizations_file["authorizations"][0]["resellers"][0]["seller_id"]
    membership_id = "a-membership-id"
    order_id = "an-order-id"

    client, authorization, api_token = adobe_client_factory()

    requests_mocker.post(
        urljoin(
            settings.EXTENSION_CONFIG["ADOBE_API_BASE_URL"],
            f"/v3/memberships/{membership_id}/transfers",
        ),
        status=202,
        json={
            "tansferId": "adobe-transfer-id",
        },
        match=[
            matchers.header_matcher(
                {
                    "X-Api-Key": authorization.client_id,
                    "Authorization": f"Bearer {api_token.token}",
                    "Accept": "application/json",
                    "Content-Type": "application/json",
                    "X-Request-Id": "uuid-1",
                    "x-correlation-id": order_id,
                },
            ),
            matchers.json_params_matcher({"resellerId": reseller_id}),
            matchers.query_param_matcher(
                {
                    "ignore-order-return": "true",
                    "expire-open-pas": "true",
                },
            ),
        ],
    )

    new_transfer = client.create_transfer(
        authorization_uk,
        seller_id,
        order_id,
        membership_id,
    )
    assert new_transfer == {
        "tansferId": "adobe-transfer-id",
    }


def test_create_transfer_bad_request(
    requests_mocker,
    settings,
    adobe_client_factory,
    adobe_authorizations_file,
    adobe_api_error_factory,
):
    authorization_uk = adobe_authorizations_file["authorizations"][0]["authorization_uk"]
    seller_id = adobe_authorizations_file["authorizations"][0]["resellers"][0]["seller_id"]
    membership_id = "a-membership-id"

    client, _, _ = adobe_client_factory()

    error = adobe_api_error_factory("1234", "An error")

    requests_mocker.post(
        urljoin(
            settings.EXTENSION_CONFIG["ADOBE_API_BASE_URL"],
            f"/v3/memberships/{membership_id}/transfers",
        ),
        status=400,
        json=error,
    )

    with pytest.raises(AdobeError) as cv:
        client.create_transfer(
            authorization_uk,
            seller_id,
            "an-order-id",
            membership_id,
        )

    assert repr(cv.value) == str(error)


def test_get_transfer(requests_mocker, settings, adobe_client_factory, adobe_authorizations_file):
    authorization_uk = adobe_authorizations_file["authorizations"][0]["authorization_uk"]
    membership_id = "a-membership-id"
    transfer_id = "a-transfer-id"

    client, authorization, api_token = adobe_client_factory()

    requests_mocker.get(
        urljoin(
            settings.EXTENSION_CONFIG["ADOBE_API_BASE_URL"],
            f"/v3/memberships/{membership_id}/transfers/{transfer_id}",
        ),
        status=200,
        json={"a": "transfer"},
        match=[
            matchers.header_matcher(
                {
                    "X-Api-Key": authorization.client_id,
                    "Authorization": f"Bearer {api_token.token}",
                    "Accept": "application/json",
                    "Content-Type": "application/json",
                },
            ),
        ],
    )

    assert client.get_transfer(authorization_uk, membership_id, transfer_id) == {"a": "transfer"}


def test_get_transfer_not_found(
    requests_mocker,
    settings,
    adobe_client_factory,
    adobe_authorizations_file,
    adobe_api_error_factory,
):
    authorization_uk = adobe_authorizations_file["authorizations"][0]["authorization_uk"]
    membership_id = "a-membership-id"
    transfer_id = "a-transfer-id"

    client, _, _ = adobe_client_factory()

    requests_mocker.get(
        urljoin(
            settings.EXTENSION_CONFIG["ADOBE_API_BASE_URL"],
            f"/v3/memberships/{membership_id}/transfers/{transfer_id}",
        ),
        status=404,
        json=adobe_api_error_factory("404", "Not Found"),
    )

    with pytest.raises(AdobeError) as cv:
        client.get_transfer(authorization_uk, membership_id, transfer_id)

    assert cv.value.code == "404"


def test_get_auth_token(requests_mocker, settings, mock_adobe_config, adobe_config_file):
    authorization = Authorization(
        authorization_uk="auth_uk",
        authorization_id="auth_id",
        name="test",
        client_id="client_id",
        client_secret="client_secret",  # noqa: S106
        currency="USD",
        distributor_id="distributor_id",
    )

    requests_mocker.post(
        settings.EXTENSION_CONFIG["ADOBE_AUTH_ENDPOINT_URL"],
        json={
            "access_token": "an-access-token",
            "expires_in": 83000,
        },
        match=[
            matchers.urlencoded_params_matcher(
                {
                    "grant_type": "client_credentials",
                    "client_id": authorization.client_id,
                    "client_secret": authorization.client_secret,
                    "scope": ",".join(REQUIRED_API_SCOPES),
                },
            ),
        ],
    )

    client = adobe_client.AdobeClient()
    with freeze_time("2024-01-01 12:00:00"):
        token = client._get_auth_token(authorization)  # noqa: SLF001
        assert isinstance(token, APIToken)
        assert token.token == "an-access-token"
        assert token.expires == dt.datetime.now(tz=dt.UTC) + dt.timedelta(seconds=83000 - 180)
        assert client._token_cache[authorization] == token  # noqa: SLF001


def test_get_auth_token_error(requests_mocker, settings, mock_adobe_config, adobe_config_file):
    authorization = Authorization(
        authorization_uk="auth_uk",
        authorization_id="auth_id",
        name="test",
        client_id="client_id",
        client_secret="client_secret",  # noqa: S106
        currency="USD",
        distributor_id="distributor_id",
    )

    requests_mocker.post(
        settings.EXTENSION_CONFIG["ADOBE_AUTH_ENDPOINT_URL"],
        status=403,
    )

    client = adobe_client.AdobeClient()
    with pytest.raises(requests.HTTPError):
        client._get_auth_token(authorization)  # noqa: SLF001


def test_get_adobe_client(mocker):
    adobe_client._ADOBE_CLIENT = None  # noqa: SLF001

    mocked_client = mocker.MagicMock()
    mocked_client_constructor = mocker.patch(
        "adobe_vipm.adobe.client.AdobeClient",
        return_value=mocked_client,
    )
    adobe_client.get_adobe_client()
    adobe_client.get_adobe_client()
    assert mocked_client_constructor.call_count == 1


def test_get_subscriptions(
    requests_mocker, settings, adobe_client_factory, adobe_authorizations_file
):
    authorization_uk = adobe_authorizations_file["authorizations"][0]["authorization_uk"]
    customer_id = "a-customer"

    client, authorization, api_token = adobe_client_factory()

    requests_mocker.get(
        urljoin(
            settings.EXTENSION_CONFIG["ADOBE_API_BASE_URL"],
            f"/v3/customers/{customer_id}/subscriptions",
        ),
        status=200,
        json={"items": [{"a": "subscription"}]},
        match=[
            matchers.header_matcher(
                {
                    "X-Api-Key": authorization.client_id,
                    "Authorization": f"Bearer {api_token.token}",
                    "Accept": "application/json",
                    "Content-Type": "application/json",
                },
            ),
        ],
    )

    assert client.get_subscriptions(authorization_uk, customer_id) == {
        "items": [{"a": "subscription"}]
    }


def test_get_customer(requests_mocker, settings, adobe_client_factory, adobe_authorizations_file):
    authorization_uk = adobe_authorizations_file["authorizations"][0]["authorization_uk"]
    customer_id = "a-customer-id"

    client, authorization, api_token = adobe_client_factory()

    requests_mocker.get(
        urljoin(
            settings.EXTENSION_CONFIG["ADOBE_API_BASE_URL"],
            f"/v3/customers/{customer_id}",
        ),
        status=200,
        json={"a": "customer"},
        match=[
            matchers.header_matcher(
                {
                    "X-Api-Key": authorization.client_id,
                    "Authorization": f"Bearer {api_token.token}",
                    "Accept": "application/json",
                    "Content-Type": "application/json",
                },
            ),
        ],
    )

    assert client.get_customer(authorization_uk, customer_id) == {"a": "customer"}


def test_get_customer_not_found(
    requests_mocker,
    settings,
    adobe_client_factory,
    adobe_authorizations_file,
    adobe_api_error_factory,
):
    authorization_uk = adobe_authorizations_file["authorizations"][0]["authorization_uk"]
    customer_id = "a-customer-id"

    client, _, _ = adobe_client_factory()

    requests_mocker.get(
        urljoin(
            settings.EXTENSION_CONFIG["ADOBE_API_BASE_URL"],
            f"/v3/customers/{customer_id}",
        ),
        status=404,
        json=adobe_api_error_factory("404", "Not Found"),
    )

    with pytest.raises(AdobeError) as cv:
        client.get_customer(authorization_uk, customer_id)

    assert cv.value.code == "404"


@pytest.mark.parametrize(
    ("quantities", "expected"),
    [
        (
            {"3YCLicenses": "12"},
            [
                {
                    "offerType": "LICENSE",
                    "quantity": 12,
                },
            ],
        ),
        (
            {"3YCConsumables": "500"},
            [
                {
                    "offerType": "CONSUMABLES",
                    "quantity": 500,
                },
            ],
        ),
        (
            {
                "3YCLicenses": "9",
                "3YCConsumables": "1220",
            },
            [
                {
                    "offerType": "LICENSE",
                    "quantity": 9,
                },
                {
                    "offerType": "CONSUMABLES",
                    "quantity": 1220,
                },
            ],
        ),
    ],
)
def test_create_customer_account_3yc(
    mocker,
    settings,
    requests_mocker,
    adobe_authorizations_file,
    customer_data,
    adobe_client_factory,
    quantities,
    expected,
):
    mocker.patch(
        "adobe_vipm.adobe.client.uuid4",
        return_value="uuid-1",
    )
    seller_id = adobe_authorizations_file["authorizations"][0]["resellers"][0]["seller_id"]
    reseller_id = adobe_authorizations_file["authorizations"][0]["resellers"][0]["id"]
    authorization_uk = adobe_authorizations_file["authorizations"][0]["authorization_uk"]

    client, authorization, api_token = adobe_client_factory()

    modified_customer = copy.copy(customer_data)

    company_name = f"{modified_customer['companyName']} (external_id)"
    modified_customer["3YC"] = ["Yes"]
    modified_customer.update(quantities)

    payload = {
        "resellerId": reseller_id,
        "externalReferenceId": "external_id",
        "companyProfile": {
            "companyName": company_name,
            "preferredLanguage": "en-US",
            "marketSegment": "EDU",
            "address": {
                "country": modified_customer["address"]["country"],
                "region": modified_customer["address"]["state"],
                "city": modified_customer["address"]["city"],
                "addressLine1": modified_customer["address"]["addressLine1"],
                "addressLine2": modified_customer["address"]["addressLine2"],
                "postalCode": modified_customer["address"]["postCode"],
                "phoneNumber": join_phone_number(modified_customer["contact"]["phone"]),
            },
            "contacts": [
                {
                    "firstName": modified_customer["contact"]["firstName"],
                    "lastName": modified_customer["contact"]["lastName"],
                    "email": modified_customer["contact"]["email"],
                    "phoneNumber": join_phone_number(modified_customer["contact"]["phone"]),
                }
            ],
        },
        "benefits": [
            {
                "type": "THREE_YEAR_COMMIT",
                "commitmentRequest": {
                    "minimumQuantities": expected,
                },
            },
        ],
    }

    correlation_id = sha256(json.dumps(payload).encode()).hexdigest()
    requests_mocker.post(
        urljoin(settings.EXTENSION_CONFIG["ADOBE_API_BASE_URL"], "/v3/customers"),
        status=201,
        json={
            "customerId": "A-customer-id",
        },
        match=[
            matchers.header_matcher(
                {
                    "X-Api-Key": authorization.client_id,
                    "Authorization": f"Bearer {api_token.token}",
                    "Accept": "application/json",
                    "Content-Type": "application/json",
                    "X-Request-Id": "uuid-1",
                    "x-correlation-id": correlation_id,
                },
            ),
            matchers.json_params_matcher(payload),
        ],
    )

    customer_id = client.create_customer_account(
        authorization_uk, seller_id, "external_id", "EDU", modified_customer
    )
    assert customer_id == {"customerId": "A-customer-id"}


@pytest.mark.parametrize(
    ("quantities", "expected"),
    [
        (
            {
                "3YCLicenses": "12",
                "3YCConsumables": "",
            },
            [
                {
                    "offerType": "LICENSE",
                    "quantity": 12,
                },
            ],
        ),
        (
            {
                "3YCLicenses": "",
                "3YCConsumables": "500",
            },
            [
                {
                    "offerType": "CONSUMABLES",
                    "quantity": 500,
                },
            ],
        ),
        (
            {
                "3YCLicenses": "9",
                "3YCConsumables": "1220",
            },
            [
                {
                    "offerType": "LICENSE",
                    "quantity": 9,
                },
                {
                    "offerType": "CONSUMABLES",
                    "quantity": 1220,
                },
            ],
        ),
    ],
)
@pytest.mark.parametrize("is_recommitment", [False, True])
def test_create_3yc_request(
    mocker,
    settings,
    requests_mocker,
    adobe_authorizations_file,
    customer_data,
    adobe_client_factory,
    is_recommitment,
    quantities,
    expected,
):
    mocker.patch(
        "adobe_vipm.adobe.client.uuid4",
        return_value="uuid-1",
    )

    authorization_uk = adobe_authorizations_file["authorizations"][0]["authorization_uk"]

    client, authorization, api_token = adobe_client_factory()

    modified_customer = copy.copy(customer_data)

    company_name = f"{modified_customer['companyName']} (external_id)"

    company_profile = {
        "companyName": company_name,
        "preferredLanguage": "en-US",
        "address": {
            "country": modified_customer["address"]["country"],
            "region": modified_customer["address"]["state"],
            "city": modified_customer["address"]["city"],
            "addressLine1": modified_customer["address"]["addressLine1"],
            "addressLine2": modified_customer["address"]["addressLine2"],
            "postalCode": modified_customer["address"]["postCode"],
            "phoneNumber": join_phone_number(modified_customer["contact"]["phone"]),
        },
        "contacts": [
            {
                "firstName": modified_customer["contact"]["firstName"],
                "lastName": modified_customer["contact"]["lastName"],
                "email": modified_customer["contact"]["email"],
                "phoneNumber": join_phone_number(modified_customer["contact"]["phone"]),
            }
        ],
    }

    client.get_customer = mocker.MagicMock(
        return_value={"companyProfile": company_profile},
    )

    request_type = "commitmentRequest" if not is_recommitment else "recommitmentRequest"

    payload = {
        "companyProfile": company_profile,
        "benefits": [
            {
                "type": "THREE_YEAR_COMMIT",
                request_type: {
                    "minimumQuantities": expected,
                },
            },
        ],
    }

    correlation_id = sha256(json.dumps(payload).encode()).hexdigest()
    requests_mocker.patch(
        urljoin(
            settings.EXTENSION_CONFIG["ADOBE_API_BASE_URL"],
            "/v3/customers/a-customer-id",
        ),
        status=200,
        json={
            "customerId": "a-customer-id",
        },
        match=[
            matchers.header_matcher(
                {
                    "X-Api-Key": authorization.client_id,
                    "Authorization": f"Bearer {api_token.token}",
                    "Accept": "application/json",
                    "Content-Type": "application/json",
                    "X-Request-Id": "uuid-1",
                    "x-correlation-id": correlation_id,
                },
            ),
            matchers.json_params_matcher(payload),
        ],
    )

    customer_id = client.create_3yc_request(
        authorization_uk,
        "a-customer-id",
        quantities,
        is_recommitment=is_recommitment,
    )
    assert customer_id == {"customerId": "a-customer-id"}


def test_get_orders(requests_mocker, settings, adobe_client_factory, adobe_authorizations_file):
    authorization_uk = adobe_authorizations_file["authorizations"][0]["authorization_uk"]
    customer_id = "a-customer"

    client, authorization, api_token = adobe_client_factory()

    page1 = [{"orderId": f"P{i}"} for i in range(100)]
    page2 = [{"orderId": f"P{i}"} for i in range(100, 105)]

    requests_mocker.get(
        urljoin(
            settings.EXTENSION_CONFIG["ADOBE_API_BASE_URL"],
            f"/v3/customers/{customer_id}/orders?limit=100&offset=0",
        ),
        status=200,
        json={
            "items": page1,
            "links": {
                "next": {
                    "uri": urljoin(
                        settings.EXTENSION_CONFIG["ADOBE_API_BASE_URL"],
                        f"/v3/customers/{customer_id}/orders?limit=100&offset=100",
                    )
                },
            },
        },
        match=[
            matchers.header_matcher(
                {
                    "X-Api-Key": authorization.client_id,
                    "Authorization": f"Bearer {api_token.token}",
                    "Accept": "application/json",
                    "Content-Type": "application/json",
                },
            ),
        ],
    )

    requests_mocker.get(
        urljoin(
            settings.EXTENSION_CONFIG["ADOBE_API_BASE_URL"],
            f"/v3/customers/{customer_id}/orders?limit=100&offset=100",
        ),
        status=200,
        json={
            "items": page2,
            "links": {},
        },
        match=[
            matchers.header_matcher(
                {
                    "X-Api-Key": authorization.client_id,
                    "Authorization": f"Bearer {api_token.token}",
                    "Accept": "application/json",
                    "Content-Type": "application/json",
                },
            ),
        ],
    )

    orders = client.get_orders(authorization_uk, customer_id)

    assert orders == page1 + page2


def test_get_orders_extra_filters(
    requests_mocker, settings, adobe_client_factory, adobe_authorizations_file
):
    authorization_uk = adobe_authorizations_file["authorizations"][0]["authorization_uk"]
    customer_id = "a-customer"

    client, authorization, api_token = adobe_client_factory()

    page = [{"orderId": f"P{i}"} for i in range(5)]

    requests_mocker.get(
        urljoin(
            settings.EXTENSION_CONFIG["ADOBE_API_BASE_URL"],
            f"/v3/customers/{customer_id}/orders?limit=100&offset=0&extra=filter",
        ),
        status=200,
        json={
            "items": page,
            "links": {},
        },
        match=[
            matchers.header_matcher(
                {
                    "X-Api-Key": authorization.client_id,
                    "Authorization": f"Bearer {api_token.token}",
                    "Accept": "application/json",
                    "Content-Type": "application/json",
                },
            ),
        ],
    )

    assert client.get_orders(authorization_uk, customer_id, filters={"extra": "filter"}) == page


@freeze_time("2024-01-01")
def test_get_returnable_orders_by_subscription_id(
    mocker,
    adobe_order_factory,
    adobe_items_factory,
    adobe_client_factory,
    adobe_authorizations_file,
):
    # new before last renewal
    order_ko_0 = adobe_order_factory(
        order_id="order_ko_0",
        order_type=ORDER_TYPE_NEW,
        items=adobe_items_factory(
            subscription_id="SUB-1000-2000-3001",
            status=AdobeStatus.PROCESSED
        .value),
        status=AdobeStatus.PROCESSED.value,
        creation_date="2024-01-06T00:00:00Z",
    )
    order_ok_1 = adobe_order_factory(
        order_id="order_ok_1",
        order_type=ORDER_TYPE_RENEWAL,
        items=adobe_items_factory(
            subscription_id="SUB-1000-2000-3000",
            status=AdobeStatus.PROCESSED
        .value),
        status=AdobeStatus.PROCESSED.value,
        creation_date="2024-01-07T00:00:00Z",
    )
    order_ok_2 = adobe_order_factory(
        order_id="order_ok_2",
        order_type=ORDER_TYPE_NEW,
        items=adobe_items_factory(
            subscription_id="SUB-1000-2000-3000",
            status=AdobeStatus.PROCESSED
        .value),
        status=AdobeStatus.PROCESSED.value,
        creation_date="2024-01-08T00:00:00Z",
    )
    order_ko_1 = adobe_order_factory(
        order_id="order_ko_1",
        order_type=ORDER_TYPE_NEW,
        items=adobe_items_factory(
            subscription_id="SUB-1000-2000-3001",
            status=AdobeStatus.ORDER_CANCELLED
        .value),
        status=AdobeStatus.PROCESSED.value,
        creation_date="2024-01-09T00:00:00Z",
    )
    order_ko_2 = adobe_order_factory(
        order_id="order_ko_2",
        order_type=ORDER_TYPE_NEW,
        items=adobe_items_factory(
            subscription_id="SUB-1000-2000-3000",
            status=AdobeStatus.PROCESSED
        .value),
        status=AdobeStatus.ORDER_CANCELLED.value,
    )
    # for another sku
    order_ko_3 = adobe_order_factory(
        order_id="order_ko_3",
        order_type=ORDER_TYPE_RENEWAL,
        items=adobe_items_factory(
            subscription_id="SUB-1000-2000-3002",
            offer_id="99999999CA01A12",
            status=AdobeStatus.PROCESSED
        .value),
        status=AdobeStatus.PROCESSED.value,
        creation_date="2024-01-10T00:00:00Z",
    )

    mocked_get_orders = mocker.patch.object(
        adobe_client.AdobeClient,
        "get_orders",
        return_value=[
            order_ko_0,
            order_ok_1,
            order_ko_1,
            order_ko_2,
            order_ko_3,
            order_ok_2,
        ],
    )

    authorization_uk = adobe_authorizations_file["authorizations"][0]["authorization_uk"]
    customer_id = "a-customer"
    client, _, _ = adobe_client_factory()

    assert client.get_returnable_orders_by_subscription_id(
        authorization_uk,
        customer_id,
        "SUB-1000-2000-3000",
        "2024-03-03",
    ) == [
        ReturnableOrderInfo(
            order=order_ok_1,
            line=order_ok_1["lineItems"][0],
            quantity=order_ok_1["lineItems"][0]["quantity"],
        ),
        ReturnableOrderInfo(
            order=order_ok_2,
            line=order_ok_2["lineItems"][0],
            quantity=order_ok_2["lineItems"][0]["quantity"],
        ),
    ]

    mocked_get_orders.assert_called_once_with(
        authorization_uk,
        customer_id,
        filters={
            "order-type": [ORDER_TYPE_NEW, ORDER_TYPE_RENEWAL],
            "start-date": "2023-12-18",
            "end-date": "2024-03-03",
        },
    )


@freeze_time("2024-01-01")
def test_get_returnable_orders_by_subscription_id_with_returning_orders(
    mocker,
    adobe_order_factory,
    adobe_items_factory,
    adobe_client_factory,
    adobe_authorizations_file,
):
    order_ko_0 = adobe_order_factory(
        order_id="order_ko_0",
        order_type=ORDER_TYPE_NEW,
        items=adobe_items_factory(
            subscription_id="SUB-1000-2000-3001",
            status=AdobeStatus.PROCESSED
        .value),
        status=AdobeStatus.PROCESSED.value,
        creation_date="2024-01-06T00:00:00Z",
    )
    order_ok_1 = adobe_order_factory(
        order_id="order_ok_1",
        order_type=ORDER_TYPE_RENEWAL,
        items=adobe_items_factory(
            subscription_id="SUB-1000-2000-3000",
            status=AdobeStatus.PROCESSED
        .value),
        status=AdobeStatus.PROCESSED.value,
        creation_date="2024-01-07T00:00:00Z",
    )
    order_ok_2 = adobe_order_factory(
        order_id="order_ok_2",
        order_type=ORDER_TYPE_NEW,
        items=adobe_items_factory(
            subscription_id="SUB-1000-2000-3000",
            status=AdobeStatus.PROCESSED
        .value),
        status=AdobeStatus.PROCESSED.value,
        creation_date="2024-01-08T00:00:00Z",
    )
    order_ok_3 = adobe_order_factory(
        order_id="order_ok_3",
        order_type=ORDER_TYPE_NEW,
        items=adobe_items_factory(
            subscription_id="SUB-1000-2000-3000",
            status=AdobeStatus.ORDER_CANCELLED
        .value),
        status=AdobeStatus.PROCESSED.value,
        creation_date="2024-01-09T00:00:00Z",
    )
    order_ok_4 = adobe_order_factory(
        order_id="order_ok_4",
        order_type=ORDER_TYPE_NEW,
        items=adobe_items_factory(
            subscription_id="SUB-1000-2000-3000",
            status=AdobeStatus.PROCESSED
        .value),
        status=AdobeStatus.ORDER_CANCELLED.value,
        creation_date="2024-01-10T00:00:00Z",
    )
    order_ko_1 = adobe_order_factory(
        order_id="order_ko_1",
        order_type=ORDER_TYPE_RENEWAL,
        items=adobe_items_factory(
            subscription_id="SUB-1000-2000-3002",
            offer_id="99999999CA01A12",
            status=AdobeStatus.PROCESSED
        .value),
        status=AdobeStatus.PROCESSED.value,
        creation_date="2024-01-11T00:00:00Z",
    )

    ret_order_1 = adobe_order_factory(
        reference_order_id="order_ok_3",
        order_type=ORDER_TYPE_RETURN,
    )
    ret_order_2 = adobe_order_factory(
        reference_order_id="order_ok_4",
        order_type=ORDER_TYPE_RETURN,
    )

    mocked_get_orders = mocker.patch.object(
        adobe_client.AdobeClient,
        "get_orders",
        return_value=[
            order_ko_0,
            order_ok_1,
            order_ok_2,
            order_ok_3,
            order_ok_4,
            order_ko_1,
        ],
    )

    authorization_uk = adobe_authorizations_file["authorizations"][0]["authorization_uk"]
    customer_id = "a-customer"
    client, _, _ = adobe_client_factory()

    assert client.get_returnable_orders_by_subscription_id(
        authorization_uk,
        customer_id,
        "SUB-1000-2000-3000",
        "2024-03-03",
        return_orders=[ret_order_1, ret_order_2],
    ) == [
        ReturnableOrderInfo(
            order=order_ok_1,
            line=order_ok_1["lineItems"][0],
            quantity=order_ok_1["lineItems"][0]["quantity"],
        ),
        ReturnableOrderInfo(
            order=order_ok_2,
            line=order_ok_2["lineItems"][0],
            quantity=order_ok_2["lineItems"][0]["quantity"],
        ),
        ReturnableOrderInfo(
            order=order_ok_3,
            line=order_ok_3["lineItems"][0],
            quantity=order_ok_3["lineItems"][0]["quantity"],
        ),
        ReturnableOrderInfo(
            order=order_ok_4,
            line=order_ok_4["lineItems"][0],
            quantity=order_ok_4["lineItems"][0]["quantity"],
        ),
    ]

    mocked_get_orders.assert_called_once_with(
        authorization_uk,
        customer_id,
        filters={
            "order-type": [ORDER_TYPE_NEW, ORDER_TYPE_RENEWAL],
            "start-date": "2023-12-18",
            "end-date": "2024-03-03",
        },
    )


def test_get_return_orders_by_external_reference(
    mocker,
    adobe_order_factory,
    adobe_items_factory,
    adobe_client_factory,
    adobe_authorizations_file,
):
    order_ok_1 = adobe_order_factory(
        order_type=ORDER_TYPE_RETURN,
        items=adobe_items_factory(status=AdobeStatus.PROCESSED.value),
        status=AdobeStatus.PROCESSED.value,
        external_id="returning-mpt-order-123_returned-mpt-order-456_line1",
    )
    order_ok_2 = adobe_order_factory(
        order_type=ORDER_TYPE_RETURN,
        items=adobe_items_factory(status=AdobeStatus.PROCESSED.value),
        status=AdobeStatus.PENDING.value,
        external_id="returning-mpt-order-123_returned-mpt-order-789_line1",
    )
    order_ko_1 = adobe_order_factory(
        order_type=ORDER_TYPE_RETURN,
        items=adobe_items_factory(status=AdobeStatus.PROCESSED.value),
        status=AdobeStatus.PROCESSED.value,
        external_id="returning-mpt-order-987_returned-mpt-order-456_line1",
    )

    mocked_get_orders = mocker.patch.object(
        adobe_client.AdobeClient,
        "get_orders",
        return_value=[order_ok_1, order_ok_2, order_ko_1],
    )

    authorization_uk = adobe_authorizations_file["authorizations"][0]["authorization_uk"]
    customer_id = "a-customer"
    client, _, _ = adobe_client_factory()

    return_orders = client.get_return_orders_by_external_reference(
        authorization_uk,
        customer_id,
        "returning-mpt-order-123",
    )
    assert return_orders[order_ok_1["lineItems"][0]["offerId"][:10]] == [
        order_ok_1,
        order_ok_2,
    ]

    mocked_get_orders.assert_called_once_with(
        authorization_uk,
        customer_id,
        filters={
            "order-type": ORDER_TYPE_RETURN,
            "status": [AdobeStatus.PROCESSED.value, AdobeStatus.PENDING.value],
        },
    )


@freeze_time("2024-01-01")
def test_get_returnable_orders_by_subscription_id_no_renewal_for_period(
    mocker,
    adobe_order_factory,
    adobe_items_factory,
    adobe_client_factory,
    adobe_authorizations_file,
):
    order_ok_0 = adobe_order_factory(
        order_id="order_ko_0",
        order_type=ORDER_TYPE_NEW,
        items=adobe_items_factory(
            subscription_id="SUB-1000-2000-3000",
            status=AdobeStatus.PROCESSED
        .value),
        status=AdobeStatus.PROCESSED.value,
        creation_date="2024-01-06T00:00:00Z",
    )
    order_ok_1 = adobe_order_factory(
        order_id="order_ok_1",
        order_type=ORDER_TYPE_NEW,
        items=adobe_items_factory(
            subscription_id="SUB-1000-2000-3000",
            status=AdobeStatus.PROCESSED
        .value),
        status=AdobeStatus.PROCESSED.value,
        creation_date="2024-01-07T00:00:00Z",
    )
    order_ok_2 = adobe_order_factory(
        order_id="order_ok_2",
        order_type=ORDER_TYPE_NEW,
        items=adobe_items_factory(
            subscription_id="SUB-1000-2000-3000",
            status=AdobeStatus.PROCESSED
        .value),
        status=AdobeStatus.PROCESSED.value,
        creation_date="2024-01-08T00:00:00Z",
    )
    order_ko_1 = adobe_order_factory(
        order_id="order_ko_1",
        order_type=ORDER_TYPE_NEW,
        items=adobe_items_factory(
            subscription_id="SUB-1000-2000-3001",
            status=AdobeStatus.ORDER_CANCELLED
        .value),
        status=AdobeStatus.PROCESSED.value,
        creation_date="2024-01-09T00:00:00Z",
    )
    order_ko_2 = adobe_order_factory(
        order_id="order_ko_2",
        order_type=ORDER_TYPE_NEW,
        items=adobe_items_factory(
            subscription_id="SUB-1000-2000-3002",
            status=AdobeStatus.PROCESSED
        .value),
        status=AdobeStatus.ORDER_CANCELLED.value,
    )
    # for another sku
    order_ko_3 = adobe_order_factory(
        order_id="order_ko_3",
        order_type=ORDER_TYPE_RENEWAL,
        items=adobe_items_factory(
            subscription_id="SUB-1000-2000-3003",
            offer_id="99999999CA01A12",
            status=AdobeStatus.PROCESSED
        .value),
        status=AdobeStatus.PROCESSED.value,
        creation_date="2024-01-10T00:00:00Z",
    )

    mocked_get_orders = mocker.patch.object(
        adobe_client.AdobeClient,
        "get_orders",
        return_value=[
            order_ok_0,
            order_ok_1,
            order_ko_1,
            order_ko_2,
            order_ko_3,
            order_ok_2,
        ],
    )

    authorization_uk = adobe_authorizations_file["authorizations"][0]["authorization_uk"]
    customer_id = "a-customer"
    client, _, _ = adobe_client_factory()

    assert client.get_returnable_orders_by_subscription_id(
        authorization_uk,
        customer_id,
        "SUB-1000-2000-3000",
        "2024-03-03",
    ) == [
        ReturnableOrderInfo(
            order=order_ok_0,
            line=order_ok_0["lineItems"][0],
            quantity=order_ok_0["lineItems"][0]["quantity"],
        ),
        ReturnableOrderInfo(
            order=order_ok_1,
            line=order_ok_1["lineItems"][0],
            quantity=order_ok_1["lineItems"][0]["quantity"],
        ),
        ReturnableOrderInfo(
            order=order_ok_2,
            line=order_ok_2["lineItems"][0],
            quantity=order_ok_2["lineItems"][0]["quantity"],
        ),
    ]

    mocked_get_orders.assert_called_once_with(
        authorization_uk,
        customer_id,
        filters={
            "order-type": [ORDER_TYPE_NEW, ORDER_TYPE_RENEWAL],
            "start-date": "2023-12-18",
            "end-date": "2024-03-03",
        },
    )


def test_get_customer_deployments(
    requests_mocker, settings, adobe_client_factory, adobe_authorizations_file
):
    authorization_uk = adobe_authorizations_file["authorizations"][0]["authorization_uk"]
    customer_id = "a-customer-id"

    client, authorization, api_token = adobe_client_factory()

    expected_response = {
        "totalCount": 1,
        "items": [
            {
                "deploymentId": "deployment-id-1",
                "status": "1000",
                "companyProfile": {"address": {"country": "DE"}},
            },
            {
                "deploymentId": "deployment-id-2",
                "status": "1004",
                "companyProfile": {"address": {"country": "DE"}},
            },
        ],
    }

    requests_mocker.get(
        urljoin(
            settings.EXTENSION_CONFIG["ADOBE_API_BASE_URL"],
            f"/v3/customers/{customer_id}/deployments?limit=100&offset=0",
        ),
        status=200,
        json=expected_response,
        match=[
            matchers.header_matcher(
                {
                    "X-Api-Key": authorization.client_id,
                    "Authorization": f"Bearer {api_token.token}",
                    "Accept": "application/json",
                    "Content-Type": "application/json",
                },
            ),
        ],
    )

    result = client.get_customer_deployments(authorization_uk, customer_id)

    assert result == expected_response


def test_get_customer_deployments_active_status(
    requests_mocker, settings, adobe_client_factory, adobe_authorizations_file
):
    authorization_uk = adobe_authorizations_file["authorizations"][0]["authorization_uk"]
    customer_id = "a-customer-id"

    client, authorization, api_token = adobe_client_factory()

    deployments_response = {
        "items": [
            {
                "deploymentId": "deployment-1",
                "status": "1000",
                "companyProfile": {"address": {"country": "DE"}},
            },
            {
                "deploymentId": "deployment-2",
                "status": "1004",
                "companyProfile": {"address": {"country": "US"}},
            },
            {
                "deploymentId": "deployment-3",
                "status": "1000",
                "companyProfile": {"address": {"country": "ES"}},
            },
        ]
    }

    active_deployments_response = [
        {
            "deploymentId": "deployment-1",
            "status": "1000",
            "companyProfile": {"address": {"country": "DE"}},
        },
        {
            "deploymentId": "deployment-3",
            "status": "1000",
            "companyProfile": {"address": {"country": "ES"}},
        },
    ]

    requests_mocker.get(
        urljoin(
            settings.EXTENSION_CONFIG["ADOBE_API_BASE_URL"],
            f"/v3/customers/{customer_id}/deployments?limit=100&offset=0",
        ),
        status=200,
        json=deployments_response,
        match=[
            matchers.header_matcher(
                {
                    "X-Api-Key": authorization.client_id,
                    "Authorization": f"Bearer {api_token.token}",
                    "Accept": "application/json",
                    "Content-Type": "application/json",
                },
            ),
        ],
    )

    active_deployments = client.get_customer_deployments_active_status(
        authorization_uk, customer_id
    )

    assert len(active_deployments) == 2
    assert active_deployments == active_deployments_response


def test_preview_reseller_change(
    requests_mocker, settings, adobe_client_factory, adobe_authorizations_file
):
    authorization_uk = adobe_authorizations_file["authorizations"][0]["authorization_uk"]
    seller_id = adobe_authorizations_file["authorizations"][0]["resellers"][0]["seller_id"]
    change_code = "a-change-code"
    admin_email = "admin@example.com"

    client, authorization, api_token = adobe_client_factory()

    expected_response = {"result": "preview-ok"}

    requests_mocker.post(
        urljoin(
            settings.EXTENSION_CONFIG["ADOBE_API_BASE_URL"],
            "/v3/transfers",
        ),
        status=200,
        json=expected_response,
        match=[
            matchers.header_matcher(
                {
                    "X-Api-Key": authorization.client_id,
                    "Authorization": f"Bearer {api_token.token}",
                    "Accept": "application/json",
                    "Content-Type": "application/json",
                },
            ),
            matchers.json_params_matcher({
                "type": "RESELLER_CHANGE",
                "action": "PREVIEW",
                "approvalCode": change_code,
                "resellerId": (
                    adobe_authorizations_file["authorizations"][0]["resellers"][0]["id"]
                ),
                "requestedBy": admin_email,
            }),
        ],
    )

    result = client.preview_reseller_change(authorization_uk, seller_id, change_code, admin_email)
    assert result == expected_response


def test_preview_reseller_change_bad_request(
    requests_mocker,
    settings,
    adobe_client_factory,
    adobe_authorizations_file,
    adobe_api_error_factory,
):
    authorization_uk = adobe_authorizations_file["authorizations"][0]["authorization_uk"]
    seller_id = adobe_authorizations_file["authorizations"][0]["resellers"][0]["seller_id"]
    change_code = "a-change-code"
    admin_email = "admin@example.com"

    client, _, _ = adobe_client_factory()

    error = adobe_api_error_factory("1234", "An error")

    requests_mocker.post(
        urljoin(
            settings.EXTENSION_CONFIG["ADOBE_API_BASE_URL"],
            "/v3/transfers",
        ),
        status=400,
        json=error,
    )

    with pytest.raises(Exception) as cv:
        client.preview_reseller_change(authorization_uk, seller_id, change_code, admin_email)

    assert repr(cv.value) == str(error)



def test_commit_reseller_change(
    requests_mocker, settings, adobe_client_factory, adobe_authorizations_file
):
    """
    Tests the preview of a reseller change.
    """
    authorization_uk = adobe_authorizations_file["authorizations"][0]["authorization_uk"]
    client, authorization, api_token = adobe_client_factory()
    expected_response = {
        "transferId": "P110044419",
        "customerId": "P1005243296",
        "resellerId": "P1000084165",
        "creationDate": "2025-07-29T08:50:39Z",
        "status": "1000",
        "totalCount": 1,
        "lineItems": [
            {
                "lineItemNumber": 1,
                "offerId": "65304520CA01A12",
                "quantity": 50,
                "subscriptionId": "22d866a3ea47f681030002fabf3470NA",
                "renewalDate": "2026-07-29T07:00:00.000+00:00"
            }
        ],
        "benefits": [
            {
                "type": "THREE_YEAR_COMMIT",
                "commitment": None,
                "commitmentRequest": {
                    "status": "REQUESTED",
                    "minimumQuantities": [
                        {
                            "offerType": "LICENSE",
                            "quantity": 50
                        }
                    ]
                },
                "recommitmentRequest": None
            }
        ],
        "discounts": [
            {
                "discountCode": None,
                "level": "03",
                "offerType": "LICENSE"
            }
        ]
    }

    transfer_id = "a-transfer-id"

    requests_mocker.get(
        urljoin(
            settings.EXTENSION_CONFIG["ADOBE_API_BASE_URL"],
            f"/v3/transfers/{transfer_id}",
        ),
        status=200,
        json=expected_response,
        match=[
            matchers.header_matcher(
                {
                    "X-Api-Key": authorization.client_id,
                    "Authorization": f"Bearer {api_token.token}",
                    "Accept": "application/json",
                    "Content-Type": "application/json",
                },
            )
        ],
    )

    result = client.get_reseller_transfer(
        authorization_uk, transfer_id
    )
    assert result == expected_response
