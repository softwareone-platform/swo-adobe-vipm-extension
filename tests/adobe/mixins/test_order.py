from urllib.parse import urljoin

import pytest
from responses import matchers

from adobe_vipm.adobe.constants import ORDER_TYPE_PREVIEW, AdobeStatus
from adobe_vipm.adobe.errors import AdobeAPIError, AdobeError
from adobe_vipm.adobe.mixins.errors import AdobeCreatePreviewError
from adobe_vipm.adobe.utils import to_adobe_line_id
from adobe_vipm.flows.constants import MARKET_SEGMENT_COMMERCIAL
from adobe_vipm.flows.context import Context


def test_create_preview_order_processing_upsize_lines_error(
    mocker,
    mock_get_adobe_product_by_marketplace_sku,
    mock_order,
    mock_mpt_client,
    adobe_authorizations_file,
    adobe_api_error_factory,
    adobe_client_factory,
    flex_discounts_factory,
    requests_mocker,
):
    mocked_client, _, _ = adobe_client_factory()
    mock_get_flex_discounts_per_base_offer = mocker.patch.object(
        mocked_client, "get_flex_discounts_per_base_offer", return_value=flex_discounts_factory()
    )
    mock_get_subscriptions_for_offers = mocker.patch.object(
        mocked_client,
        "get_subscriptions_for_offers",
        return_value=[
            {
                "subscriptionId": "fake-sub-id",
                "status": "1000",
                "autoRenewal": {"enabled": False},
                "offerId": "fake-offer-id",
            }
        ],
    )
    context = Context(
        order=mock_order,
        order_id="order-id",
        authorization_id=adobe_authorizations_file["authorizations"][0]["authorization_uk"],
        new_lines=[],
        upsize_lines=mock_order["lines"],
        adobe_customer_id="fake-customer-id",
    )

    with pytest.raises(AdobeCreatePreviewError, match="Subscription has not been found in Adobe"):
        mocked_client.create_preview_order(context)

    mock_get_flex_discounts_per_base_offer.assert_called_once()
    mock_get_subscriptions_for_offers.assert_called_once()


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


def test_get_preview_order_not_qualified(
    adobe_client_factory,
    requests_mocker,
    settings,
    order_preview_discounts_resp_factory,
    preview_discounts_payload_factory,
    caplog,
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

    assert (
        "2141 - Customer is not qualified for the Flexible Discount: Line Item: 3, Reason: Invalid "
        "Flexible Discount" in caplog.messages
    )


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

    result = mocked_client._get_preview_order_line_item(
        line, "65304578CA", 2, "FLEX_DISCOUNT", MARKET_SEGMENT_COMMERCIAL
    )

    assert result == {
        "extLineItemNumber": 1,
        "flexDiscountCodes": ["FLEX_DISCOUNT"],
        "offerId": "65304578CA01A12",
        "quantity": 2,
    }


def test_get_flex_discounts_per_base_offer_invalid_country(
    adobe_client_factory,
    requests_mocker,
    settings,
    order_preview_discounts_resp_factory,
    preview_discounts_payload_factory,
    mock_order,
    flex_discounts_factory,
    adobe_api_error_factory,
):
    mocked_client, authorization, _ = adobe_client_factory()
    payload = preview_discounts_payload_factory()
    payload["lineItems"][1]["flexDiscountCodes"] = []
    response_json = order_preview_discounts_resp_factory()
    del response_json["lineItems"][1]["flexDiscounts"]
    requests_mocker.get(
        urljoin(settings.EXTENSION_CONFIG["ADOBE_API_BASE_URL"], "/v3/flex-discounts"),
        status=400,
        json=adobe_api_error_factory(
            AdobeStatus.INVALID_COUNTRY_FOR_PARTNER, "Invalid Country for Partner"
        ),
        match=[
            matchers.query_param_matcher({
                "market-segment": "COM",
                "country": "US",
                "offer-ids": "99999999CA01A12,99999999CA01A12",
            })
        ],
    )
    context = Context(order=mock_order, market_segment="COM")

    flex_discounts = mocked_client.get_flex_discounts_per_base_offer(
        authorization,
        context,
        ("99999999CA01A12", "99999999CA01A12"),
    )  # act

    assert flex_discounts == {}


def test_get_flex_discounts_per_base_offer_error(
    adobe_client_factory,
    requests_mocker,
    settings,
    order_preview_discounts_resp_factory,
    preview_discounts_payload_factory,
    mock_order,
    flex_discounts_factory,
    adobe_api_error_factory,
):
    mocked_client, authorization, _ = adobe_client_factory()
    payload = preview_discounts_payload_factory()
    payload["lineItems"][1]["flexDiscountCodes"] = []
    response_json = order_preview_discounts_resp_factory()
    del response_json["lineItems"][1]["flexDiscounts"]
    requests_mocker.get(
        urljoin(settings.EXTENSION_CONFIG["ADOBE_API_BASE_URL"], "/v3/flex-discounts"),
        status=400,
        json=adobe_api_error_factory(AdobeStatus.INTERNAL_SERVER_ERROR, "Internal server error"),
        match=[
            matchers.query_param_matcher({
                "market-segment": "COM",
                "country": "US",
                "offer-ids": "99999999CA01A12,99999999CA01A12",
            })
        ],
    )
    context = Context(order=mock_order, market_segment="COM")

    with pytest.raises(AdobeError):
        mocked_client.get_flex_discounts_per_base_offer(
            authorization,
            context,
            ("99999999CA01A12", "99999999CA01A12"),
        )  # act
