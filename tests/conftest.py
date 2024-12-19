import copy
from collections import defaultdict
from datetime import UTC, date, datetime, timedelta

import jwt
import pytest
import responses
from swo.mpt.extensions.runtime.djapp.conf import get_for_product

from adobe_vipm.adobe.client import AdobeClient
from adobe_vipm.adobe.config import Config
from adobe_vipm.adobe.constants import (
    OFFER_TYPE_CONSUMABLES,
    OFFER_TYPE_LICENSE,
    STATUS_PENDING,
    STATUS_PROCESSED,
)
from adobe_vipm.adobe.dataclasses import APIToken, Authorization
from adobe_vipm.flows.constants import (
    PARAM_3YC,
    PARAM_3YC_COMMITMENT_REQUEST_STATUS,
    PARAM_3YC_CONSUMABLES,
    PARAM_3YC_END_DATE,
    PARAM_3YC_ENROLL_STATUS,
    PARAM_3YC_LICENSES,
    PARAM_3YC_RECOMMITMENT,
    PARAM_3YC_RECOMMITMENT_REQUEST_STATUS,
    PARAM_3YC_START_DATE,
    PARAM_ADDRESS,
    PARAM_ADOBE_SKU,
    PARAM_AGREEMENT_TYPE,
    PARAM_COMPANY_NAME,
    PARAM_CONTACT,
    PARAM_COTERM_DATE,
    PARAM_CUSTOMER_ID,
    PARAM_DUE_DATE,
    PARAM_MARKET_SEGMENT_ELIGIBILITY_STATUS,
    PARAM_MEMBERSHIP_ID,
    PARAM_NEXT_SYNC_DATE,
)


@pytest.fixture()
def requests_mocker():
    """
    Allow mocking of http calls made with requests.
    """
    with responses.RequestsMock() as rsps:
        yield rsps


@pytest.fixture()
def adobe_api_error_factory():
    """
    Generate an error message returned by Adobe.
    """

    def _adobe_error(code, message, details=None):
        error = {
            "code": code,
            "message": message,
        }
        if details:
            error["additionalDetails"] = details
        return error

    return _adobe_error


@pytest.fixture()
def adobe_config_file():
    """
    Return an Adobe VIP Marketplace configuration file
    """
    return {
        "language_codes": ["en-US"],
        "skus_mapping": [
            {
                "vendor_external_id": "65304578CA",
                "name": "Test product",
                "sku": "65304578CA01A12",
                "type": "TEAM",
            },
            {
                "vendor_external_id": "77777777CA",
                "name": "Test onetime item",
                "sku": "77777777CA01A12",
                "type": "TEAM",
            },
        ],
        "countries": [
            {
                "code": "US",
                "name": "United States",
                "currencies": ["USD"],
                "states_or_provinces": [
                    "DE",
                    "HI",
                    "TX",
                    "PW",
                    "MA",
                    "MD",
                    "IA",
                    "ME",
                    "ID",
                    "MI",
                    "UT",
                    "AA",
                    "MN",
                    "MO",
                    "IL",
                    "AE",
                    "IN",
                    "MS",
                    "MT",
                    "AK",
                    "AL",
                    "VA",
                    "AP",
                    "AR",
                    "NC",
                    "ND",
                    "NE",
                    "RI",
                    "AZ",
                    "NH",
                    "NJ",
                    "VT",
                    "NM",
                    "FL",
                    "NV",
                    "WA",
                    "NY",
                    "SC",
                    "SD",
                    "WI",
                    "OH",
                    "GA",
                    "OK",
                    "CA",
                    "WV",
                    "WY",
                    "OR",
                    "KS",
                    "CO",
                    "KY",
                    "CT",
                    "PA",
                    "LA",
                    "TN",
                    "DC",
                ],
                "pricelist_region": "NA",
                "postal_code_format_regex": "^[\\d]{5}(?:-[\\d]{4})?$",
                "provinces_to_code": {
                    "Alabama": "AL",
                    "Alaska": "AK",
                    "Arizona": "AZ",
                    "Arkansas": "AR",
                    "California": "CA",
                    "Colorado": "CO",
                    "Connecticut": "CT",
                    "Delaware": "DE",
                    "District of Columbia": "DC",
                    "Florida": "FL",
                    "Georgia": "GA",
                    "Hawaii": "HI",
                    "Idaho": "ID",
                    "Illinois": "IL",
                    "Indiana": "IN",
                    "Iowa": "IA",
                    "Kansas": "KS",
                    "Kentucky": "KY",
                    "Louisiana": "LA",
                    "Maine": "ME",
                    "Maryland": "MD",
                    "Massachusetts": "MA",
                    "Michigan": "MI",
                    "Minnesota": "MN",
                    "Mississippi": "MS",
                    "Missouri": "MO",
                    "Montana": "MT",
                    "Nebraska": "NE",
                    "Nevada": "NV",
                    "New Hampshire": "NH",
                    "New Jersey": "NJ",
                    "New Mexico": "NM",
                    "New York": "NY",
                    "North Carolina": "NC",
                    "North Dakota": "ND",
                    "Ohio": "OH",
                    "Oklahoma": "OK",
                    "Oregon": "OR",
                    "Pennsylvania": "PA",
                    "Rhode Island": "RI",
                    "South Carolina": "SC",
                    "South Dakota": "SD",
                    "Tennessee": "TN",
                    "Texas": "TX",
                    "Utah": "UT",
                    "Vermont": "VT",
                    "Virginia": "VA",
                    "Washington": "WA",
                    "West Virginia": "WV",
                    "Wisconsin": "WI",
                    "Wyoming": "WY",
                    "Armed Forces Americas": "AA",
                    "Armed Forces Europe, Canada, Africa and Middle East": "AE",
                    "Armed Forces Pacific": "AP",
                },
            },
            {
                "code": "VU",
                "name": "Vanuatu",
                "currencies": ["USD"],
                "states_or_provinces": [
                    "00",
                    "01",
                    "SEE",
                    "TOB",
                    "TAE",
                    "MAP",
                    "PAM",
                    "SAM",
                ],
                "pricelist_region": "AP",
                "postal_code_format_regex": "",
            },
        ],
    }


@pytest.fixture()
def adobe_credentials_file():
    """
    Return an Adobe VIP Marketplace credentials file
    """
    return [
        {
            "authorization_uk": "uk-auth-adobe-us-01",
            "authorization_id": "AUT-1234-4567",
            "name": "Adobe VIP Marketplace for Sandbox",
            "country": "US",
            "client_id": "client_id",
            "client_secret": "client_secret",
        },
    ]


@pytest.fixture()
def adobe_authorizations_file():
    """
    Return an Adobe VIP Marketplace authorizations file
    """
    return {
        "authorizations": [
            {
                "pricelist_region": "NA",
                "distributor_id": "db5a6d9c-9eb5-492e-a000-ab4b8c29fc63",
                "currency": "USD",
                "authorization_uk": "uk-auth-adobe-us-01",
                "authorization_id": "AUT-1234-4567",
                "resellers": [
                    {
                        "id": "P1000041107",
                        "seller_uk": "SWO_US",
                        "seller_id": "SEL-1234-4567",
                    },
                ],
            },
        ]
    }


@pytest.fixture()
def mock_adobe_config(
    mocker, adobe_credentials_file, adobe_authorizations_file, adobe_config_file
):
    """
    Mock the Adobe Config object to load test data from the adobe_credentials and
    adobe_config_file fixtures.
    """
    mocker.patch.object(
        Config, "_load_credentials", return_value=adobe_credentials_file
    )
    mocker.patch.object(
        Config, "_load_authorizations", return_value=adobe_authorizations_file
    )
    mocker.patch.object(Config, "_load_config", return_value=adobe_config_file)


@pytest.fixture()
def account_data():
    """
    Returns a adobe account data structure.

    """
    return {
        "companyName": "ACME Inc",
        "address": {
            "country": "US",
            "state": "CA",
            "city": "Irvine",
            "addressLine1": "Test street",
            "addressLine2": "Line 2",
            "postCode": "08010",
        },
        "contact": {
            "firstName": "First Name",
            "lastName": "Last Name",
            "email": "test@example.com",
            "phone": {
                "prefix": "+1",
                "number": "4082954078",
            },
        },
    }


@pytest.fixture()
def customer_data(account_data):
    data = copy.copy(account_data)
    data["3YC"] = []
    data["3YCConsumables"] = ""
    data["3YCLicenses"] = ""
    return data


@pytest.fixture()
def reseller_data(account_data):
    return account_data


@pytest.fixture()
def order_parameters_factory():
    def _order_parameters(
        company_name="FF Buyer good enough",
        address=None,
        contact=None,
        p3yc=None,
        p3yc_licenses="",
        p3yc_consumables="",
    ):
        if address is None:
            address = {
                "country": "US",
                "state": "CA",
                "city": "San Jose",
                "addressLine1": "3601 Lyon St",
                "addressLine2": "",
                "postCode": "94123",
            }
        if contact is None:
            contact = {
                "firstName": "Cic",
                "lastName": "Faraone",
                "email": "francesco.faraone@softwareone.com",
                "phone": {
                    "prefix": "+1",
                    "number": "4082954078",
                },
            }
        return [
            {
                "id": "PAR-0000-0001",
                "name": "Company Name",
                "externalId": PARAM_COMPANY_NAME,
                "type": "SingleLineText",
                "value": company_name,
                "constraints": {
                    "hidden": False,
                    "required": True,
                },
            },
            {
                "id": "PAR-0000-0002",
                "name": "Address",
                "externalId": PARAM_ADDRESS,
                "type": "Address",
                "value": address,
                "constraints": {
                    "hidden": False,
                    "required": True,
                },
            },
            {
                "id": "PAR-0000-0003",
                "name": "Contact",
                "externalId": PARAM_CONTACT,
                "type": "Contact",
                "value": contact,
                "constraints": {
                    "hidden": False,
                    "required": True,
                },
            },
            {
                "id": "PAR-0000-0004",
                "name": "Account type",
                "externalId": PARAM_AGREEMENT_TYPE,
                "type": "SingleLineText",
                "value": "New",
                "constraints": {
                    "hidden": False,
                    "required": True,
                },
            },
            {
                "id": "PAR-0000-0005",
                "name": "Membership Id",
                "externalId": PARAM_MEMBERSHIP_ID,
                "type": "SingleLineText",
                "value": "",
                "constraints": {
                    "hidden": True,
                    "required": False,
                },
            },
            {
                "id": "PAR-0000-0006",
                "name": "3YC",
                "externalId": PARAM_3YC,
                "type": "Checkbox",
                "value": p3yc,
                "constraints": {
                    "hidden": False,
                    "required": False,
                },
            },
            {
                "id": "PAR-0000-0007",
                "name": "3YCLicenses",
                "externalId": PARAM_3YC_LICENSES,
                "type": "SingleLineText",
                "value": p3yc_licenses,
                "constraints": {
                    "hidden": False,
                    "required": False,
                },
            },
            {
                "id": "PAR-0000-0008",
                "name": "3YCConsumables",
                "externalId": PARAM_3YC_CONSUMABLES,
                "type": "SingleLineText",
                "value": p3yc_consumables,
                "constraints": {
                    "hidden": False,
                    "required": False,
                },
            },
        ]

    return _order_parameters


@pytest.fixture()
def transfer_order_parameters_factory():
    def _order_parameters(
        membership_id="a-membership-id",
        company_name=None,
        address=None,
        contact=None,
        p3yc=None,
        p3yc_licenses=None,
        p3yc_consumables=None,
    ):
        return [
            {
                "id": "PAR-0000-0001",
                "name": "Company Name",
                "externalId": PARAM_COMPANY_NAME,
                "type": "SingleLineText",
                "value": company_name or "",
                "constraints": {
                    "hidden": True,
                    "required": False,
                },
            },
            {
                "id": "PAR-0000-0002",
                "name": "Address",
                "externalId": PARAM_ADDRESS,
                "type": "Address",
                "value": address or {},
                "constraints": {
                    "hidden": True,
                    "required": False,
                },
            },
            {
                "id": "PAR-0000-0003",
                "name": "Contact",
                "externalId": PARAM_CONTACT,
                "type": "Contact",
                "value": contact or {},
                "constraints": {
                    "hidden": True,
                    "required": False,
                },
            },
            {
                "id": "PAR-0000-0004",
                "name": "Account type",
                "externalId": PARAM_AGREEMENT_TYPE,
                "type": "SingleLineText",
                "value": "Migrate",
                "constraints": {
                    "hidden": False,
                    "required": True,
                },
            },
            {
                "id": "PAR-0000-0005",
                "name": "Membership Id",
                "externalId": PARAM_MEMBERSHIP_ID,
                "type": "SingleLineText",
                "value": membership_id,
                "constraints": {
                    "hidden": False,
                    "required": True,
                },
            },
            {
                "id": "PAR-0000-0006",
                "name": "3YC",
                "externalId": PARAM_3YC,
                "type": "Checkbox",
                "value": p3yc,
                "constraints": {
                    "hidden": True,
                    "required": False,
                },
            },
            {
                "id": "PAR-0000-0007",
                "name": "3YCLicenses",
                "externalId": PARAM_3YC_LICENSES,
                "type": "SingleLineText",
                "value": p3yc_licenses or "",
                "constraints": {
                    "hidden": True,
                    "required": False,
                },
            },
            {
                "id": "PAR-0000-0008",
                "name": "3YCConsumables",
                "externalId": PARAM_3YC_CONSUMABLES,
                "type": "SingleLineText",
                "value": p3yc_consumables or "",
                "constraints": {
                    "hidden": True,
                    "required": False,
                },
            },
        ]

    return _order_parameters


@pytest.fixture()
def fulfillment_parameters_factory():
    def _fulfillment_parameters(
        customer_id="",
        due_date=None,
        p3yc_recommitment=None,
        p3yc_enroll_status="",
        p3yc_commitment_request_status="",
        p3yc_recommitment_request_status="",
        p3yc_start_date="",
        p3yc_end_date="",
        next_sync_date="",
        market_segment_eligibility_status=None,
        coterm_date="",
    ):
        return [
            {
                "id": "PAR-1234-5678",
                "name": "Customer Id",
                "externalId": PARAM_CUSTOMER_ID,
                "type": "SingleLineText",
                "value": customer_id,
            },
            {
                "id": "PAR-7771-1777",
                "name": "Due Date",
                "externalId": PARAM_DUE_DATE,
                "type": "Date",
                "value": due_date,
            },
            {
                "id": "PAR-9876-5432",
                "name": "3YC Enroll Status",
                "externalId": PARAM_3YC_ENROLL_STATUS,
                "type": "SingleLineText",
                "value": p3yc_enroll_status,
            },
            {
                "id": "PAR-2266-4848",
                "name": "3YC Start Date",
                "externalId": PARAM_3YC_START_DATE,
                "type": "Date",
                "value": p3yc_start_date,
            },
            {
                "id": "PAR-3528-2927",
                "name": "3YC End Date",
                "externalId": PARAM_3YC_END_DATE,
                "type": "Date",
                "value": p3yc_end_date,
            },
            {
                "id": "PAR-4141-1414",
                "name": "Next Sync",
                "externalId": PARAM_NEXT_SYNC_DATE,
                "type": "Date",
                "value": next_sync_date,
            },
            {
                "id": "PAR-0022-2200",
                "name": "3YC Commitment Request Status",
                "externalId": PARAM_3YC_COMMITMENT_REQUEST_STATUS,
                "type": "SingleLineText",
                "value": p3yc_commitment_request_status,
            },
            {
                "id": "PAR-0077-7700",
                "name": "3YC Recommitment Request Status",
                "externalId": PARAM_3YC_RECOMMITMENT_REQUEST_STATUS,
                "type": "SingleLineText",
                "value": p3yc_recommitment_request_status,
            },
            {
                "id": "PAR-0000-6666",
                "name": "3YCRecommitment",
                "externalId": PARAM_3YC_RECOMMITMENT,
                "type": "Checkbox",
                "value": p3yc_recommitment or [],
            },
            {
                "id": "PAR-0000-6666",
                "name": "Eligibility Status",
                "externalId": PARAM_MARKET_SEGMENT_ELIGIBILITY_STATUS,
                "type": "Dropdown",
                "value": market_segment_eligibility_status,
            },
            {
                "id": "PAR-7373-1919",
                "name": "Customer Coterm date",
                "externalId": PARAM_COTERM_DATE,
                "type": "Date",
                "value": coterm_date,
            },
        ]

    return _fulfillment_parameters


@pytest.fixture()
def items_factory():
    def _items(
        item_id=1,
        name="Awesome product",
        external_vendor_id="65304578CA",
        term_period="1y",
    ):
        return [
            {
                "id": f"ITM-1234-1234-1234-{item_id:04d}",
                "name": name,
                "externalIds": {
                    "vendor": external_vendor_id,
                },
                "terms": {"period": term_period},
            },
        ]

    return _items


@pytest.fixture()
def pricelist_items_factory():
    def _items(
        item_id=1,
        external_vendor_id="65304578CA",
        unit_purchase_price=1234.55,
    ):
        return [
            {
                "id": f"PRI-1234-1234-1234-{item_id:04d}",
                "item": {
                    "id": f"ITM-1234-1234-1234-{item_id:04d}",
                    "externalIds": {
                        "vendor": external_vendor_id,
                    },
                },
                "unitPP": unit_purchase_price,
            },
        ]

    return _items


@pytest.fixture()
def lines_factory(agreement):
    agreement_id = agreement["id"].split("-", 1)[1]

    def _items(
        line_id=1,
        item_id=1,
        name="Awesome product",
        old_quantity=0,
        quantity=170,
        external_vendor_id="65304578CA",
        unit_purchase_price=1234.55,
    ):
        line = {
            "item": {
                "id": f"ITM-1234-1234-1234-{item_id:04d}",
                "name": name,
                "externalIds": {
                    "vendor": external_vendor_id,
                },
            },
            "oldQuantity": old_quantity,
            "quantity": quantity,
            "price": {
                "unitPP": unit_purchase_price,
            },
        }
        if line_id:
            line["id"] = f"ALI-{agreement_id}-{line_id:04d}"
        return [line]

    return _items


@pytest.fixture()
def subscriptions_factory(lines_factory):
    def _subscriptions(
        subscription_id="SUB-1000-2000-3000",
        product_name="Awesome product",
        adobe_subscription_id="a-sub-id",
        adobe_sku="65304578CA01A12",
        start_date=None,
        commitment_date=None,
        lines=None,
    ):
        start_date = (
            start_date.isoformat() if start_date else datetime.now(UTC).isoformat()
        )
        lines = lines_factory() if lines is None else lines
        return [
            {
                "id": subscription_id,
                "name": f"Subscription for {product_name}",
                "parameters": {
                    "fulfillment": [
                        {
                            "name": "Adobe SKU",
                            "externalId": PARAM_ADOBE_SKU,
                            "type": "SingleLineText",
                            "value": adobe_sku,
                        }
                    ]
                },
                "externalIds": {
                    "vendor": adobe_subscription_id,
                },
                "lines": lines,
                "startDate": start_date,
                "commitmentDate": commitment_date,
            }
        ]

    return _subscriptions


@pytest.fixture()
def agreement_factory(buyer, order_parameters_factory, fulfillment_parameters_factory):
    def _agreement(
        licensee_name="My beautiful licensee",
        licensee_address=None,
        licensee_contact=None,
        use_buyer_address=False,
        subscriptions=None,
        fulfillment_parameters=None,
        ordering_parameters=None,
        lines=None,
    ):
        if not subscriptions:
            subscriptions = [
                {
                    "id": "SUB-1000-2000-3000",
                    "status": "Active",
                    "item": {
                        "id": "ITM-0000-0001-0001",
                    },
                },
                {
                    "id": "SUB-1234-5678",
                    "status": "Terminated",
                    "item": {
                        "id": "ITM-0000-0001-0002",
                    },
                },
            ]

        licensee = {
            "name": licensee_name,
            "address": licensee_address,
            "useBuyerAddress": use_buyer_address,
        }
        if licensee_contact:
            licensee["contact"] = licensee_contact

        return {
            "id": "AGR-2119-4550-8674-5962",
            "href": "/commerce/agreements/AGR-2119-4550-8674-5962",
            "icon": None,
            "name": "Product Name 1",
            "audit": {
                "created": {
                    "at": "2023-12-14T18:02:16.9359",
                    "by": {"id": "USR-0000-0001"},
                },
                "updated": None,
            },
            "listing": {
                "id": "LST-9401-9279",
                "href": "/listing/LST-9401-9279",
                "priceList": {
                    "id": "PRC-9457-4272-3691",
                    "href": "/v1/price-lists/PRC-9457-4272-3691",
                    "currency": "USD",
                },
            },
            "licensee": licensee,
            "buyer": buyer,
            "seller": {
                "id": "SEL-9121-8944",
                "href": "/accounts/sellers/SEL-9121-8944",
                "name": "Software LN",
                "icon": "/static/SEL-9121-8944/icon.png",
                "address": {
                    "country": "US",
                },
            },
            "client": {
                "id": "ACC-9121-8944",
                "href": "/accounts/sellers/ACC-9121-8944",
                "name": "Software LN",
                "icon": "/static/ACC-9121-8944/icon.png",
            },
            "product": {
                "id": "PRD-1111-1111",
            },
            "authorization": {"id": "AUT-1234-5678"},
            "lines": lines or [],
            "subscriptions": subscriptions,
            "parameters": {
                "ordering": ordering_parameters or order_parameters_factory(),
                "fulfillment": fulfillment_parameters
                or fulfillment_parameters_factory(),
            },
        }

    return _agreement


@pytest.fixture()
def agreement(buyer):
    return {
        "id": "AGR-2119-4550-8674-5962",
        "href": "/commerce/agreements/AGR-2119-4550-8674-5962",
        "icon": None,
        "name": "Product Name 1",
        "audit": {
            "created": {
                "at": "2023-12-14T18:02:16.9359",
                "by": {"id": "USR-0000-0001"},
            },
            "updated": None,
        },
        "subscriptions": [
            {
                "id": "SUB-1000-2000-3000",
                "status": "Active",
                "lines": [
                    {
                        "id": "ALI-0010",
                        "item": {
                            "id": "ITM-1234-1234-1234-0010",
                            "name": "Item 0010",
                            "externalIds": {
                                "vendor": "external-id1",
                            },
                        },
                        "quantity": 10,
                    }
                ],
            },
            {
                "id": "SUB-1234-5678",
                "status": "Terminated",
                "lines": [
                    {
                        "id": "ALI-0011",
                        "item": {
                            "id": "ITM-1234-1234-1234-0011",
                            "name": "Item 0011",
                            "externalIds": {
                                "vendor": "external-id2",
                            },
                        },
                        "quantity": 4,
                    }
                ],
            },
        ],
        "listing": {
            "id": "LST-9401-9279",
            "href": "/listing/LST-9401-9279",
            "priceList": {
                "id": "PRC-9457-4272-3691",
                "href": "/v1/price-lists/PRC-9457-4272-3691",
                "currency": "USD",
            },
        },
        "licensee": {
            "id": "LCE-1111-2222-3333",
            "name": "FF Buyer good enough",
            "useBuyerAddress": True,
            "address": buyer["address"],
            "contact": buyer["contact"],
        },
        "buyer": buyer,
        "seller": {
            "id": "SEL-9121-8944",
            "href": "/accounts/sellers/SEL-9121-8944",
            "name": "Software LN",
            "icon": "/static/SEL-9121-8944/icon.png",
            "address": {
                "country": "US",
            },
        },
        "product": {
            "id": "PRD-1111-1111",
        },
    }


@pytest.fixture()
def order_factory(
    agreement,
    order_parameters_factory,
    fulfillment_parameters_factory,
    lines_factory,
    status="Processing",
):
    """
    Marketplace platform order for tests.
    """

    def _order(
        order_id="ORD-0792-5000-2253-4210",
        order_type="Purchase",
        order_parameters=None,
        fulfillment_parameters=None,
        lines=None,
        subscriptions=None,
        external_ids=None,
        status=status,
        template=None,
    ):
        order_parameters = (
            order_parameters_factory() if order_parameters is None else order_parameters
        )
        fulfillment_parameters = (
            fulfillment_parameters_factory()
            if fulfillment_parameters is None
            else fulfillment_parameters
        )

        lines = lines_factory() if lines is None else lines
        subscriptions = [] if subscriptions is None else subscriptions

        order = {
            "id": order_id,
            "error": None,
            "href": "/commerce/orders/ORD-0792-5000-2253-4210",
            "agreement": agreement,
            "authorization": {
                "id": "AUT-1234-4567",
            },
            "type": order_type,
            "status": status,
            "clientReferenceNumber": None,
            "notes": "First order to try",
            "lines": lines,
            "subscriptions": subscriptions,
            "parameters": {
                "fulfillment": fulfillment_parameters,
                "ordering": order_parameters,
            },
            "audit": {
                "created": {
                    "at": "2023-12-14T18:02:16.9359",
                    "by": {"id": "USR-0000-0001"},
                },
                "updated": None,
            },
        }
        if external_ids:
            order["externalIds"] = external_ids
        if template:
            order["template"] = template
        return order

    return _order


@pytest.fixture()
def order(order_factory):
    return order_factory()


@pytest.fixture()
def buyer():
    return {
        "id": "BUY-3731-7971",
        "href": "/accounts/buyers/BUY-3731-7971",
        "name": "A buyer",
        "icon": "/static/BUY-3731-7971/icon.png",
        "address": {
            "country": "US",
            "state": "CA",
            "city": "San Jose",
            "addressLine1": "3601 Lyon St",
            "addressLine2": "",
            "postCode": "94123",
        },
        "contact": {
            "firstName": "Cic",
            "lastName": "Faraone",
            "email": "francesco.faraone@softwareone.com",
            "phone": {
                "prefix": "+1",
                "number": "4082954078",
            },
        },
    }


@pytest.fixture()
def seller():
    return {
        "id": "SEL-9121-8944",
        "href": "/accounts/sellers/SEL-9121-8944",
        "name": "SWO US",
        "icon": "/static/SEL-9121-8944/icon.png",
        "address": {
            "country": "US",
            "region": "CA",
            "city": "San Jose",
            "addressLine1": "3601 Lyon St",
            "addressLine2": "",
            "postCode": "94123",
        },
        "contact": {
            "firstName": "Francesco",
            "lastName": "Faraone",
            "email": "francesco.faraone@softwareone.com",
            "phone": {
                "prefix": "+1",
                "number": "4082954078",
            },
        },
    }


@pytest.fixture()
def webhook(settings):
    return {
        "id": "WH-123-123",
        "criteria": {"product.id": settings.MPT_PRODUCTS_IDS[0]},
    }


@pytest.fixture()
def adobe_items_factory():
    def _items(
        line_number=1,
        offer_id="65304578CA01A12",
        quantity=170,
        subscription_id=None,
        renewal_date=None,
        status=None,
        deployment_id=None,
       currencyCode= None,
    ):
        item = {
            "extLineItemNumber": line_number,
            "offerId": offer_id,
            "quantity": quantity,
        }
        if currencyCode:
            item["currencyCode"] = currencyCode
        if deployment_id:
            item["deploymentId"] = deployment_id
        if renewal_date:
            item["renewalDate"] = renewal_date
        if subscription_id:
            item["subscriptionId"] = subscription_id
        if status:
            item["status"] = status
        return [item]

    return _items


@pytest.fixture()
def adobe_order_factory(adobe_items_factory):
    def _order(
        order_type,
        currency_code="USD",
        external_id="external_id",
        items=None,
        order_id=None,
        reference_order_id=None,
        status=None,
        creation_date=None,
    ):
        order = {
            "externalReferenceId": external_id,
            "currencyCode": currency_code,
            "orderType": order_type,
            "lineItems": items or adobe_items_factory(),
        }

        if reference_order_id:
            order["referenceOrderId"] = reference_order_id
        if status:
            order["status"] = status
        if status in [STATUS_PENDING, STATUS_PROCESSED] or order_id:
            order["orderId"] = order_id or "P0123456789"
        if creation_date:
            order["creationDate"] = creation_date
        return order

    return _order


@pytest.fixture()
def adobe_subscription_factory():
    def _subscription(
        subscription_id=None,
        offer_id=None,
        current_quantity=10,
        renewal_quantity=10,
        autorenewal_enabled=True,
        deployment_id="",
        status=STATUS_PROCESSED,
        renewal_date=None,
    ):
        return {
            "subscriptionId": subscription_id or "a-sub-id",
            "offerId": offer_id or "65304578CA01A12",
            "currentQuantity": current_quantity,
            "autoRenewal": {
                "enabled": autorenewal_enabled,
                "renewalQuantity": renewal_quantity,
            },
            "creationDate": "2019-05-20T22:49:55Z",
            "renewalDate": renewal_date
            or (date.today() + timedelta(days=366)).isoformat(),
            "status": status,
            "deploymentId": deployment_id,
        }

    return _subscription


@pytest.fixture()
def adobe_preview_transfer_factory(adobe_items_factory):
    def _preview(items=None):
        items = (
            items
            if items is not None
            else adobe_items_factory(renewal_date=date.today().isoformat())
        )
        return {
            "totalCount": len(items),
            "items": items,
        }

    return _preview


@pytest.fixture()
def adobe_transfer_factory(adobe_items_factory):
    def _transfer(
        transfer_id="a-transfer-id",
        customer_id="",
        status=STATUS_PENDING,
        items=None,
        membership_id="membership-id",
    ):
        transfer = {
            "transferId": transfer_id,
            "customerId": customer_id,
            "status": status,
            "membershipId": membership_id,
            "lineItems": items or adobe_items_factory(),
        }

        return transfer

    return _transfer


@pytest.fixture()
def adobe_client_factory(
    adobe_credentials_file,
    mock_adobe_config,
    adobe_authorizations_file,
):
    """
    Returns a factory that allow the creation of an instance
    of the AdobeClient with a fake token ready for tests.
    """

    def _factory():
        authorization = Authorization(
            authorization_uk=adobe_authorizations_file["authorizations"][0][
                "authorization_uk"
            ],
            authorization_id=adobe_authorizations_file["authorizations"][0][
                "authorization_id"
            ],
            name=adobe_credentials_file[0]["name"],
            client_id=adobe_credentials_file[0]["client_id"],
            client_secret=adobe_credentials_file[0]["client_secret"],
            currency=adobe_authorizations_file["authorizations"][0]["currency"],
            distributor_id=adobe_authorizations_file["authorizations"][0][
                "distributor_id"
            ],
        )
        api_token = APIToken(
            "a-token",
            expires=datetime.now() + timedelta(seconds=86000),
        )
        client = AdobeClient()
        client._token_cache[authorization] = api_token

        return client, authorization, api_token

    return _factory


@pytest.fixture()
def mpt_client(settings):
    """
    Create an instance of the MPT client used by the extension.
    """
    settings.MPT_API_BASE_URL = "https://localhost"
    from swo.mpt.extensions.core.utils import setup_client

    return setup_client()


@pytest.fixture()
def mpt_error_factory():
    """
    Generate an error message returned by the Marketplace platform.
    """

    def _mpt_error(
        status,
        title,
        detail,
        trace_id="00-27cdbfa231ecb356ab32c11b22fd5f3c-721db10d009dfa2a-00",
        errors=None,
    ):
        error = {
            "status": status,
            "title": title,
            "detail": detail,
            "traceId": trace_id,
        }
        if errors:
            error["errors"] = errors

        return error

    return _mpt_error


@pytest.fixture()
def airtable_error_factory():
    """
    Generate an error message returned by the Airtable API.
    """

    def _airtable_error(
        message,
        error_type="INVALID_REQUEST_UNKNOWN",
    ):
        error = {
            "error": {
                "type": error_type,
                "message": message,
            }
        }

        return error

    return _airtable_error


@pytest.fixture()
def mpt_list_response():
    def _wrap_response(objects_list):
        return {
            "data": objects_list,
        }

    return _wrap_response


@pytest.fixture()
def jwt_token(settings):
    iat = nbf = int(datetime.now().timestamp())
    exp = nbf + 300
    return jwt.encode(
        {
            "iss": "mpt",
            "aud": "adobe.ext.s1.com",
            "iat": iat,
            "nbf": nbf,
            "exp": exp,
            "webhook_id": "WH-123-123",
        },
        get_for_product(settings, "WEBHOOKS_SECRETS", "PRD-1111-1111"),
        algorithm="HS256",
    )


@pytest.fixture()
def extension_settings(settings):
    current_extension_config = copy.copy(settings.EXTENSION_CONFIG)
    yield settings
    settings.EXTENSION_CONFIG = current_extension_config


@pytest.fixture()
def adobe_commitment_factory():
    def _commitment(
        licenses=None,
        consumables=None,
        start_date="2024-01-01",
        end_date="2025-01-01",
        status="COMMITTED",
    ):
        commitment = {
            "startDate": start_date,
            "endDate": end_date,
            "status": status,
            "minimumQuantities": [],
        }
        if licenses:
            commitment["minimumQuantities"].append(
                {
                    "offerType": "LICENSE",
                    "quantity": licenses,
                },
            )

        if consumables:
            commitment["minimumQuantities"].append(
                {
                    "offerType": "CONSUMABLES",
                    "quantity": consumables,
                },
            )

        return commitment

    return _commitment


@pytest.fixture()
def adobe_customer_factory():
    def _customer(
        customer_id="a-client-id",
        phone_number="+18004449890",
        country="US",
        commitment=None,
        commitment_request=None,
        recommitment_request=None,
        licenses_discount_level="01",
        consumables_discount_level="T1",
        coterm_date="2024-01-23",
        global_sales_enabled=False,
    ):
        customer = {
            "customerId": customer_id,
            "companyProfile": {
                "companyName": "Migrated Company",
                "preferredLanguage": "en-US",
                "address": {
                    "addressLine1": "addressLine1",
                    "addressLine2": "addressLine2",
                    "city": "city",
                    "region": "region",
                    "postalCode": "postalCode",
                    "country": country,
                    "phoneNumber": phone_number,
                },
                "contacts": [
                    {
                        "firstName": "firstName",
                        "lastName": "lastName",
                        "email": "email",
                        "phoneNumber": phone_number,
                    },
                ],
            },
            "discounts": [
                {
                    "offerType": OFFER_TYPE_LICENSE,
                    "level": licenses_discount_level,
                },
                {
                    "offerType": OFFER_TYPE_CONSUMABLES,
                    "level": consumables_discount_level,
                },
            ],
            "cotermDate": coterm_date,
            "globalSalesEnabled":global_sales_enabled,
        }
        if commitment or commitment_request or recommitment_request:
            customer["benefits"] = [
                {
                    "type": "THREE_YEAR_COMMIT",
                    "commitment": commitment,
                    "commitmentRequest": commitment_request,
                    "recommitmentRequest": recommitment_request,
                },
            ]
        return customer

    return _customer


@pytest.fixture()
def mock_pricelist_cache_factory(mocker):
    def _mocked_cache(cache=None):
        new_cache = cache or defaultdict(list)
        mocker.patch("adobe_vipm.flows.airtable.PRICELIST_CACHE", new_cache)
        return new_cache

    return _mocked_cache


@pytest.fixture()
def mocked_pricelist_cache(mock_pricelist_cache_factory):
    return mock_pricelist_cache_factory()
