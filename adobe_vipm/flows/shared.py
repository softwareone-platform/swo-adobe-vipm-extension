import logging

from django.conf import settings

from adobe_vipm.adobe.client import get_adobe_client
from adobe_vipm.adobe.constants import STATUS_INVALID_ADDRESS, STATUS_INVALID_FIELDS
from adobe_vipm.adobe.errors import AdobeError
from adobe_vipm.flows.constants import (
    ERR_ADOBE_ADDRESS,
    ERR_ADOBE_COMPANY_NAME,
    ERR_ADOBE_CONTACT,
    ERR_ADOBE_PREFERRED_LANGUAGE,
    PARAM_ADDRESS,
    PARAM_COMPANY_NAME,
    PARAM_CONTACT,
    PARAM_PREFERRED_LANGUAGE,
)
from adobe_vipm.flows.mpt import fail_order, get_agreement, query_order, update_order
from adobe_vipm.flows.utils import (
    get_customer_data,
    get_ordering_parameter,
    reset_retry_count,
    set_adobe_customer_id,
    set_customer_data,
    set_ordering_parameter_error,
)

logger = logging.getLogger(__name__)


def populate_order_info(client, order):
    order["agreement"] = get_agreement(client, order["agreement"]["id"])

    return order


def prepare_customer_data(client, order, buyer):
    """
    Try to get customer data from ordering parameters. If they are empty,
    they will be filled with data from the buyer object related to the
    current order that will than be updated.

    Args:
        client (MPTClient): an instance of the Marketplace platform client.
        order (dict): the order that is being processed.
        buyer (dict): the buyer that can be used to take the customer data
        from.

    Returns:
        tuple: a tuple which first item is the updated order and the second
        a dictionary with the data of the customer that must be created in Adobe.
    """
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
                    "postalCode": buyer["address"]["postCode"],
                },
                PARAM_CONTACT: {
                    "firstName": buyer["contact"]["firstName"],
                    "lastName": buyer["contact"]["lastName"],
                    "email": buyer["contact"]["email"],
                    "phone": buyer["contact"]["phone"],
                },
            },
        )
        update_order(
            client,
            order["id"],
            parameters=order["parameters"],
        )
        customer_data = get_customer_data(order)
    return order, customer_data


def _handle_customer_error(client, order, e):
    """
    Process the error received from the Adobe API during the customer creation.
    If the error is related to a customer parameter, the parameter error attribute
    is set and the MPT order is switched to the `query` status.
    Other errors will result in the MPT order to be failed.

    Args:
        client (MPTClient): an instance of the Marketplace platform client.
        order (dict): The MPT order that is being processed.
        e (AdobeAPIError): The error received by the Adobe API.
    """
    if e.code not in (STATUS_INVALID_ADDRESS, STATUS_INVALID_FIELDS):
        fail_order(client, order["id"], str(e))
        return
    if e.code == STATUS_INVALID_ADDRESS:
        param = get_ordering_parameter(order, PARAM_ADDRESS)
        order = set_ordering_parameter_error(
            order,
            PARAM_ADDRESS,
            ERR_ADOBE_ADDRESS.to_dict(title=param["name"], details=str(e)),
        )
    else:
        if "companyProfile.companyName" in e.details:
            param = get_ordering_parameter(order, PARAM_COMPANY_NAME)
            order = set_ordering_parameter_error(
                order,
                PARAM_COMPANY_NAME,
                ERR_ADOBE_COMPANY_NAME.to_dict(title=param["name"], details=str(e)),
            )
        if "companyProfile.preferredLanguage" in e.details:
            param = get_ordering_parameter(order, PARAM_PREFERRED_LANGUAGE)
            order = set_ordering_parameter_error(
                order,
                PARAM_PREFERRED_LANGUAGE,
                ERR_ADOBE_PREFERRED_LANGUAGE.to_dict(
                    title=param["name"], details=str(e)
                ),
            )
        if len(
            list(
                filter(lambda x: x.startswith("companyProfile.contacts[0]"), e.details)
            )
        ):
            param = get_ordering_parameter(order, PARAM_CONTACT)
            order = set_ordering_parameter_error(
                order,
                PARAM_CONTACT,
                ERR_ADOBE_CONTACT.to_dict(title=param["name"], details=str(e)),
            )

    order = reset_retry_count(order)
    query_order(
        client,
        order["id"],
        parameters=order["parameters"],
        templateId=settings.EXTENSION_CONFIG["QUERYING_TEMPLATE_ID"],
    )


def create_customer_account(client, seller_country, buyer, order):
    """
    Create a customer account in Adobe for the new agreement
    that belong to the order that is being processed.

    Args:
        client (MPTClient): an instance of the Marketplace platform client.
        seller_country (str): the country of the seller of the current order
        used to select the right credentials to access the Adobe API.
        buyer (dict): the buyer attached to the current order.
        order (dict): the order that is being processed.

    Returns:
        dict: The order updated with the customer id set on the corresponding
        fulfillment parameter.
    """
    adobe_client = get_adobe_client()
    try:
        order, customer_data = prepare_customer_data(client, order, buyer)
        external_id = order["agreement"]["id"]
        customer_id = adobe_client.create_customer_account(
            seller_country, external_id, customer_data
        )
        order = set_adobe_customer_id(order, customer_id)
        update_order(client, order["id"], parameters=order["parameters"])
        return order
    except AdobeError as e:
        logger.error(repr(e))
        _handle_customer_error(client, order, e)
