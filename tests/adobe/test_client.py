import json
from datetime import datetime, timedelta
from hashlib import sha256
from urllib.parse import urljoin

import pytest
import requests
from freezegun import freeze_time
from responses import matchers

from adobe_vipm.adobe.client import AdobeClient, get_adobe_client
from adobe_vipm.adobe.config import Config
from adobe_vipm.adobe.constants import (
    ORDER_TYPE_NEW,
    ORDER_TYPE_PREVIEW,
    ORDER_TYPE_PREVIEW_RENEWAL,
    ORDER_TYPE_RETURN,
    STATUS_ORDER_INACTIVE_CUSTOMER,
    STATUS_PENDING,
    STATUS_PROCESSED,
)
from adobe_vipm.adobe.dataclasses import APIToken, Authorization
from adobe_vipm.adobe.errors import AdobeError
from adobe_vipm.adobe.utils import join_phone_number, to_adobe_line_id


def test_create_reseller_account(
    mocker,
    settings,
    requests_mocker,
    adobe_authorizations_file,
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
    distributor_id = adobe_authorizations_file["authorizations"][0]["distributor_id"]
    authorization_uk = adobe_authorizations_file["authorizations"][0][
        "authorization_uk"
    ]

    client, authorization, api_token = adobe_client_factory()
    payload = {
        "externalReferenceId": "external_id",
        "distributorId": distributor_id,
        "companyProfile": {
            "companyName": reseller_data["companyName"],
            "preferredLanguage": reseller_data["preferredLanguage"],
            "address": {
                "country": reseller_data["address"]["country"],
                "region": reseller_data["address"]["state"],
                "city": reseller_data["address"]["city"],
                "addressLine1": reseller_data["address"]["addressLine1"],
                "addressLine2": reseller_data["address"]["addressLine2"],
                "postalCode": reseller_data["address"]["postalCode"],
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

    reseller_id = client.create_reseller_account(
        authorization_uk, "external_id", reseller_data
    )
    assert reseller_id == "a-reseller-id"


def test_create_reseller_account_bad_request(
    requests_mocker,
    settings,
    adobe_authorizations_file,
    reseller_data,
    adobe_api_error_factory,
    adobe_client_factory,
):
    """
    Test the call to Adobe API to create a reseller when the response is 400 bad request.
    """
    authorization_uk = adobe_authorizations_file["authorizations"][0][
        "authorization_uk"
    ]

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
    """
    Test the call to Adobe API to create a customer.
    """
    mocker.patch(
        "adobe_vipm.adobe.client.uuid4",
        return_value="uuid-1",
    )
    seller_id = adobe_authorizations_file["authorizations"][0]["resellers"][0][
        "seller_id"
    ]
    reseller_id = adobe_authorizations_file["authorizations"][0]["resellers"][0]["id"]
    authorization_uk = adobe_authorizations_file["authorizations"][0][
        "authorization_uk"
    ]

    client, authorization, api_token = adobe_client_factory()

    company_name = f"{customer_data['companyName']} (external_id)"

    payload = {
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
                "postalCode": customer_data["address"]["postalCode"],
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
        authorization_uk, seller_id, "external_id", customer_data
    )
    assert customer_id == "A-customer-id"


def test_create_customer_account_bad_request(
    requests_mocker,
    settings,
    adobe_authorizations_file,
    customer_data,
    adobe_api_error_factory,
    adobe_client_factory,
):
    """
    Test the call to Adobe API to create a customer when the response is 400 bad request.
    """
    authorization_uk = adobe_authorizations_file["authorizations"][0][
        "authorization_uk"
    ]
    seller_id = adobe_authorizations_file["authorizations"][0]["resellers"][0][
        "seller_id"
    ]

    client, _, _ = adobe_client_factory()

    error = adobe_api_error_factory("1234", "An error")

    requests_mocker.post(
        urljoin(settings.EXTENSION_CONFIG["ADOBE_API_BASE_URL"], "/v3/customers"),
        status=400,
        json=error,
    )

    with pytest.raises(AdobeError) as cv:
        client.create_customer_account(
            authorization_uk, seller_id, "external_id", customer_data
        )

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
    settings,
    requests_mocker,
    adobe_config_file,
    adobe_authorizations_file,
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
    authorization_uk = adobe_authorizations_file["authorizations"][0][
        "authorization_uk"
    ]
    adobe_full_sku = adobe_config_file["skus_mapping"][0]["sku"]
    customer_id = "a-customer"

    client, authorization, api_token = adobe_client_factory()

    order = order_factory(
        lines=lines_factory(old_quantity=old_quantity, quantity=quantity)
    )
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
                    "currencyCode": "USD",
                    "orderType": "PREVIEW",
                    "lineItems": [
                        {
                            "extLineItemNumber": to_adobe_line_id(
                                order["lines"][0]["id"]
                            ),
                            "offerId": adobe_full_sku,
                            "quantity": expected_quantity,
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
    )
    assert preview_order == {
        "orderId": "adobe-order-id",
    }


def test_create_preview_order_bad_request(
    requests_mocker,
    settings,
    adobe_authorizations_file,
    adobe_api_error_factory,
    adobe_client_factory,
    order,
):
    """
    Test the call to Adobe API to create a preview order when the response is 400 bad request.
    """
    order["lines"][0]["item"]["externalIds"] = {"vendor": "65304578CA"}
    authorization_uk = adobe_authorizations_file["authorizations"][0][
        "authorization_uk"
    ]
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
        client.create_preview_order(
            authorization_uk,
            customer_id,
            order["id"],
            order["lines"],
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
    """
    Test the call to Adobe API to create a new order.
    """
    mocker.patch(
        "adobe_vipm.adobe.client.uuid4",
        return_value="uuid-1",
    )
    authorization_uk = adobe_authorizations_file["authorizations"][0][
        "authorization_uk"
    ]
    customer_id = "a-customer"

    client, authorization, api_token = adobe_client_factory()

    adobe_order = adobe_order_factory(ORDER_TYPE_NEW, external_id="mpt-order-id")

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
                    "x-correlation-id": adobe_order["externalReferenceId"],
                },
            ),
            matchers.json_params_matcher(adobe_order),
        ],
    )

    new_order = client.create_new_order(
        authorization_uk,
        customer_id,
        adobe_order,
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
    """
    Test the call to Adobe API to create a new order when the response is 400 bad request.
    """
    authorization_uk = adobe_authorizations_file["authorizations"][0][
        "authorization_uk"
    ]
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
    """
    Test the call to Adobe API to create a preview renewal.
    """
    mocker.patch(
        "adobe_vipm.adobe.client.uuid4",
        side_effect=["uuid-1", "uuid-2"],
    )
    authorization_uk = adobe_authorizations_file["authorizations"][0][
        "authorization_uk"
    ]
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
    """
    Test the call to Adobe API to create a preview renewal when the response is 400 bad request.
    """
    authorization_uk = adobe_authorizations_file["authorizations"][0][
        "authorization_uk"
    ]
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


def test_get_order(
    requests_mocker, settings, adobe_client_factory, adobe_authorizations_file
):
    """
    Tests the retrieval of an order.
    """
    authorization_uk = adobe_authorizations_file["authorizations"][0][
        "authorization_uk"
    ]
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
    """
    Tests the retrieval of an order when it doesn't exist.
    """
    authorization_uk = adobe_authorizations_file["authorizations"][0][
        "authorization_uk"
    ]
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
    """
    Tests the retrieval of a subscription.
    """
    authorization_uk = adobe_authorizations_file["authorizations"][0][
        "authorization_uk"
    ]
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

    assert client.get_subscription(authorization_uk, customer_id, sub_id) == {
        "a": "subscription"
    }


def test_get_subscription_not_found(
    requests_mocker,
    settings,
    adobe_client_factory,
    adobe_authorizations_file,
    adobe_api_error_factory,
):
    """
    Tests the retrieval of a subscription when it doesn't exist.
    """
    authorization_uk = adobe_authorizations_file["authorizations"][0][
        "authorization_uk"
    ]
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


def test_search_new_and_returned_orders_by_sku_line_number(
    requests_mocker,
    settings,
    adobe_client_factory,
    adobe_config_file,
    adobe_authorizations_file,
    adobe_order_factory,
    adobe_items_factory,
):
    """
    Tests the call to search the last processed order by SKU for a given
    customer.
    """
    authorization_uk = adobe_authorizations_file["authorizations"][0][
        "authorization_uk"
    ]
    customer_id = "a-customer"
    vendor_external_id = adobe_config_file["skus_mapping"][0]["vendor_external_id"]

    client, authorization, api_token = adobe_client_factory()

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
            settings.EXTENSION_CONFIG["ADOBE_API_BASE_URL"],
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
                    "X-Api-Key": authorization.client_id,
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
            settings.EXTENSION_CONFIG["ADOBE_API_BASE_URL"],
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
                    "X-Api-Key": authorization.client_id,
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
            settings.EXTENSION_CONFIG["ADOBE_API_BASE_URL"],
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
                    "X-Api-Key": authorization.client_id,
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
            settings.EXTENSION_CONFIG["ADOBE_API_BASE_URL"],
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
                    "X-Api-Key": authorization.client_id,
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
        authorization_uk,
        customer_id,
        vendor_external_id,
        "ALI-2119-4550-8674-5962-0001",
    )

    assert result == [
        (new_order_1, new_order_1["lineItems"][0], return_order_1),
        (new_order_2, new_order_2["lineItems"][0], None),
        (new_order_3, new_order_3["lineItems"][0], None),
    ]


def test_search_new_and_returned_orders_by_sku_line_number_not_found(
    requests_mocker,
    settings,
    adobe_client_factory,
    adobe_config_file,
    adobe_authorizations_file,
):
    """
    Tests the call to search the last processed order by SKU for a given
    customer when no order is found.
    """
    authorization_uk = adobe_authorizations_file["authorizations"][0][
        "authorization_uk"
    ]
    customer_id = "a-customer"
    vendor_external_id = adobe_config_file["skus_mapping"][0]["vendor_external_id"]

    client, authorization, api_token = adobe_client_factory()

    requests_mocker.get(
        urljoin(
            settings.EXTENSION_CONFIG["ADOBE_API_BASE_URL"],
            f"/v3/customers/{customer_id}/orders",
        ),
        status=200,
        json={"totalCount": 0, "items": [], "links": {}},
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
                    "order-type": ORDER_TYPE_NEW,
                    "limit": 100,
                    "offset": 0,
                },
            ),
        ],
    )

    results = client.search_new_and_returned_orders_by_sku_line_number(
        authorization_uk,
        customer_id,
        vendor_external_id,
        "ALI-2119-4550-8674-5962-0001",
    )

    assert results == []


def test_create_return_order(
    mocker,
    settings,
    requests_mocker,
    adobe_client_factory,
    adobe_authorizations_file,
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
    authorization_uk = adobe_authorizations_file["authorizations"][0][
        "authorization_uk"
    ]
    customer_id = "a-customer"

    client, authorization, api_token = adobe_client_factory()

    returning_order = adobe_order_factory(
        ORDER_TYPE_NEW,
        external_id="ORD-1234",
        order_id="returning-order-id",
        status=STATUS_PROCESSED,
    )

    returning_item = returning_order["lineItems"][0]

    extReferenceId = returning_order["externalReferenceId"]
    extItemNumber = returning_item["extLineItemNumber"]
    expected_external_id = f"{extReferenceId}-{extItemNumber}"

    expected_body = adobe_order_factory(
        ORDER_TYPE_RETURN,
        reference_order_id=returning_order["orderId"],
        external_id=expected_external_id,
        items=adobe_items_factory(),
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
    """
    Test the call to Adobe API to create a return order when the response is 400 bad request.
    """
    authorization_uk = adobe_authorizations_file["authorizations"][0][
        "authorization_uk"
    ]
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
    returning_order = adobe_order_factory(ORDER_TYPE_NEW, status=STATUS_PROCESSED)

    with pytest.raises(AdobeError) as cv:
        client.create_return_order(
            authorization_uk,
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
    requests_mocker,
    settings,
    adobe_client_factory,
    adobe_authorizations_file,
    update_params,
):
    """
    Tests the update of a subscription.
    """
    authorization_uk = adobe_authorizations_file["authorizations"][0][
        "authorization_uk"
    ]
    customer_id = "a-customer"
    sub_id = "a-sub-id"

    client, authorization, api_token = adobe_client_factory()

    body_to_match = {
        "autoRenewal": {
            "enabled": update_params.get("auto_renewal", True),
        },
    }
    if "quantity" in update_params:
        body_to_match["autoRenewal"]["quantity"] = update_params["quantity"]

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

    assert client.update_subscription(
        authorization_uk,
        customer_id,
        sub_id,
        **update_params,
    ) == {"a": "subscription"}


def test_update_subscription_not_found(
    requests_mocker,
    settings,
    adobe_client_factory,
    adobe_authorizations_file,
    adobe_api_error_factory,
):
    """
    Tests the update of a subscription when it doesn't exist.
    """
    authorization_uk = adobe_authorizations_file["authorizations"][0][
        "authorization_uk"
    ]
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
    """
    Tests the retrieval subscriptions for a transfer given a membership id.
    """
    authorization_uk = adobe_authorizations_file["authorizations"][0][
        "authorization_uk"
    ]
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
        ],
    )

    assert client.preview_transfer(authorization_uk, membership_id) == {
        "a": "transfer-preview"
    }


def test_preview_transfer_not_found(
    requests_mocker,
    settings,
    adobe_client_factory,
    adobe_authorizations_file,
    adobe_api_error_factory,
):
    """
    Tests the retrieval subscriptions for a transfer given a membership id when they don't exist.
    """
    authorization_uk = adobe_authorizations_file["authorizations"][0][
        "authorization_uk"
    ]
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
    """
    Test the call to Adobe API to create a transfer order.
    """
    mocker.patch(
        "adobe_vipm.adobe.client.uuid4",
        return_value="uuid-1",
    )
    authorization_uk = adobe_authorizations_file["authorizations"][0][
        "authorization_uk"
    ]
    reseller_id = adobe_authorizations_file["authorizations"][0]["resellers"][0]["id"]
    seller_id = adobe_authorizations_file["authorizations"][0]["resellers"][0][
        "seller_id"
    ]
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
    """
    Test the call to Adobe API to create a transfer order when the response is 400 bad request.
    """
    authorization_uk = adobe_authorizations_file["authorizations"][0][
        "authorization_uk"
    ]
    seller_id = adobe_authorizations_file["authorizations"][0]["resellers"][0][
        "seller_id"
    ]
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


def test_get_transfer(
    requests_mocker, settings, adobe_client_factory, adobe_authorizations_file
):
    """
    Tests the retrieval of a transfer order.
    """
    authorization_uk = adobe_authorizations_file["authorizations"][0][
        "authorization_uk"
    ]
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

    assert client.get_transfer(authorization_uk, membership_id, transfer_id) == {
        "a": "transfer"
    }


def test_get_transfer_not_found(
    requests_mocker,
    settings,
    adobe_client_factory,
    adobe_authorizations_file,
    adobe_api_error_factory,
):
    """
    Tests the retrieval of a transfer when it doesn't exist.
    """
    authorization_uk = adobe_authorizations_file["authorizations"][0][
        "authorization_uk"
    ]
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


def test_get_auth_token(
    requests_mocker, settings, mock_adobe_config, adobe_config_file
):
    """
    Test issuing of authentication token.
    """
    authorization = Authorization(
        authorization_uk="auth_uk",
        authorization_id="auth_id",
        name="test",
        client_id="client_id",
        client_secret="client_secret",
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
                    "scope": ",".join(Config.REQUIRED_API_SCOPES),
                },
            ),
        ],
    )

    client = AdobeClient()
    with freeze_time("2024-01-01 12:00:00"):
        token = client._get_auth_token(authorization)
        assert isinstance(token, APIToken)
        assert token.token == "an-access-token"
        assert token.expires == datetime.now() + timedelta(seconds=83000 - 180)
        assert client._token_cache[authorization] == token


def test_get_auth_token_error(
    requests_mocker, settings, mock_adobe_config, adobe_config_file
):
    """
    Test error issuing of authentication token.
    """
    authorization = Authorization(
        authorization_uk="auth_uk",
        authorization_id="auth_id",
        name="test",
        client_id="client_id",
        client_secret="client_secret",
        currency="USD",
        distributor_id="distributor_id",
    )

    requests_mocker.post(
        settings.EXTENSION_CONFIG["ADOBE_AUTH_ENDPOINT_URL"],
        status=403,
    )

    client = AdobeClient()
    with pytest.raises(requests.HTTPError):
        client._get_auth_token(authorization)


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


def test_get_subscriptions(
    requests_mocker, settings, adobe_client_factory, adobe_authorizations_file
):
    """
    Tests the retrieval of all the subscriptions of a given customer.
    """
    authorization_uk = adobe_authorizations_file["authorizations"][0][
        "authorization_uk"
    ]
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
