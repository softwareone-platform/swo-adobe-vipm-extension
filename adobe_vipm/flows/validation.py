import logging
import re

from adobe_vipm.adobe.config import get_config
from adobe_vipm.adobe.utils import join_phone_number
from adobe_vipm.flows.constants import (
    ERR_ADDRESS,
    ERR_ADDRESS_LINE_1_LENGTH,
    ERR_ADDRESS_LINE_2_LENGTH,
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
    ORDER_TYPE_PURCHASE,
    PARAM_ADDRESS,
    PARAM_COMPANY_NAME,
    PARAM_CONTACT,
    PARAM_PREFERRED_LANGUAGE,
    REGEX_COMPANY_NAME,
    REGEX_EMAIL,
    REGEX_FIRST_LAST_NAME,
)
from adobe_vipm.flows.mpt import get_buyer
from adobe_vipm.flows.shared import populate_order_info, prepare_customer_data
from adobe_vipm.flows.utils import get_parameter, set_ordering_parameter_error

logger = logging.getLogger(__name__)


def validate_company_name(order, customer_data):
    param = get_parameter(order, "ordering", PARAM_COMPANY_NAME)
    name = customer_data[PARAM_COMPANY_NAME]
    if not (MINLEN_COMPANY_NAME <= len(name) <= MAXLEN_COMPANY_NAME):
        order = set_ordering_parameter_error(
            order,
            PARAM_COMPANY_NAME,
            ERR_COMPANY_NAME_LENGTH.to_dict(title=param["title"]),
        )
        return True, order
    if not REGEX_COMPANY_NAME.match(name):
        order = set_ordering_parameter_error(
            order,
            PARAM_COMPANY_NAME,
            ERR_COMPANY_NAME_CHARS.to_dict(title=param["title"]),
        )
        return True, order
    return False, order


def validate_preferred_language(order, customer_data):
    config = get_config()
    param = get_parameter(order, "ordering", PARAM_PREFERRED_LANGUAGE)
    if customer_data[PARAM_PREFERRED_LANGUAGE] not in config.language_codes:
        order = set_ordering_parameter_error(
            order,
            PARAM_PREFERRED_LANGUAGE,
            ERR_PREFERRED_LANGUAGE.to_dict(
                title=param["title"],
                languages=", ".join(config.language_codes),
            ),
        )
        return True, order
    return False, order


def validate_address(order, customer_data):
    config = get_config()
    param = get_parameter(order, "ordering", PARAM_ADDRESS)
    address = customer_data[PARAM_ADDRESS]
    errors = []

    if address["country"] not in config.country_codes:
        errors.append(ERR_COUNTRY_CODE)
        order = set_ordering_parameter_error(
            order,
            PARAM_ADDRESS,
            ERR_ADDRESS.to_dict(
                title=param["title"],
                errors="".join(errors),
            ),
        )
        return True, order

    country = config.get_country(address["country"])
    if address["state"] not in country.states_or_provinces:
        errors.append(ERR_STATE_OR_PROVINCE)

    if country.postal_code_format_regex and not re.match(
        country.postal_code_format_regex, address["postCode"]
    ):
        errors.append(ERR_POSTAL_CODE_FORMAT)

    for field, max_len, err_msg in (
        ("postCode", MAXLEN_POSTAL_CODE, ERR_POSTAL_CODE_LENGTH),
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
                title=param["title"],
                errors="; ".join(errors),
            ),
        )
        return True, order
    return False, order


def validate_contact(order, customer_data):
    contact = customer_data[PARAM_CONTACT]
    param = get_parameter(order, "ordering", PARAM_CONTACT)
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
                title=param["title"],
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


def validate_order(client, order):
    order = populate_order_info(client, order)
    has_errors = False
    if order["type"] == ORDER_TYPE_PURCHASE:  # pragma: no branch
        buyer_id = order["agreement"]["buyer"]["id"]
        buyer = get_buyer(client, buyer_id)
        order, customer_data = prepare_customer_data(client, order, buyer)
        has_errors, order = validate_customer_data(order, customer_data)

    logger.info(
        f"Validation of order {order['id']} succeeded with{'out' if not has_errors else ''} errors"
    )
    return order
