import logging
import re

from adobe_vipm.adobe.client import get_adobe_client
from adobe_vipm.adobe.config import get_config
from adobe_vipm.adobe.errors import AdobeAPIError
from adobe_vipm.adobe.utils import join_phone_number
from adobe_vipm.flows.constants import (
    ERR_ADDRESS,
    ERR_ADDRESS_LINE_1_LENGTH,
    ERR_ADDRESS_LINE_2_LENGTH,
    ERR_ADOBE_MEMBERSHIP_ID,
    ERR_ADOBE_MEMBERSHIP_ID_ITEM,
    ERR_CITY_LENGTH,
    ERR_COMPANY_NAME_CHARS,
    ERR_COMPANY_NAME_LENGTH,
    ERR_CONTACT,
    ERR_COUNTRY_CODE,
    ERR_EMAIL_FORMAT,
    ERR_FIRST_NAME_FORMAT,
    ERR_LAST_NAME_FORMAT,
    ERR_PHONE_NUMBER_LENGTH,
    ERR_POSTAL_CODE_FORMAT,
    ERR_POSTAL_CODE_LENGTH,
    ERR_PREFERRED_LANGUAGE,
    ERR_STATE_OR_PROVINCE,
    MAXLEN_ADDRESS_LINE_1,
    MAXLEN_ADDRESS_LINE_2,
    MAXLEN_CITY,
    MAXLEN_COMPANY_NAME,
    MAXLEN_PHONE_NUMBER,
    MAXLEN_POSTAL_CODE,
    MINLEN_COMPANY_NAME,
    PARAM_ADDRESS,
    PARAM_COMPANY_NAME,
    PARAM_CONTACT,
    PARAM_MEMBERSHIP_ID,
    PARAM_PREFERRED_LANGUAGE,
    REGEX_COMPANY_NAME,
    REGEX_EMAIL,
    REGEX_FIRST_LAST_NAME,
)
from adobe_vipm.flows.helpers import (
    populate_order_info,
    prepare_customer_data,
    update_purchase_prices,
)
from adobe_vipm.flows.mpt import get_buyer, get_product_items_by_skus
from adobe_vipm.flows.utils import (
    get_adobe_membership_id,
    get_ordering_parameter,
    is_purchase_order,
    is_transfer_order,
    set_ordering_parameter_error,
)

logger = logging.getLogger(__name__)


def validate_company_name(order, customer_data):
    param = get_ordering_parameter(order, PARAM_COMPANY_NAME)
    name = customer_data[PARAM_COMPANY_NAME]
    if not (MINLEN_COMPANY_NAME <= len(name) <= MAXLEN_COMPANY_NAME):
        order = set_ordering_parameter_error(
            order,
            PARAM_COMPANY_NAME,
            ERR_COMPANY_NAME_LENGTH.to_dict(title=param["name"]),
        )
        return True, order
    if not REGEX_COMPANY_NAME.match(name):
        order = set_ordering_parameter_error(
            order,
            PARAM_COMPANY_NAME,
            ERR_COMPANY_NAME_CHARS.to_dict(title=param["name"]),
        )
        return True, order
    return False, order


def validate_preferred_language(order, customer_data):
    config = get_config()
    param = get_ordering_parameter(order, PARAM_PREFERRED_LANGUAGE)
    if customer_data[PARAM_PREFERRED_LANGUAGE] not in config.language_codes:
        order = set_ordering_parameter_error(
            order,
            PARAM_PREFERRED_LANGUAGE,
            ERR_PREFERRED_LANGUAGE.to_dict(
                title=param["name"],
                languages=", ".join(config.language_codes),
            ),
        )
        return True, order
    return False, order


def validate_address(order, customer_data):
    config = get_config()
    param = get_ordering_parameter(order, PARAM_ADDRESS)
    address = customer_data[PARAM_ADDRESS]
    errors = []

    if address["country"] not in config.country_codes:
        errors.append(ERR_COUNTRY_CODE)
        order = set_ordering_parameter_error(
            order,
            PARAM_ADDRESS,
            ERR_ADDRESS.to_dict(
                title=param["name"],
                errors="".join(errors),
            ),
        )
        return True, order

    country = config.get_country(address["country"])
    if address["state"] not in country.states_or_provinces:
        errors.append(ERR_STATE_OR_PROVINCE)

    if country.postal_code_format_regex and not re.match(
        country.postal_code_format_regex, address["postalCode"]
    ):
        errors.append(ERR_POSTAL_CODE_FORMAT)

    for field, max_len, err_msg in (
        ("postalCode", MAXLEN_POSTAL_CODE, ERR_POSTAL_CODE_LENGTH),
        ("addressLine1", MAXLEN_ADDRESS_LINE_1, ERR_ADDRESS_LINE_1_LENGTH),
        ("addressLine2", MAXLEN_ADDRESS_LINE_2, ERR_ADDRESS_LINE_2_LENGTH),
        ("city", MAXLEN_CITY, ERR_CITY_LENGTH),
    ):
        if len(address[field]) > max_len:
            errors.append(err_msg)

    if errors:
        order = set_ordering_parameter_error(
            order,
            PARAM_ADDRESS,
            ERR_ADDRESS.to_dict(
                title=param["name"],
                errors="; ".join(errors),
            ),
        )
        return True, order
    return False, order


def validate_contact(order, customer_data):
    contact = customer_data[PARAM_CONTACT]
    param = get_ordering_parameter(order, PARAM_CONTACT)
    errors = []

    if not REGEX_FIRST_LAST_NAME.match(contact["firstName"]):
        errors.append(ERR_FIRST_NAME_FORMAT)

    if not REGEX_FIRST_LAST_NAME.match(contact["lastName"]):
        errors.append(ERR_LAST_NAME_FORMAT)

    if not REGEX_EMAIL.match(contact["email"]):
        errors.append(ERR_EMAIL_FORMAT)

    if contact.get("phone"):
        contact_phone = join_phone_number(contact["phone"])

        if len(contact_phone) > MAXLEN_PHONE_NUMBER:
            errors.append(ERR_PHONE_NUMBER_LENGTH)

    if errors:
        order = set_ordering_parameter_error(
            order,
            PARAM_CONTACT,
            ERR_CONTACT.to_dict(
                title=param["name"],
                errors="; ".join(errors),
            ),
        )
        return True, order
    return False, order


def validate_customer_data(order, customer_data):
    has_errors = False

    has_error, order = validate_company_name(order, customer_data)
    has_errors = has_errors or has_error

    has_error, order = validate_preferred_language(order, customer_data)
    has_errors = has_errors or has_error

    has_error, order = validate_address(order, customer_data)
    has_errors = has_errors or has_error

    has_error, order = validate_contact(order, customer_data)
    has_errors = has_errors or has_error

    return has_errors, order


def validate_transfer(mpt_client, order):
    seller_country = order["agreement"]["seller"]["address"]["country"]
    membership_id = get_adobe_membership_id(order)
    adobe_client = get_adobe_client()
    transfer_preview = None
    try:
        transfer_preview = adobe_client.preview_transfer(
            seller_country,
            membership_id,
        )
    except AdobeAPIError as e:
        param = get_ordering_parameter(order, PARAM_MEMBERSHIP_ID)
        order = set_ordering_parameter_error(
            order,
            PARAM_MEMBERSHIP_ID,
            ERR_ADOBE_MEMBERSHIP_ID.to_dict(title=param["name"], details=str(e)),
        )
        return True, order

    returned_skus = [item["offerId"][:10] for item in transfer_preview["items"]]

    items_map = {
        item["externalIds"]["vendor"]: item
        for item in get_product_items_by_skus(
            mpt_client, order["agreement"]["product"]["id"], returned_skus
        )
    }
    lines = []
    for adobe_line in transfer_preview["items"]:
        item = items_map.get(adobe_line["offerId"][:10])
        if not item:
            param = get_ordering_parameter(order, PARAM_MEMBERSHIP_ID)
            order = set_ordering_parameter_error(
                order,
                PARAM_MEMBERSHIP_ID,
                ERR_ADOBE_MEMBERSHIP_ID_ITEM.to_dict(
                    title=param["name"],
                    item_sku=adobe_line["offerId"][:10],
                ),
            )
            return True, order
        lines.append(
            {
                "item": item,
                "quantity": adobe_line["quantity"],
                "oldQuantity": 0,
            },
        )
    order["lines"] = lines
    return False, order


def validate_order(mpt_client, order):
    order = populate_order_info(mpt_client, order)
    has_errors = False
    if is_purchase_order(order):
        buyer_id = order["agreement"]["buyer"]["id"]
        buyer = get_buyer(mpt_client, buyer_id)
        order, customer_data = prepare_customer_data(mpt_client, order, buyer)
        has_errors, order = validate_customer_data(order, customer_data)
    elif is_transfer_order(order):  # pragma: no branch
        has_errors, order = validate_transfer(mpt_client, order)
    if not has_errors:
        adobe_client = get_adobe_client()
        seller_country = order["agreement"]["seller"]["address"]["country"]
        order = update_purchase_prices(mpt_client, adobe_client, seller_country, order)
    logger.info(
        f"Validation of order {order['id']} succeeded with{'out' if not has_errors else ''} errors"
    )
    return order
