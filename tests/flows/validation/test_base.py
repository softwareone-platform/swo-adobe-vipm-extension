import logging

import pytest
from django.test import override_settings

from adobe_vipm.flows.errors import MPTAPIError
from adobe_vipm.flows.utils import reset_ordering_parameters_error, strip_trace_id
from adobe_vipm.flows.validation.base import validate_order


def test_validate_transfer_order(
    mocker,
    caplog,
    order_factory,
    transfer_order_parameters_factory,
):
    """Tests the validate order entrypoint function for transfer orders when it validates."""
    order = order_factory(order_parameters=transfer_order_parameters_factory())
    m_client = mocker.MagicMock()

    mocker.patch("adobe_vipm.flows.validation.base.populate_order_info", return_value=order)
    m_validate_transfer = mocker.patch(
        "adobe_vipm.flows.validation.base.validate_transfer",
        return_value=(False, order),
    )

    m_adobe_cli = mocker.MagicMock()
    mocker.patch("adobe_vipm.flows.validation.base.get_adobe_client", return_value=m_adobe_cli)

    with caplog.at_level(logging.INFO):
        assert validate_order(m_client, order) == order

    assert caplog.records[0].message == (
        f"Validation of order {order['id']} succeeded without errors"
    )

    m_validate_transfer.assert_called_once_with(
        m_client,
        m_adobe_cli,
        reset_ordering_parameters_error(order),
    )


def test_validate_transfer_order_no_validate(
    mocker,
    caplog,
    order_factory,
    transfer_order_parameters_factory,
):
    """Tests the validate order entrypoint function for transfers when doesn't validate."""
    mocker.patch("adobe_vipm.flows.validation.base.get_adobe_client")
    order = order_factory(order_parameters=transfer_order_parameters_factory())
    m_client = mocker.MagicMock()

    mocker.patch(
        "adobe_vipm.flows.validation.base.populate_order_info",
        return_value=reset_ordering_parameters_error(order),
    )

    mocker.patch(
        "adobe_vipm.flows.validation.base.validate_transfer",
        return_value=(True, order),
    )

    with caplog.at_level(logging.INFO):
        validate_order(m_client, order)

    assert caplog.records[0].message == (f"Validation of order {order['id']} succeeded with errors")


def test_validate_order_exception(mocker, mpt_error_factory, order_factory):
    error_data = mpt_error_factory(500, "Internal Server Error", "Oops!")
    error = MPTAPIError(500, error_data)
    mocked_notify = mocker.patch(
        "adobe_vipm.flows.validation.base.notify_unhandled_exception_in_teams"
    )
    mocker.patch(
        "adobe_vipm.flows.validation.base.validate_purchase_order",
        side_effect=error,
    )
    order = order_factory(order_id="ORD-VVVV")
    with pytest.raises(MPTAPIError):
        validate_order(mocker.MagicMock(), order)

    process, order_id, tb = mocked_notify.mock_calls[0].args
    assert process == "validation"
    assert order_id == order["id"]
    assert strip_trace_id(str(error)) in tb


def test_validate_change_order(mocker, caplog, order_factory):
    """Tests the validate order entrypoint function when it validates."""
    order = order_factory(order_type="Change")

    mocked_client = mocker.MagicMock()
    mocked_validate = mocker.patch(
        "adobe_vipm.flows.validation.base.validate_change_order",
        return_value=(False, order),
    )

    with caplog.at_level(logging.INFO):
        assert validate_order(mocked_client, order) == order

    assert caplog.records[0].message == (
        f"Validation of order {order['id']} succeeded without errors"
    )

    mocked_validate.assert_called_once_with(mocked_client, order)


def test_validate_purchase_order(mocker, caplog, order_factory):
    """Tests the validate order entrypoint function when it validates."""
    order = order_factory(order_type="Purchase")

    mocked_client = mocker.MagicMock()
    mocked_validate = mocker.patch(
        "adobe_vipm.flows.validation.base.validate_purchase_order",
        return_value=(False, order),
    )

    with caplog.at_level(logging.INFO):
        assert validate_order(mocked_client, order) == order

    assert caplog.records[0].message == (
        f"Validation of order {order['id']} succeeded without errors"
    )

    mocked_validate.assert_called_once_with(mocked_client, order)


@override_settings(
    EXTENSION_CONFIG={
        "AIRTABLE_API_TOKEN": "test-token",
        "AIRTABLE_SKU_MAPPING_BASE": "test - token",
        "PRODUCT_SEGMENT": {"PRD-1111-1111": "COM"},
    }
)
def test_validate_purchase_order_with_change(
    mocker, caplog, order_factory, mock_worker_initialize, agreement, mpt_client
):
    """Tests the validate order entrypoint function when it validates."""
    # mocked_adobe_client = mocker.patch("adobe_vipm.flows.helpers.get_adobe_client")
    from adobe_vipm.adobe.client import AdobeClient
    from adobe_vipm.adobe.dataclasses import ReturnableOrderInfo

    # mocker.patch("adobe_vipm.adobe.client.get_adobe_client")
    mocker.patch("adobe_vipm.adobe.client.get_config")
    mocker.patch.object(
        AdobeClient,
        "get_returnable_orders_by_sku",
        spec=True,
        return_value=[
            ReturnableOrderInfo(
                order={
                    "referenceOrderId": "",
                    "externalReferenceId": "ORD-1740-6220-8373",
                    "orderId": "P9201731903",
                    "customerId": "P1005202188",
                    "currencyCode": "USD",
                    "orderType": "NEW",
                    "status": "1000",
                    "lineItems": [
                        {
                            "extLineItemNumber": 1,
                            "offerId": "65304520CA02A12",
                            "quantity": 20,
                            "subscriptionId": "e495b121eb47ae80d19d8c24b4d569NA",
                            "status": "1000",
                        }
                    ],
                    "creationDate": "2025-05-28T21:48:24Z",
                    "links": {
                        "self": {
                            "uri": "/v3/customers/P1005202188/orders/P9201731903",
                            "method": "GET",
                            "headers": [],
                        }
                    },
                },
                line={
                    "extLineItemNumber": 1,
                    "offerId": "65304520CA02A12",
                    "quantity": 20,
                    "subscriptionId": "e495b121eb47ae80d19d8c24b4d569NA",
                    "status": "1000",
                },
                quantity=20,
            ),
            ReturnableOrderInfo(
                order={
                    "referenceOrderId": "",
                    "externalReferenceId": "ORD-1537-8014-5235",
                    "orderId": "P9201731906",
                    "customerId": "P1005202188",
                    "currencyCode": "USD",
                    "orderType": "NEW",
                    "status": "1000",
                    "lineItems": [
                        {
                            "extLineItemNumber": 1,
                            "offerId": "65304520CA02A12",
                            "quantity": 11,
                            "subscriptionId": "e495b121eb47ae80d19d8c24b4d569NA",
                            "status": "1000",
                        }
                    ],
                    "creationDate": "2025-05-28T21:45:40Z",
                    "links": {
                        "self": {
                            "uri": "/v3/customers/P1005202188/orders/P9201731906",
                            "method": "GET",
                            "headers": [],
                        }
                    },
                },
                line={
                    "extLineItemNumber": 1,
                    "offerId": "65304520CA02A12",
                    "quantity": 11,
                    "subscriptionId": "e495b121eb47ae80d19d8c24b4d569NA",
                    "status": "1000",
                },
                quantity=11,
            ),
        ],
    )
    mocker.patch.object(
        AdobeClient,
        "get_customer",
        spec=True,
        return_value={
            "benefits": [],
            "companyProfile": {
                "address": {
                    "addressLine1": "695 Nixon Ports",
                    "addressLine2": "Apt 232",
                    "city": "Port Elainemouth",
                    "country": "US",
                    "phoneNumber": "",
                    "postalCode": "99801",
                    "region": "AK",
                },
                "companyName": "Lukasz Lancucki (AGR-8870-5353-2814)",
                "contacts": [
                    {
                        "email": "Lukasz.Lancucki@softwareone.com",
                        "firstName": "Lukasz",
                        "lastName": "Lancucki",
                        "phoneNumber": "",
                    }
                ],
                "marketSegment": "COM",
                "preferredLanguage": "en-US",
            },
            "cotermDate": "2026-05-28",
            "creationDate": "2025-05-28T21:45:36Z",
            "customerId": "P1005202188",
            "discounts": [
                {"level": "T1", "offerType": "CONSUMABLES"},
                {"level": "02", "offerType": "LICENSE"},
            ],
            "externalReferenceId": "AGR-8870-5353-2814",
            "globalSalesEnabled": False,
            "links": {"self": {"headers": [], "method": "GET", "uri": "/v3/customers/P1005202188"}},
            "resellerId": "P1000083009",
            "status": "1000",
            "tags": [],
        },
    )
    mocker.patch.object(
        AdobeClient,
        "create_preview_order",
        spec=True,
        return_value={
            "creationDate": "2025-05-29T19:12:44Z",
            "currencyCode": "USD",
            "customerId": "P1005202188",
            "externalReferenceId": "ORD-6090-1975-4432",
            "lineItems": [
                {
                    "extLineItemNumber": 6,
                    "offerId": "65305520CA02A12",
                    "quantity": 5,
                    "status": "",
                    "subscriptionId": "",
                }
            ],
            "orderId": "",
            "orderType": "PREVIEW",
            "referenceOrderId": "",
            "status": "",
        },
    )

    mocker.patch(
        "adobe_vipm.flows.validation.shared.get_prices_for_skus",
        spec=True,
        return_value={"65305520CA02A12": 413.52},
    )

    mocker.patch(
        "adobe_vipm.flows.helpers.get_agreement",
        return_value=agreement,
    )
    mocker.patch(
        "adobe_vipm.flows.helpers.get_licensee",
        return_value=agreement["licensee"],
    )
    order = {
        "error": None,
        "$meta": {"omitted": ["billTo"]},
        "agreement": agreement,
        # {
        #     "id": "AGR-8870-5353-2814",
        #     "name": "Lukasz Test Adobe VIP Marketplace for Commercial for Area302 (Client)",
        #     "status": "Active",
        # }
        "audit": {
            "created": {
                "at": "2025-05-28T22:04:53.302Z",
                "by": {"id": "USR-3146-7176", "name": "Lukasz Lancucki"},
            },
            "updated": {
                "at": "2025-05-29T12:32:33.008Z",
                "by": {"id": "USR-3146-7176", "name": "Lukasz Lancucki"},
            },
        },
        "authorization": {
            "currency": "USD",
            "id": "AUT-2845-0795",
            "name": "Lukasz Test Authorisation",
        },
        "buyer": {
            "icon": "/v1/accounts/buyers/BUY-0280-5606/icon",
            "id": "BUY-0280-5606",
            "name": "Rolls-Royce Corporation",
        },
        "certificates": [],
        "client": {
            "icon": "/v1/accounts/accounts/ACC-5809-3083/icon",
            "id": "ACC-5809-3083",
            "name": "Area302 (Client)",
            "status": "Active",
            "type": "Client",
        },
        "externalIds": {"client": ""},
        "id": "ORD-6090-1975-4432",
        "licensee": {
            "eligibility": {"client": True, "partner": False},
            "id": "LCE-0035-3290-5619",
            "name": "Lukasz Lancucki",
        },
        "lines": [
            {
                "id": "ALI-8870-5353-2814-0001",
                "item": {
                    "externalIds": {"vendor": "65304520CA"},
                    "id": "ITM-7664-8222-0055",
                    "name": "Acrobat Pro for Teams; Multi Language - North America; Multi",
                },
                "oldQuantity": 31,
                "price": {"PPxM": -405.6, "PPxY": -4867.2, "currency": "USD", "unitPP": 243.36},
                "quantity": 11,
                "subscription": {
                    "id": "SUB-7234-3017-0009",
                    "name": "Subscription for Acrobat Pro for Teams; Multi Language - North America"
                    "; Multi",
                    "status": "Active",
                },
            },
            {
                "id": "ALI-8870-5353-2814-0006",
                "item": {
                    "externalIds": {"vendor": "65305520CA"},
                    "id": "ITM-7664-8222-0119",
                    "name": "Animate / Flash Professional for Teams; Multi Language - North America"
                    "; Multi",
                },
                "oldQuantity": 0,
                "price": {"PPxM": 172.3, "PPxY": 2067.6, "currency": "USD", "unitPP": 413.52},
                "quantity": 5,
            },
        ],
        "listing": {"id": "LST-4764-6306"},
        "notes": "",
        "parameters": {
            "fulfillment": [
                {
                    "constraints": {"hidden": False, "required": False},
                    "externalId": "dueDate",
                    "id": "PAR-7664-8222-0009",
                    "name": "Due Date",
                    "phase": "Fulfillment",
                    "type": "Date",
                },
                {
                    "constraints": {"hidden": False, "required": False},
                    "displayValue": "P1005202188",
                    "externalId": "customerId",
                    "id": "PAR-7664-8222-0010",
                    "name": "CustomerId",
                    "phase": "Fulfillment",
                    "type": "SingleLineText",
                    "value": "P1005202188",
                },
                {
                    "constraints": {"hidden": False, "required": False},
                    "displayValue": "2026-05-28",
                    "externalId": "cotermDate",
                    "id": "PAR-7664-8222-0011",
                    "name": "Anniversary date",
                    "phase": "Fulfillment",
                    "type": "Date",
                    "value": "2026-05-28",
                },
                {
                    "constraints": {"hidden": False, "required": False},
                    "displayValue": "2026-05-29",
                    "externalId": "nextSync",
                    "id": "PAR-7664-8222-0012",
                    "name": "Next synchronization",
                    "phase": "Fulfillment",
                    "type": "Date",
                    "value": "2026-05-29",
                },
                {
                    "constraints": {"hidden": False, "required": False},
                    "externalId": "3YCEnrollStatus",
                    "id": "PAR-7664-8222-0013",
                    "name": "3YC enroll status",
                    "phase": "Fulfillment",
                    "type": "SingleLineText",
                },
                {
                    "constraints": {"hidden": False, "required": False},
                    "externalId": "3YCStartDate",
                    "id": "PAR-7664-8222-0014",
                    "name": "3YC start date",
                    "phase": "Fulfillment",
                    "type": "Date",
                },
                {
                    "constraints": {"hidden": False, "required": False},
                    "externalId": "3YCEndDate",
                    "id": "PAR-7664-8222-0015",
                    "name": "3YC end date",
                    "phase": "Fulfillment",
                    "type": "Date",
                },
                {
                    "constraints": {"hidden": False, "required": False},
                    "externalId": "3YCCommitmentRequestStatus",
                    "id": "PAR-7664-8222-0016",
                    "name": "3YC Commitment Request Status",
                    "phase": "Fulfillment",
                    "type": "SingleLineText",
                },
                {
                    "constraints": {"hidden": False, "required": False},
                    "externalId": "3YCRecommit",
                    "id": "PAR-7664-8222-0017",
                    "name": "3-year recommitment",
                    "phase": "Fulfillment",
                    "type": "Checkbox",
                },
                {
                    "constraints": {"hidden": False, "required": False},
                    "externalId": "3YCRecommitmentRequestStatus",
                    "id": "PAR-7664-8222-0018",
                    "name": "3YC Recommitment Request Status",
                    "phase": "Fulfillment",
                    "type": "SingleLineText",
                },
                {
                    "constraints": {"hidden": False, "required": False},
                    "externalId": "globalCustomer",
                    "id": "PAR-7664-8222-0019",
                    "name": "Global customer",
                    "phase": "Fulfillment",
                    "type": "Checkbox",
                },
                {
                    "constraints": {"hidden": False, "required": False},
                    "externalId": "deploymentId",
                    "id": "PAR-7664-8222-0020",
                    "name": "Deployment ID",
                    "phase": "Fulfillment",
                    "type": "SingleLineText",
                },
                {
                    "constraints": {
                        "readonly": False,
                        "hidden": False,
                        "required": False,
                    },
                    "externalId": "deployments",
                    "id": "PAR-7664-8222-0021",
                    "name": "Deployments",
                    "phase": "Fulfillment",
                    "type": "MultiLineText",
                },
            ],
            "ordering": [
                {
                    "error": None,
                    "constraints": {
                        "hidden": False,
                        "readonly": False,
                        "required": False,
                    },
                    "displayValue": "New",
                    "externalId": "agreementType",
                    "id": "PAR-7664-8222-0001",
                    "name": "Agreement type",
                    "phase": "Order",
                    "type": "Choice",
                    "value": "New",
                },
                {
                    "error": None,
                    "constraints": {"hidden": False, "required": True},
                    "displayValue": "Lukasz Lancucki",
                    "externalId": "companyName",
                    "id": "PAR-7664-8222-0002",
                    "name": "Company Name",
                    "phase": "Order",
                    "type": "SingleLineText",
                    "value": "Lukasz Lancucki",
                },
                {
                    "error": None,
                    "constraints": {"hidden": False, "required": True},
                    "displayValue": "695 Nixon Ports, Apt 232, Port Elainemouth, AK 99801",
                    "externalId": "address",
                    "id": "PAR-7664-8222-0003",
                    "name": "Address",
                    "phase": "Order",
                    "type": "Address",
                    "value": {
                        "addressLine1": "695 Nixon Ports",
                        "addressLine2": "Apt 232",
                        "city": "Port Elainemouth",
                        "country": "US",
                        "postCode": "99801",
                        "state": "AK",
                    },
                },
                {
                    "error": None,
                    "constraints": {"hidden": False, "required": True},
                    "displayValue": "Lukasz Lancucki Lukasz.Lancucki@softwareone.com",
                    "externalId": "contact",
                    "id": "PAR-7664-8222-0004",
                    "name": "Contact",
                    "phase": "Order",
                    "type": "Contact",
                    "value": {
                        "email": "Lukasz.Lancucki@softwareone.com",
                        "firstName": "Lukasz",
                        "lastName": "Lancucki",
                        "phone": None,
                    },
                },
                {
                    "error": None,
                    "constraints": {"hidden": False, "required": False},
                    "externalId": "3YC",
                    "id": "PAR-7664-8222-0005",
                    "name": "3-year commitment",
                    "phase": "Order",
                    "type": "Checkbox",
                },
                {
                    "error": None,
                    "constraints": {"hidden": False, "required": False},
                    "externalId": "3YCLicenses",
                    "id": "PAR-7664-8222-0006",
                    "name": "Minimum licenses",
                    "phase": "Order",
                    "type": "SingleLineText",
                },
                {
                    "error": None,
                    "constraints": {"hidden": False, "required": False},
                    "externalId": "3YCConsumables",
                    "id": "PAR-7664-8222-0007",
                    "name": "Minimum consumables",
                    "phase": "Order",
                    "type": "SingleLineText",
                },
                {
                    "error": None,
                    "constraints": {"hidden": True, "required": False},
                    "externalId": "membershipId",
                    "id": "PAR-7664-8222-0008",
                    "name": "MembershipId",
                    "phase": "Order",
                    "type": "SingleLineText",
                },
            ],
        },
        "price": {"PPx1": 0.0, "PPxM": -233.3, "PPxY": -2799.6, "currency": "USD"},
        "product": {
            "externalIds": {},
            "icon": "/v1/catalog/products/PRD-7664-8222/icon",
            "id": "PRD-7664-8222",
            "name": "Lukasz Test Adobe VIP Marketplace for Commercial",
            "status": "Published",
        },
        "seller": {
            "externalId": "78ADB9DA-BC69-4CBF-BAA0-CDBC28619EF7",
            "icon": "/v1/accounts/sellers/SEL-7282-9889/icon",
            "id": "SEL-7282-9889",
            "name": "SoftwareOne, Inc.",
        },
        "status": "Draft",
        "subscriptions": [
            {
                "id": "SUB-7234-3017-0009",
                "name": "Subscription for Acrobat Pro for Teams; Multi Language - North America;"
                " Multi",
                "status": "Active",
            }
        ],
        "termsAndConditions": [],
        "type": "Change",
        "vendor": {"id": "ACC-9226-9856", "name": "Adobe", "status": "Active", "type": "Vendor"},
    }
    mocker.patch("adobe_vipm.airtable.models.get_sku_adobe_mapping_model", return_value={})

    with caplog.at_level(logging.INFO):
        assert validate_order(mpt_client, order) == order
