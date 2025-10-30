import pytest


@pytest.fixture
def preview_discounts_payload_factory():
    def _func():
        return {
            "externalReferenceId": "ORD-0792-5000-2253-4210",
            "lineItems": [
                {
                    "currencyCode": "USD",
                    "deploymentId": "a_deployment_id",
                    "extLineItemNumber": 2,
                    "offerId": "65304837CA03A12",
                    "quantity": 5,
                    "flexDiscountCodes": ["EASTER_26"],
                },
                {
                    "currencyCode": "USD",
                    "deploymentId": "a_deployment_id",
                    "extLineItemNumber": 3,
                    "offerId": "65304838CA03A12",
                    "quantity": 5,
                    "flexDiscountCodes": ["BLACK_FRIDAY"],
                },
                {
                    "currencyCode": "USD",
                    "deploymentId": "a_deployment_id",
                    "extLineItemNumber": 4,
                    "offerId": "65304839CA03A12",
                    "quantity": 5,
                },
            ],
            "orderType": "PREVIEW",
        }

    return _func


@pytest.fixture
def order_preview_discounts_resp_factory(mock_uuid4):
    def _func():
        return {
            "referenceOrderId": "",
            "externalReferenceId": "ORD-0792-5000-2253-4210",
            "orderId": "",
            "customerId": "P1005267002",
            "currencyCode": "USD",
            "orderType": "PREVIEW",
            "status": "",
            "lineItems": [
                {
                    "extLineItemNumber": 2,
                    "offerId": "65304767CA03A12",
                    "quantity": 1,
                    "subscriptionId": "",
                    "status": "",
                    "currencyCode": "USD",
                    "flexDiscounts": [
                        {
                            "id": str(mock_uuid4.return_value),
                            "code": "EASTER_26",
                            "result": "SUCCESS",
                        }
                    ],
                    "proratedDays": 364,
                    "pricing": {
                        "partnerPrice": 875.16,
                        "discountedPartnerPrice": 849.16,
                        "netPartnerPrice": 846.83,
                        "lineItemPartnerPrice": 846.83,
                    },
                },
                {
                    "extLineItemNumber": 3,
                    "offerId": "65304768CA03A12",
                    "quantity": 1,
                    "subscriptionId": "",
                    "status": "",
                    "currencyCode": "USD",
                    "flexDiscounts": [
                        {
                            "id": str(mock_uuid4.return_value),
                            "code": "BLACK_FRIDAY",
                            "result": "FAILURE",
                        }
                    ],
                    "proratedDays": 364,
                    "pricing": {
                        "partnerPrice": 875.16,
                        "discountedPartnerPrice": 849.16,
                        "netPartnerPrice": 846.83,
                        "lineItemPartnerPrice": 846.83,
                    },
                },
                {
                    "extLineItemNumber": 4,
                    "offerId": "65304839CA03A12",
                    "quantity": 1,
                    "subscriptionId": "",
                    "status": "",
                    "currencyCode": "USD",
                    "proratedDays": 364,
                    "pricing": {
                        "partnerPrice": 1363.56,
                        "discountedPartnerPrice": 1363.56,
                        "netPartnerPrice": 1359.82,
                        "lineItemPartnerPrice": 1359.82,
                    },
                },
            ],
            "pricingSummary": [{"totalLineItemPartnerPrice": 2206.65, "currencyCode": "USD"}],
            "creationDate": "2025-09-30T11:01:45Z",
        }

    return _func
