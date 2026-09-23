import json
from hashlib import sha256
from urllib.parse import urljoin

import pytest
import responses
from responses import matchers

from adobe_vipm.adobe.constants import (
    ORDER_TYPE_PREVIEW,
    ORDER_TYPE_PREVIEW_SWITCH,
    ORDER_TYPE_SWITCH,
    AdobeErrorCode,
)
from adobe_vipm.adobe.dataclasses import FlexDiscountCascade
from adobe_vipm.adobe.errors import AdobeAPIError, AdobeError, AdobeHttpError
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
    requests_mocker,
):
    mocked_client, _, _ = adobe_client_factory()
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
    del second_payload["lineItems"][1]["flexDiscountCodes"]
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


def _reject_requested_code(order_preview_discounts_resp_factory, accepted_code=None):
    """Build a responses callback that rejects whatever code the second line proposes."""

    def callback(request):
        codes = json.loads(request.body)["lineItems"][1].get("flexDiscountCodes") or []
        response_json = order_preview_discounts_resp_factory()
        response_json["lineItems"][1]["flexDiscounts"] = [
            {"code": code, "result": "SUCCESS" if code == accepted_code else "FAILURE"}
            for code in codes
        ]
        return 200, {}, json.dumps(response_json)

    return callback


@pytest.mark.parametrize("accepted_code", [None, "CODE_12"])
def test_get_preview_order_exhausts_ranked_candidates(
    adobe_client_factory,
    requests_mocker,
    settings,
    order_preview_discounts_resp_factory,
    preview_discounts_payload_factory,
    mock_send_exception,
    accepted_code,
):
    mocked_client, authorization, _ = adobe_client_factory()
    adobe_customer_id = "test-customer"
    payload = preview_discounts_payload_factory()
    del payload["lineItems"][0]["flexDiscountCodes"]
    candidates = [f"CODE_{index}" for index in range(1, 13)]
    payload["lineItems"][1]["flexDiscountCodes"] = [candidates[0]]
    cascade = FlexDiscountCascade(candidates={3: list(candidates)})
    requests_mocker.add_callback(
        responses.POST,
        urljoin(
            settings.EXTENSION_CONFIG["ADOBE_API_BASE_URL"],
            "/v3/customers/test-customer/orders",
        ),
        callback=_reject_requested_code(order_preview_discounts_resp_factory, accepted_code),
        content_type="application/json",
    )

    mocked_client.get_preview_order(authorization, adobe_customer_id, payload, cascade)  # act

    assert cascade.rejections == {3: [code for code in candidates if code != accepted_code]}
    assert cascade.selection == ({3: accepted_code} if accepted_code else {})
    assert len(requests_mocker.calls) == len(cascade.rejections[3]) + 1
    mock_send_exception.assert_not_called()


def test_get_preview_order_cascades_to_next_candidate(
    adobe_client_factory,
    requests_mocker,
    settings,
    order_preview_discounts_resp_factory,
    preview_discounts_payload_factory,
):
    mocked_client, authorization, _ = adobe_client_factory()
    payload = preview_discounts_payload_factory()
    second_payload = preview_discounts_payload_factory()
    second_payload["lineItems"][1]["flexDiscountCodes"] = ["SPRING_26"]
    discounts_resp_ok = order_preview_discounts_resp_factory()
    discounts_resp_ok["lineItems"][1]["flexDiscounts"][0].update({
        "code": "SPRING_26",
        "result": "SUCCESS",
    })
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
    cascade = FlexDiscountCascade(
        candidates={2: ["EASTER_26"], 3: ["BLACK_FRIDAY", "SPRING_26"]},
    )

    result = mocked_client.get_preview_order(authorization, "test-customer", payload, cascade)

    assert result == discounts_resp_ok
    assert cascade.selection == {2: "EASTER_26", 3: "SPRING_26"}
    assert cascade.rejections == {3: ["BLACK_FRIDAY"]}
    assert payload["lineItems"][1]["flexDiscountCodes"] == ["SPRING_26"]


def test_get_preview_order_ignores_unrequested_rejections(
    adobe_client_factory,
    requests_mocker,
    settings,
    order_preview_discounts_resp_factory,
    preview_discounts_payload_factory,
):
    mocked_client, authorization, _ = adobe_client_factory()
    payload = preview_discounts_payload_factory()
    del payload["lineItems"][1]["flexDiscountCodes"]
    response_json = order_preview_discounts_resp_factory()
    requests_mocker.post(
        urljoin(
            settings.EXTENSION_CONFIG["ADOBE_API_BASE_URL"],
            "/v3/customers/test-customer/orders",
        ),
        json=response_json,
        match=[matchers.json_params_matcher(payload)],
    )
    cascade = FlexDiscountCascade(candidates={2: ["EASTER_26"]})

    result = mocked_client.get_preview_order(authorization, "test-customer", payload, cascade)

    assert result == response_json
    assert cascade.selection == {2: "EASTER_26"}
    assert cascade.rejections == {}


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
    del second_payload["lineItems"][1]["flexDiscountCodes"]
    discounts_resp_ok = order_preview_discounts_resp_factory()
    del discounts_resp_ok["lineItems"][1]["flexDiscounts"]
    for payload_to_match, response in (
        (
            payload,
            {
                "body": AdobeAPIError(
                    status_code=int(AdobeErrorCode.CUSTOMER_NOT_QUALIFIED_FOR_FLEX_DISCOUNT),
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


def test_get_preview_order_not_qualified_on_undiscounted_line(
    adobe_client_factory,
    requests_mocker,
    settings,
    preview_discounts_payload_factory,
):
    mocked_client, authorization, _ = adobe_client_factory()
    payload = preview_discounts_payload_factory()
    requests_mocker.post(
        urljoin(
            settings.EXTENSION_CONFIG["ADOBE_API_BASE_URL"],
            "/v3/customers/test-customer/orders",
        ),
        match=[matchers.json_params_matcher(payload)],
        body=AdobeAPIError(
            status_code=int(AdobeErrorCode.CUSTOMER_NOT_QUALIFIED_FOR_FLEX_DISCOUNT),
            payload={
                "code": "2141",
                "message": "Customer is not qualified for the Flexible Discount",
                "additionalDetails": ["Line Item: 4, Reason: Invalid Flexible Discount"],
            },
        ),
    )

    with pytest.raises(AdobeAPIError) as err:
        mocked_client.get_preview_order(authorization, "test-customer", payload)

    assert err.value.code == "2141"


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
            status_code=int(AdobeErrorCode.CUSTOMER_NOT_QUALIFIED_FOR_FLEX_DISCOUNT),
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


def test_get_flex_discounts_by_code(
    adobe_client_factory,
    adobe_authorizations_file,
    requests_mocker,
    settings,
    flex_discounts_factory,
):
    authorization_uk = adobe_authorizations_file["authorizations"][0]["authorization_uk"]
    mocked_client, _, _ = adobe_client_factory()
    response_json = flex_discounts_factory()
    requests_mocker.get(
        urljoin(settings.EXTENSION_CONFIG["ADOBE_API_BASE_URL"], "/v3/flex-discounts"),
        json=response_json,
        match=[
            matchers.query_param_matcher({
                "market-segment": "COM",
                "country": "US",
                "flex-discount-code": "EASTER_26",
            })
        ],
    )

    result = mocked_client.get_flex_discounts_by_code(
        authorization_uk,
        "COM",
        "US",
        "EASTER_26",
    )  # act

    assert result == response_json["flexDiscounts"]


def test_get_flex_discounts_by_code_error(
    adobe_client_factory,
    adobe_authorizations_file,
    requests_mocker,
    settings,
    adobe_api_error_factory,
):
    authorization_uk = adobe_authorizations_file["authorizations"][0]["authorization_uk"]
    mocked_client, _, _ = adobe_client_factory()
    requests_mocker.get(
        urljoin(settings.EXTENSION_CONFIG["ADOBE_API_BASE_URL"], "/v3/flex-discounts"),
        status=400,
        json=adobe_api_error_factory(AdobeErrorCode.INTERNAL_SERVER_ERROR, "Internal server error"),
    )

    with pytest.raises(AdobeError):
        mocked_client.get_flex_discounts_by_code(
            authorization_uk,
            "COM",
            "US",
            "EASTER_26",
        )  # act


def test_create_switch_preview_order(
    adobe_client_factory,
    adobe_authorizations_file,
    adobe_order_factory,
    requests_mocker,
    settings,
    switch_payload,
):
    authorization_uk = adobe_authorizations_file["authorizations"][0]["authorization_uk"]
    mocked_client, _, _ = adobe_client_factory()
    adobe_preview_order = adobe_order_factory(order_type=ORDER_TYPE_PREVIEW_SWITCH)
    expected_payload = {
        **switch_payload,
        "externalReferenceId": "mpt-order-id",
        "orderType": ORDER_TYPE_PREVIEW_SWITCH,
    }
    expected_payload.pop("recommendationTrackerId")
    requests_mocker.post(
        urljoin(
            settings.EXTENSION_CONFIG["ADOBE_API_BASE_URL"],
            "/v3/customers/a-customer/orders",
        ),
        status=200,
        json=adobe_preview_order,
        match=[
            matchers.header_matcher({
                "x-recommendation-tracker-id": switch_payload["recommendationTrackerId"],
            }),
            matchers.json_params_matcher(expected_payload),
            matchers.query_param_matcher({"fetch-price": "true"}),
        ],
    )

    result = mocked_client.create_switch_preview_order(
        authorization_uk,
        "a-customer",
        "mpt-order-id",
        switch_payload,
    )  # act

    assert result == adobe_preview_order


def test_create_switch_order(
    adobe_client_factory,
    adobe_authorizations_file,
    adobe_order_factory,
    requests_mocker,
    settings,
    switch_payload,
):
    authorization_uk = adobe_authorizations_file["authorizations"][0]["authorization_uk"]
    mocked_client, _, _ = adobe_client_factory()
    adobe_order = adobe_order_factory(order_type=ORDER_TYPE_SWITCH, order_id="an-order-id")
    expected_payload = {
        **switch_payload,
        "externalReferenceId": "mpt-order-id",
        "orderType": ORDER_TYPE_SWITCH,
    }
    expected_payload.pop("recommendationTrackerId")
    correlation_id = sha256(json.dumps(expected_payload).encode()).hexdigest()
    requests_mocker.post(
        urljoin(
            settings.EXTENSION_CONFIG["ADOBE_API_BASE_URL"],
            "/v3/customers/a-customer/orders",
        ),
        status=202,
        json=adobe_order,
        match=[
            matchers.header_matcher({
                "x-correlation-id": correlation_id,
                "x-recommendation-tracker-id": switch_payload["recommendationTrackerId"],
            }),
            matchers.json_params_matcher(expected_payload),
        ],
    )

    result = mocked_client.create_switch_order(
        authorization_uk,
        "a-customer",
        "mpt-order-id",
        switch_payload,
    )  # act

    assert result == adobe_order


def test_create_switch_order_without_currency_code(
    adobe_client_factory,
    adobe_authorizations_file,
    adobe_order_factory,
    requests_mocker,
    settings,
    switch_payload,
):
    authorization_uk = adobe_authorizations_file["authorizations"][0]["authorization_uk"]
    mocked_client, authorization, _ = adobe_client_factory()
    adobe_order = adobe_order_factory(order_type=ORDER_TYPE_SWITCH, order_id="an-order-id")
    del switch_payload["currencyCode"]
    expected_payload = {
        **switch_payload,
        "externalReferenceId": "mpt-order-id",
        "orderType": ORDER_TYPE_SWITCH,
        "currencyCode": authorization.currency,
    }
    expected_payload.pop("recommendationTrackerId")
    requests_mocker.post(
        urljoin(
            settings.EXTENSION_CONFIG["ADOBE_API_BASE_URL"],
            "/v3/customers/a-customer/orders",
        ),
        status=202,
        json=adobe_order,
        match=[
            matchers.header_matcher({
                "x-recommendation-tracker-id": switch_payload["recommendationTrackerId"],
            }),
            matchers.json_params_matcher(expected_payload),
        ],
    )

    result = mocked_client.create_switch_order(
        authorization_uk,
        "a-customer",
        "mpt-order-id",
        switch_payload,
    )  # act

    assert result == adobe_order


def _without_tracker_header(request):
    absent = "x-recommendation-tracker-id" not in request.headers
    return absent, "x-recommendation-tracker-id header must not be sent"


def test_create_switch_order_without_recommendation_tracker_id(
    adobe_client_factory,
    adobe_authorizations_file,
    adobe_order_factory,
    requests_mocker,
    settings,
    switch_payload,
):
    authorization_uk = adobe_authorizations_file["authorizations"][0]["authorization_uk"]
    mocked_client, _, _ = adobe_client_factory()
    adobe_order = adobe_order_factory(order_type=ORDER_TYPE_SWITCH, order_id="an-order-id")
    del switch_payload["recommendationTrackerId"]
    expected_payload = {
        **switch_payload,
        "externalReferenceId": "mpt-order-id",
        "orderType": ORDER_TYPE_SWITCH,
    }
    requests_mocker.post(
        urljoin(
            settings.EXTENSION_CONFIG["ADOBE_API_BASE_URL"],
            "/v3/customers/a-customer/orders",
        ),
        status=202,
        json=adobe_order,
        match=[
            _without_tracker_header,
            matchers.json_params_matcher(expected_payload),
        ],
    )

    result = mocked_client.create_switch_order(
        authorization_uk,
        "a-customer",
        "mpt-order-id",
        switch_payload,
    )  # act

    assert result == adobe_order


def test_get_preview_order_http_error_without_code(
    mocker, adobe_client_factory, preview_discounts_payload_factory
):
    mocked_client, authorization, _ = adobe_client_factory()
    payload = preview_discounts_payload_factory()
    error = AdobeHttpError(504, "<html>Gateway Timeout</html>")
    mocker.patch.object(mocked_client, "_get_preview_order", side_effect=error)

    with pytest.raises(AdobeHttpError) as err:
        mocked_client.get_preview_order(authorization, "test-customer", payload)  # act

    assert err.value is error
