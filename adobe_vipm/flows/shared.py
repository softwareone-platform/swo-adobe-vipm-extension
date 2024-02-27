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
from adobe_vipm.flows.mpt import (
    fail_order,
    get_agreement,
    get_product_items,
    query_order,
    update_order,
)
from adobe_vipm.flows.utils import (
    get_customer_data,
    get_parameter,
    reset_retry_count,
    set_adobe_customer_id,
    set_customer_data,
    set_ordering_parameter_error,
)

logger = logging.getLogger(__name__)


def _populate_order_lines(client, lines):
    item_ids = set([line["item"]["id"] for line in lines])

    product_items = get_product_items(client, settings.PRODUCT_ID, item_ids)
    id_sku_mapping = {
        pi["id"]: pi["externalIds"]["vendor"]
        for pi in product_items
        if pi.get("externalIds", {}).get("vendor")
    }

    for line in lines:
        line["item"]["externalIds"] = {"vendor": id_sku_mapping[line["item"]["id"]]}

    return lines


def populate_order_info(client, order):
    if "lines" in order:  # pragma: no branch
        order["lines"] = _populate_order_lines(client, order["lines"])
    order["agreement"] = get_agreement(client, order["agreement"]["id"])

    return order


def prepare_customer_data(client, order, buyer):
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
        update_order(
            client,
            order["id"],
            parameters=order["parameters"],
        )
        customer_data = get_customer_data(order)
    return order, customer_data


def _handle_customer_error(client, order, e):
    if e.code not in (STATUS_INVALID_ADDRESS, STATUS_INVALID_FIELDS):
        fail_order(client, order["id"], str(e))
        return
    if e.code == STATUS_INVALID_ADDRESS:
        param = get_parameter(order, "ordering", PARAM_ADDRESS)
        order = set_ordering_parameter_error(
            order,
            PARAM_ADDRESS,
            ERR_ADOBE_ADDRESS.to_dict(title=param["title"], details=str(e)),
        )
    else:
        if "companyProfile.companyName" in e.details:
            param = get_parameter(order, "ordering", PARAM_COMPANY_NAME)
            order = set_ordering_parameter_error(
                order,
                PARAM_COMPANY_NAME,
                ERR_ADOBE_COMPANY_NAME.to_dict(title=param["title"], details=str(e)),
            )
        if "companyProfile.preferredLanguage" in e.details:
            param = get_parameter(order, "ordering", PARAM_PREFERRED_LANGUAGE)
            order = set_ordering_parameter_error(
                order,
                PARAM_PREFERRED_LANGUAGE,
                ERR_ADOBE_PREFERRED_LANGUAGE.to_dict(title=param["title"], details=str(e)),
            )
        if len(list(filter(lambda x: x.startswith("companyProfile.contacts[0]"), e.details))):
            param = get_parameter(order, "ordering", PARAM_CONTACT)
            order = set_ordering_parameter_error(
                order,
                PARAM_CONTACT,
                ERR_ADOBE_CONTACT.to_dict(title=param["title"], details=str(e)),
            )

    order = reset_retry_count(order)
    query_order(
        client,
        order["id"],
        parameters=order["parameters"],
        templateId=settings.EXTENSION_CONFIG["QUERYING_TEMPLATE_ID"],
    )


def create_customer_account(client, seller_country, buyer, order):
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
