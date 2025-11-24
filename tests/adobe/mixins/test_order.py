from urllib.parse import urljoin

import pytest
from responses import matchers

from adobe_vipm.adobe.constants import ORDER_TYPE_PREVIEW, AdobeStatus
from adobe_vipm.adobe.errors import AdobeAPIError, AdobeError
from adobe_vipm.adobe.utils import to_adobe_line_id


def test_get_preview_order(
    adobe_client_factory, order_factory, requests_mocker, settings, adobe_order_factory, mock_uuid4
):
    mocked_client, authorization, _ = adobe_client_factory()
    adobe_customer_id = "test-customer"
    order = order_factory()
    payload = {
        "externalReferenceId": "ORD-0792-5000-2253-4210",
        "lineItems": [
            {
                "currencyCode": "USD",
                "deploymentId": "a_deployment_id",
                "extLineItemNumber": 1,
                "offerId": "65304578CA01A12",
                "quantity": 5,
            }
        ],
        "orderType": "PREVIEW",
    }
    requests_mocker.post(
        urljoin(
            settings.EXTENSION_CONFIG["ADOBE_API_BASE_URL"],
            "/v3/customers/test-customer/orders",
        ),
        status=200,
        json=adobe_order_factory(order_type=ORDER_TYPE_PREVIEW),
        match=[
            matchers.json_params_matcher(
                {
                    "externalReferenceId": order["id"],
                    "orderType": "PREVIEW",
                    "lineItems": [
                        {
                            "extLineItemNumber": to_adobe_line_id(order["lines"][0]["id"]),
                            "offerId": "65304578CA01A12",
                            "quantity": 5,
                            "deploymentId": "a_deployment_id",
                            "currencyCode": "USD",
                        },
                    ],
                },
            ),
            matchers.query_param_matcher({"fetch-price": "true"}),
        ],
    )

    result = mocked_client.get_preview_order(authorization, adobe_customer_id, payload)

    assert result == {
        "currencyCode": "USD",
        "externalReferenceId": "external_id",
        "lineItems": [
            {
                "extLineItemNumber": 1,
                "offerId": "65304578CA01A12",
                "pricing": {
                    "discountedPartnerPrice": 849.16,
                    "lineItemPartnerPrice": 846.83,
                    "netPartnerPrice": 846.83,
                    "partnerPrice": 875.16,
                },
                "quantity": 170,
            }
        ],
        "orderType": "PREVIEW",
    }


def test_get_preview_order_discounts(
    adobe_client_factory,
    requests_mocker,
    settings,
    order_preview_discounts_resp_factory,
    preview_discounts_payload_factory,
):
    mocked_client, authorization, _ = adobe_client_factory()
    adobe_customer_id = "test-customer"
    payload = preview_discounts_payload_factory()
    second_payload = preview_discounts_payload_factory()
    second_payload["lineItems"][1]["flexDiscountCodes"] = []
    discounts_resp_ok = order_preview_discounts_resp_factory()
    del discounts_resp_ok["lineItems"][1]["flexDiscounts"]
    for payload_to_match, json_body in (
        (payload, order_preview_discounts_resp_factory()),
        (second_payload, discounts_resp_ok),
    ):
        requests_mocker.post(
            urljoin(
                settings.EXTENSION_CONFIG["ADOBE_API_BASE_URL"],
                "/v3/customers/test-customer/orders",
            ),
            json=json_body,
            match=[
                matchers.json_params_matcher(payload_to_match),
                matchers.query_param_matcher({"fetch-price": "true"}),
            ],
        )

    result = mocked_client.get_preview_order(authorization, adobe_customer_id, payload)

    assert result == {
        "creationDate": "2025-09-30T11:01:45Z",
        "currencyCode": "USD",
        "customerId": "P1005267002",
        "externalReferenceId": "ORD-0792-5000-2253-4210",
        "lineItems": [
            {
                "currencyCode": "USD",
                "extLineItemNumber": 2,
                "flexDiscounts": [
                    {
                        "code": "EASTER_26",
                        "id": "a21beee6-c07e-43e1-b5b7-fbef9644dbbb",
                        "result": "SUCCESS",
                    }
                ],
                "offerId": "65304767CA03A12",
                "pricing": {
                    "discountedPartnerPrice": 849.16,
                    "lineItemPartnerPrice": 846.83,
                    "netPartnerPrice": 846.83,
                    "partnerPrice": 875.16,
                },
                "proratedDays": 364,
                "quantity": 1,
                "status": "",
                "subscriptionId": "",
            },
            {
                "currencyCode": "USD",
                "extLineItemNumber": 3,
                "offerId": "65304768CA03A12",
                "pricing": {
                    "discountedPartnerPrice": 849.16,
                    "lineItemPartnerPrice": 846.83,
                    "netPartnerPrice": 846.83,
                    "partnerPrice": 875.16,
                },
                "proratedDays": 364,
                "quantity": 1,
                "status": "",
                "subscriptionId": "",
            },
            {
                "currencyCode": "USD",
                "extLineItemNumber": 4,
                "offerId": "65304839CA03A12",
                "pricing": {
                    "discountedPartnerPrice": 1363.56,
                    "lineItemPartnerPrice": 1359.82,
                    "netPartnerPrice": 1359.82,
                    "partnerPrice": 1363.56,
                },
                "proratedDays": 364,
                "quantity": 1,
                "status": "",
                "subscriptionId": "",
            },
        ],
        "orderId": "",
        "orderType": "PREVIEW",
        "pricingSummary": [{"currencyCode": "USD", "totalLineItemPartnerPrice": 2206.65}],
        "referenceOrderId": "",
        "status": "",
    }


def test_get_preview_order_too_many_failed_discounts(
    adobe_client_factory,
    requests_mocker,
    settings,
    order_preview_discounts_resp_factory,
    preview_discounts_payload_factory,
    mock_send_exception,
):
    mocked_client, authorization, _ = adobe_client_factory()
    adobe_customer_id = "test-customer"
    payload = preview_discounts_payload_factory()
    requests_mocker.post(
        urljoin(
            settings.EXTENSION_CONFIG["ADOBE_API_BASE_URL"],
            "/v3/customers/test-customer/orders",
        ),
        json=order_preview_discounts_resp_factory(),
        match=[
            matchers.json_params_matcher(payload),
            matchers.query_param_matcher({"fetch-price": "true"}),
        ],
    )

    with pytest.raises(AdobeError):
        mocked_client.get_preview_order(authorization, adobe_customer_id, payload)

    mock_send_exception.assert_called_once_with(
        "Failed applying discount codes",
        "After 5 attempts still finding failed discount codes: {'BLACK_FRIDAY'}.",
    )


# ???: there isn't asserts
def test_get_preview_order_not_qualified(
    adobe_client_factory,
    requests_mocker,
    settings,
    order_preview_discounts_resp_factory,
    preview_discounts_payload_factory,
):
    mocked_client, authorization, _ = adobe_client_factory()
    payload = preview_discounts_payload_factory()
    second_payload = preview_discounts_payload_factory()
    second_payload["lineItems"][1]["flexDiscountCodes"] = []
    discounts_resp_ok = order_preview_discounts_resp_factory()
    del discounts_resp_ok["lineItems"][1]["flexDiscounts"]
    for payload_to_match, response in (
        (
            payload,
            {
                "body": AdobeAPIError(
                    status_code=int(AdobeStatus.CUSTOMER_NOT_QUALIFIED_FOR_FLEX_DISCOUNT),
                    payload={
                        "code": "2141",
                        "message": "Customer is not qualified for the Flexible Discount",
                        "additionalDetails": ["Line Item: 3, Reason: Invalid Flexible Discount"],
                    },
                )
            },
        ),
        (
            second_payload,
            {"json": discounts_resp_ok},
        ),
    ):
        requests_mocker.post(
            urljoin(
                settings.EXTENSION_CONFIG["ADOBE_API_BASE_URL"],
                "/v3/customers/test-customer/orders",
            ),
            match=[
                matchers.json_params_matcher(payload_to_match),
                matchers.query_param_matcher({"fetch-price": "true"}),
            ],
            **response,
        )

    mocked_client.get_preview_order(authorization, "test-customer", payload)  # act


def test_get_preview_order_unexpected_message(
    adobe_client_factory,
    requests_mocker,
    settings,
    order_preview_discounts_resp_factory,
    preview_discounts_payload_factory,
):
    mocked_client, authorization, _ = adobe_client_factory()
    payload_to_match = preview_discounts_payload_factory()
    requests_mocker.post(
        urljoin(
            settings.EXTENSION_CONFIG["ADOBE_API_BASE_URL"],
            "/v3/customers/test-customer/orders",
        ),
        match=[
            matchers.json_params_matcher(payload_to_match),
            matchers.query_param_matcher({"fetch-price": "true"}),
        ],
        body=AdobeAPIError(
            status_code=int(AdobeStatus.CUSTOMER_NOT_QUALIFIED_FOR_FLEX_DISCOUNT),
            payload={
                "code": "2141",
                "message": "Customer is not qualified for the Flexible Discount",
                "additionalDetails": ["line item 1, Reason: Invalid Flexible Discount"],
            },
        ),
    )

    with pytest.raises(AdobeError) as err:
        mocked_client.get_preview_order(authorization, "test-customer", payload_to_match)

    assert str(err.value) == (
        "Can't parse Adobe error message: '['line item 1, Reason: Invalid Flexible "
        "Discount']'. Expected format example: 'Line Item: 2, Reason: Invalid "
        "Flexible Discount'"
    )


def test_get_preview_order_line_item(
    settings, adobe_client_factory, mock_get_adobe_product_by_marketplace_sku, caplog
):
    mocked_client, _, _ = adobe_client_factory()
    line = {
        "id": "ALI-2119-4550-8674-5962-0001",
        "item": {
            "externalIds": {"vendor": "65304578CA"},
            "id": "ITM-1234-1234-1234-0001",
            "name": "Awesome product",
        },
        "oldQuantity": 8,
        "price": {"unitPP": 1234.55},
        "quantity": 12,
        "subscription": {
            "id": "SUB-1000-2000-3000",
            "name": "Subscription for Acrobat Pro for Teams; Multi Language",
            "status": "Active",
        },
    }

    result = mocked_client._get_preview_order_line_item(line, "65304578CA", 2, "FLEX_DISCOUNT")

    assert result == {
        "extLineItemNumber": 1,
        "flexDiscountCodes": ["FLEX_DISCOUNT"],
        "offerId": "65304578CA01A12",
        "quantity": 2,
    }
