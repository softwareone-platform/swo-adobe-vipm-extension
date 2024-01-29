from datetime import datetime, timedelta

import pytest
import responses

from adobe_vipm.adobe.client import AdobeClient
from adobe_vipm.adobe.config import Config
from adobe_vipm.adobe.constants import STATUS_PENDING, STATUS_PROCESSED
from adobe_vipm.adobe.dataclasses import APIToken, Credentials


def get_reference(obj, fields=None):
    return {
        k: v for k, v in obj.items() if k in (fields or ("id", "href", "name", "icon", "product"))
    }


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
        "accounts": [
            {
                "region": "NA",
                "client_id": "client_id",
                "client_secret": "client_secret",
                "distributor_id": "distributor_id",
                "resellers": [{"id": "P1000040545", "country": "US"}],
            }
        ],
        "skus_mapping": [
            {
                "product_item_id": "65304578CA",
                "name": "Test product",
                "sku": "65304578CA01A12",
                "type": "TEAM",
            },
        ],
    }


@pytest.fixture()
def mock_adobe_config(mocker, adobe_config_file):
    """
    Mock the Adobe Config object to load test data from the adobe_config_file fixture.
    """
    mocker.patch.object(Config, "_load_config", return_value=adobe_config_file)


@pytest.fixture()
def account_data():
    """
    Returns a adobe account data structure.

    """
    return {
        "CompanyName": "ACME Inc",
        "PreferredLanguage": "en-US",
        "Address": {
            "country": "US",
            "state": "CA",
            "city": "Irvine",
            "addressLine1": "Test street",
            "addressLine2": "Line 2",
            "postCode": "08010",
        },
        "Contact": {
            "firstName": "First Name",
            "lastName": "Last Name",
            "email": "test@example.com",
            "phone": "+22003939393",
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
                "phone": "+14082954078",
            }
        return [
            {
                "id": "PAR-0000-0001",
                "name": "CompanyName",
                "value": company_name,
            },
            {
                "id": "PAR-0000-0002",
                "name": "PreferredLanguage",
                "value": preferred_language,
            },
            {
                "id": "PAR-0000-0002",
                "name": "Address",
                "value": address,
            },
            {
                "id": "PAR-0000-0002",
                "name": "Contact",
                "value": contact,
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
            {"id": "PAR-1234-5678", "name": "CustomerId", "value": customer_id},
            {"id": "PAR-7771-1777", "name": "RetryCount", "value": retry_count},
        ]

    return _fulfillment_parameters


@pytest.fixture()
def items_factory():
    def _items(
        line_number=1,
        product_item_id="65304578CA",
        name="Awesome product",
        old_quantity=0,
        quantity=170,
    ):
        return [
            {
                "lineNumber": line_number,
                "productItemId": product_item_id,
                "name": name,
                "oldQuantity": old_quantity,
                "quantity": quantity,
            },
        ]

    return _items


@pytest.fixture()
def subscriptions_factory(items_factory):
    def _subscriptions(
        subscription_id="SUB-1000-2000-3000",
        product_name="Awesome product",
        adobe_subscription_id="ffe5d0e78b411fa199dd29401ba37bNA",
        start_date="2024-01-11T08:53:37Z",
        items=None,
    ):
        items = items_factory() if items is None else items
        return [
            {
                "id": subscription_id,
                "name": f"Subscription for {product_name}",
                "parameters": {
                    "fulfillment": [
                        {
                            "name": "SubscriptionId",
                            "value": adobe_subscription_id,
                        }
                    ]
                },
                "items": items,
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
        },
        "product": {
            "id": "PRD-1111-1111-1111",
        },
    }


@pytest.fixture()
def order_factory(
    agreement, order_parameters_factory, fulfillment_parameters_factory, items_factory
):
    """
    Marketplace platform order for tests.
    """

    def _order(
        order_type="Purchase",
        order_parameters=None,
        fulfillment_parameters=None,
        items=None,
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

        items = items_factory() if items is None else items
        subscriptions = [] if subscriptions is None else subscriptions

        order = {
            "id": "ORD-0792-5000-2253-4210",
            "href": "/commerce/orders/ORD-0792-5000-2253-4210",
            "agreement": get_reference(agreement),
            "type": order_type,
            "status": "Processing",
            "clientReferenceNumber": None,
            "notes": "First order to try",
            "items": items,
            "subscriptions": subscriptions,
            "parameters": {
                "fulfillment": fulfillment_parameters,
                "order": order_parameters,
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
            order["externalIDs"] = external_ids
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
            "phone": "+14082954078",
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
            "phone": "+14082954078",
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
def adobe_client_factory(adobe_config_file, mock_adobe_config):
    """
    Returns a factory that allow the creation of an instance
    of the AdobeClient with a fake token ready for tests.
    """

    def _factory():
        credentials = Credentials(
            adobe_config_file["accounts"][0]["client_id"],
            adobe_config_file["accounts"][0]["client_secret"],
            adobe_config_file["accounts"][0]["region"],
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

    def _mpt_error(status, title, details):
        error = {"status": status, "title": title, "details": details}
        return error

    return _mpt_error
