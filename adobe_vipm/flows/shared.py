import logging

from django.conf import settings

from adobe_vipm.adobe.client import get_adobe_client
from adobe_vipm.adobe.constants import STATUS_INVALID_ADDRESS, STATUS_INVALID_FIELDS
from adobe_vipm.adobe.errors import AdobeError
from adobe_vipm.flows.constants import (
    PARAM_ADDRESS,
    PARAM_COMPANY_NAME,
    PARAM_CONTACT,
    PARAM_PREFERRED_LANGUAGE,
)
from adobe_vipm.flows.mpt import fail_order, query_order, update_order
from adobe_vipm.flows.utils import (
    get_customer_data,
    reset_retry_count,
    set_adobe_customer_id,
    set_customer_data,
    set_ordering_parameter_error,
)

logger = logging.getLogger(__name__)


def _get_customer_data(client, buyer, order):
    customer_data = get_customer_data(order)
    if not all(customer_data.values()):
        order = set_customer_data(
            order,
            {
                PARAM_COMPANY_NAME: buyer["name"],
                PARAM_PREFERRED_LANGUAGE: "en-US",
                PARAM_ADDRESS: {
                    "country": buyer["address"]["country"],
                    "state": buyer["address"]["state"],
                    "city": buyer["address"]["city"],
                    "addressLine1": buyer["address"]["addressLine1"],
                    "addressLine2": buyer["address"]["addressLine2"],
                    "postCode": buyer["address"]["postCode"],
                },
                PARAM_CONTACT: {
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
    if e.code not in (STATUS_INVALID_ADDRESS, STATUS_INVALID_FIELDS):
        fail_order(client, order["id"], str(e))
        return
    if e.code == STATUS_INVALID_ADDRESS:
        order = set_ordering_parameter_error(order, PARAM_ADDRESS, str(e))
    else:
        if "companyProfile.companyName" in e.details:
            order = set_ordering_parameter_error(order, PARAM_COMPANY_NAME, str(e))
        if "companyProfile.preferredLanguage" in e.details:
            order = set_ordering_parameter_error(order, PARAM_PREFERRED_LANGUAGE, str(e))
        if len(list(filter(lambda x: x.startswith("companyProfile.contacts[0]"), e.details))):
            order = set_ordering_parameter_error(order, PARAM_CONTACT, str(e))

    order = reset_retry_count(order)
    query_order(
        client,
        order["id"],
        {
            "parameters": order["parameters"],
            "template": {"id": settings.EXTENSION_CONFIG["QUERYING_TEMPLATE_ID"]},
        },
    )


def create_customer_account(client, seller_country, buyer, order):
    adobe_client = get_adobe_client()
    try:
        customer_data, order = _get_customer_data(client, buyer, order)
        external_id = buyer["id"]
        customer_id = adobe_client.create_customer_account(
            seller_country, external_id, customer_data
        )
        order = set_adobe_customer_id(order, customer_id)
        return update_order(client, order["id"], {"parameters": order["parameters"]})
    except AdobeError as e:
        logger.error(repr(e))
        _handle_customer_error(client, order, e)
