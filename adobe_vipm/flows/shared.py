import logging

from django.conf import settings

from adobe_vipm.adobe.client import AdobeError, get_adobe_client
from adobe_vipm.flows.mpt import fail_order, get_buyer, querying_order, update_order
from adobe_vipm.flows.utils import (
    get_customer_data,
    set_adobe_customer_id,
    set_customer_data,
    set_ordering_parameter_error,
)

logger = logging.getLogger(__name__)


def _get_customer_data(client, order):
    customer_data = get_customer_data(order)
    if not all(customer_data.values()):
        buyer_id = order["agreement"]["buyer"]["id"]
        buyer = get_buyer(client, buyer_id)
        order = set_customer_data(
            order,
            {
                "CompanyName": buyer["name"],
                "PreferredLanguage": "en-US",
                "Address": {
                    "country": buyer["address"]["country"],
                    "state": buyer["address"]["state"],
                    "city": buyer["address"]["city"],
                    "addressLine1": buyer["address"]["addressLine1"],
                    "addressLine2": buyer["address"]["addressLine2"],
                    "postCode": buyer["address"]["postCode"],
                },
                "Contact": {
                    "firstName": buyer["contact"]["firstName"],
                    "lastName": buyer["contact"]["lastName"],
                    "email": buyer["contact"]["email"],
                    "phone": buyer["contact"]["phone"],
                },
            },
        )
        order = update_order(client, order["id"], {"parameters": order["parameters"]})
        customer_data = get_customer_data(order)
    return customer_data, order


def _handle_customer_error(client, order, e):
    if e.code not in (AdobeError.INVALID_ADDRESS, AdobeError.INVALID_FIELDS):
        fail_order(client, order["id"], str(e))
        return
    if e.code == AdobeError.INVALID_ADDRESS:
        order = set_ordering_parameter_error(order, "Address", str(e))
    else:
        if "companyProfile.companyName" in e.details:
            order = set_ordering_parameter_error(order, "CompanyName", str(e))
        if "companyProfile.preferredLanguage" in e.details:
            order = set_ordering_parameter_error(order, "PreferredLanguage", str(e))
        if len(
            list(
                filter(lambda x: x.startswith("companyProfile.contacts[0]"), e.details)
            )
        ):
            order = set_ordering_parameter_error(order, "Contact", str(e))

    querying_order(
        client,
        order["id"],
        {
            "parameters": order["parameters"],
            "template": {"id": settings.EXTENSION_CONFIG["QUERYING_TEMPLATE_ID"]},
        },
    )


def create_customer_account(client, seller_country, order):
    adobe_client = get_adobe_client()
    try:
        customer_data, order = _get_customer_data(client, order)
        external_id = order["agreement"]["buyer"]["id"]
        customer_id = adobe_client.create_customer_account(
            seller_country, external_id, customer_data
        )
        order = set_adobe_customer_id(order, customer_id)
        logger.info(f"update parameters: {order['parameters']}")
        return update_order(client, order["id"], {"parameters": order["parameters"]})
    except AdobeError as e:
        logger.error(repr(e))
        _handle_customer_error(client, order, e)
