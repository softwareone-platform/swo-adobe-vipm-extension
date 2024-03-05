from datetime import UTC, datetime, timedelta

import jwt
import pytest
import responses

from adobe_vipm.adobe.client import AdobeClient
from adobe_vipm.adobe.config import Config
from adobe_vipm.adobe.constants import STATUS_PENDING, STATUS_PROCESSED
from adobe_vipm.adobe.dataclasses import APIToken, Credentials


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
        "authentication_endpoint_url": "https://authenticate.adobe",
        "api_base_url": "https://api.adobe",
        "scopes": ["openid", "AdobeID", "read_organizations"],
        "language_codes": ["en-US"],
        "accounts": [
            {
                "pricelist_region": "NA",
                "country": "US",
                "distributor_id": "distributor_id",
                "currency": "USD",
                "resellers": [{"id": "P1000040545", "country": "US"}],
            }
        ],
        "skus_mapping": [
            {
                "vendor_external_id": "65304578CA",
                "name": "Test product",
                "sku": "65304578CA01A12",
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
            },
            {
                "code": "VU",
                "name": "Vanuatu",
                "currencies": ["USD"],
                "states_or_provinces": ["00", "01", "SEE", "TOB", "TAE", "MAP", "PAM", "SAM"],
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
            "country": "US",
            "client_id": "client_id",
            "client_secret": "client_secret",
        },
    ]


@pytest.fixture()
def mock_adobe_config(mocker, adobe_credentials_file, adobe_config_file):
    """
    Mock the Adobe Config object to load test data from the adobe_credentials and
    adobe_config_file fixtures.
    """
    mocker.patch.object(Config, "_load_credentials", return_value=adobe_credentials_file)
    mocker.patch.object(Config, "_load_config", return_value=adobe_config_file)


@pytest.fixture()
def account_data():
    """
    Returns a adobe account data structure.

    """
    return {
        "companyName": "ACME Inc",
        "preferredLanguage": "en-US",
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
    return account_data


@pytest.fixture()
def reseller_data(account_data):
    return account_data


@pytest.fixture()
def order_parameters_factory():
    def _order_parameters(
        company_name="FF Buyer good enough",
        preferred_language="en-US",
        address=None,
        contact=None,
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
                "title": "Company Name",
                "name": "Company Name",
                "externalId": "companyName",
                "type": "SingleLineText",
                "value": company_name,
                "constraints": {
                    "hidden": True,
                    "optional": True,
                },
            },
            {
                "id": "PAR-0000-0002",
                "title": "Preferred Language",
                "name": "Preferred Language",
                "externalId": "preferredLanguage",
                "type": "Choice",
                "value": preferred_language,
                "constraints": {
                    "hidden": False,
                    "optional": False,
                },
            },
            {
                "id": "PAR-0000-0002",
                "title": "Customer Address",
                "name": "Address",
                "externalId": "address",
                "type": "Address",
                "value": address,
                "constraints": {
                    "hidden": True,
                    "optional": True,
                },
            },
            {
                "id": "PAR-0000-0002",
                "title": "Customer Contact",
                "name": "Contact",
                "externalId": "contact",
                "type": "Contact",
                "value": contact,
                "constraints": {
                    "hidden": False,
                    "optional": False,
                },
            },
        ]

    return _order_parameters


@pytest.fixture()
def fulfillment_parameters_factory():
    def _fulfillment_parameters(
        customer_id="",
        retry_count="0",
    ):
        return [
            {
                "id": "PAR-1234-5678",
                "name": "Customer Id",
                "externalId": "customerId",
                "type": "SingleLineText",
                "value": customer_id,
            },
            {
                "id": "PAR-7771-1777",
                "name": "Retry Count",
                "externalId": "retryCount",
                "type": "SingleLineText",
                "value": retry_count,
            },
        ]

    return _fulfillment_parameters


@pytest.fixture()
def lines_factory():
    def _items(
        line_id=1,
        name="Awesome product",
        old_quantity=0,
        quantity=170,
    ):
        return [
            {
                "id": f"ALI-1234-1234-1234-{line_id:04d}",
                "item": {
                    "id": f"ITM-1234-1234-1234-{line_id:04d}",
                    "name": name,
                },
                "oldQuantity": old_quantity,
                "quantity": quantity,
            },
        ]

    return _items


@pytest.fixture()
def product_item_factory():
    def _product_item(
        item_id=1,
        vendor_external_id="65304578CA",
        name="Item for sale",
    ):
        return {
            "id": f"ITM-1234-1234-1234-{item_id:04d}",
            "name": name,
            "externalIds": {
                "vendor": vendor_external_id,
            },
        }

    return _product_item


@pytest.fixture()
def subscriptions_factory(lines_factory):
    def _subscriptions(
        subscription_id="SUB-1000-2000-3000",
        product_name="Awesome product",
        adobe_subscription_id="a-sub-id",
        start_date=None,
        lines=None,
    ):
        start_date = start_date.isoformat() if start_date else datetime.now(UTC).isoformat()
        lines = lines_factory() if lines is None else lines
        return [
            {
                "id": subscription_id,
                "name": f"Subscription for {product_name}",
                "parameters": {
                    "fulfillment": [
                        {
                            "name": "Subscription Id",
                            "externalId": "subscriptionId",
                            "type": "SingleLineText",
                            "value": adobe_subscription_id,
                        }
                    ]
                },
                "lines": lines,
                "startDate": start_date,
            }
        ]

    return _subscriptions


@pytest.fixture()
def agreement():
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
        "licensee": None,
        "buyer": {
            "id": "BUY-3731-7971",
            "href": "/accounts/buyers/BUY-3731-7971",
            "name": "Adam Ruszczak",
            "icon": "/static/BUY-3731-7971/icon.png",
        },
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
            "id": "PRD-1111-1111-1111",
        },
    }


@pytest.fixture()
def order_factory(
    agreement, order_parameters_factory, fulfillment_parameters_factory, lines_factory
):
    """
    Marketplace platform order for tests.
    """

    def _order(
        order_type="purchase",
        order_parameters=None,
        fulfillment_parameters=None,
        lines=None,
        subscriptions=None,
        external_ids=None,
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
            "id": "ORD-0792-5000-2253-4210",
            "href": "/commerce/orders/ORD-0792-5000-2253-4210",
            "agreement": agreement,
            "type": order_type,
            "status": "Processing",
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
        "name": "FF Buyer good enough",
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
def adobe_items_factory():
    def _items(
        line_number=1,
        offer_id="65304578CA01A12",
        quantity=170,
        subscription_id=None,
    ):
        item = {
            "extLineItemNumber": line_number,
            "offerId": offer_id,
            "quantity": quantity,
        }
        if subscription_id:
            item["subscriptionId"] = subscription_id
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
        if status in [STATUS_PENDING, STATUS_PROCESSED]:
            order["orderId"] = order_id or "P0123456789"
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
            "status": "1000",
        }

    return _subscription


@pytest.fixture()
def adobe_client_factory(adobe_credentials_file, adobe_config_file, mock_adobe_config):
    """
    Returns a factory that allow the creation of an instance
    of the AdobeClient with a fake token ready for tests.
    """

    def _factory():
        credentials = Credentials(
            adobe_credentials_file[0]["client_id"],
            adobe_credentials_file[0]["client_secret"],
            adobe_config_file["accounts"][0]["country"],
            adobe_config_file["accounts"][0]["distributor_id"],
        )
        api_token = APIToken(
            "a-token",
            expires=datetime.now() + timedelta(seconds=86000),
        )
        client = AdobeClient()
        client._token_cache[credentials] = api_token

        return client, credentials, api_token

    return _factory


@pytest.fixture()
def mpt_client(settings):
    """
    Create an instance of the MPT client used by the extension.
    """
    settings.MPT_API_BASE_URL = "https://localhost"
    from swo.mpt.extensions.runtime.events.utils import setup_client

    return setup_client()


@pytest.fixture()
def mpt_error_factory():
    """
    Generate an error message returned by the Marketplace platform.
    """

    def _mpt_error(status, title, errors):
        error = {"status": status, "title": title, "errors": errors, "traceId": "1234567890"}
        return error

    return _mpt_error


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
        },
        settings.EXTENSION_CONFIG["WEBHOOK_SECRET"],
        algorithm="HS256",
    )
