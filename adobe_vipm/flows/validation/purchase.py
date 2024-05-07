import logging

from adobe_vipm.adobe.utils import join_phone_number
from adobe_vipm.adobe.validation import (
    is_valid_address_line_1_length,
    is_valid_address_line_2_length,
    is_valid_city_length,
    is_valid_company_name,
    is_valid_company_name_length,
    is_valid_country,
    is_valid_email,
    is_valid_first_last_name,
    is_valid_minimum_consumables,
    is_valid_minimum_licenses,
    is_valid_phone_number_length,
    is_valid_postal_code,
    is_valid_postal_code_length,
    is_valid_state_or_province,
)
from adobe_vipm.flows.constants import (
    ERR_3YC_NO_MINIMUMS,
    ERR_3YC_QUANTITY_CONSUMABLES,
    ERR_3YC_QUANTITY_LICENSES,
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
    ERR_STATE_OR_PROVINCE,
    PARAM_3YC,
    PARAM_3YC_CONSUMABLES,
    PARAM_3YC_LICENSES,
    PARAM_ADDRESS,
    PARAM_COMPANY_NAME,
    PARAM_CONTACT,
)
from adobe_vipm.flows.utils import (
    get_ordering_parameter,
    set_order_error,
    set_ordering_parameter_error,
)

logger = logging.getLogger(__name__)


def validate_3yc(order, customer_data):
    p3yc = customer_data[PARAM_3YC]

    if p3yc != ["Yes"]:
        return False, order

    errors = False

    for param_name, validator, error in (
        (
            PARAM_3YC_CONSUMABLES,
            is_valid_minimum_consumables,
            ERR_3YC_QUANTITY_CONSUMABLES,
        ),
        (PARAM_3YC_LICENSES, is_valid_minimum_licenses, ERR_3YC_QUANTITY_LICENSES),
    ):
        param = get_ordering_parameter(order, param_name)

        if not validator(customer_data[param_name]):
            errors = True
            order = set_ordering_parameter_error(
                order,
                param_name,
                error.to_dict(title=param["name"]),
                optional=True,
            )

    if not errors and not (
        customer_data[PARAM_3YC_LICENSES] or customer_data[PARAM_3YC_CONSUMABLES]
    ):
        errors = True
        param_licenses = get_ordering_parameter(order, PARAM_3YC_LICENSES)
        param_consumables = get_ordering_parameter(order, PARAM_3YC_CONSUMABLES)
        order = set_order_error(
            order,
            ERR_3YC_NO_MINIMUMS.to_dict(
                title_min_licenses=param_licenses["name"],
                title_min_consumables=param_consumables["name"],
            ),
        )

    return errors, order


def validate_company_name(order, customer_data):
    param = get_ordering_parameter(order, PARAM_COMPANY_NAME)
    name = customer_data[PARAM_COMPANY_NAME]
    if not is_valid_company_name_length(name):
        order = set_ordering_parameter_error(
            order,
            PARAM_COMPANY_NAME,
            ERR_COMPANY_NAME_LENGTH.to_dict(title=param["name"]),
        )
        return True, order
    if not is_valid_company_name(name):
        order = set_ordering_parameter_error(
            order,
            PARAM_COMPANY_NAME,
            ERR_COMPANY_NAME_CHARS.to_dict(title=param["name"]),
        )
        return True, order
    return False, order


def validate_address(order, customer_data):
    param = get_ordering_parameter(order, PARAM_ADDRESS)
    address = customer_data[PARAM_ADDRESS]
    errors = []

    country_code = address["country"]

    if not is_valid_country(country_code):
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

    if not is_valid_state_or_province(country_code, address["state"]):
        errors.append(ERR_STATE_OR_PROVINCE)

    if not is_valid_postal_code(country_code, address["postCode"]):
        errors.append(ERR_POSTAL_CODE_FORMAT)

    for field, validator_func, err_msg in (
        ("postCode", is_valid_postal_code_length, ERR_POSTAL_CODE_LENGTH),
        ("addressLine1", is_valid_address_line_1_length, ERR_ADDRESS_LINE_1_LENGTH),
        ("addressLine2", is_valid_address_line_2_length, ERR_ADDRESS_LINE_2_LENGTH),
        ("city", is_valid_city_length, ERR_CITY_LENGTH),
    ):
        if not validator_func(address[field]):
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

    if not contact:
        order = set_ordering_parameter_error(
            order,
            PARAM_CONTACT,
            ERR_CONTACT.to_dict(
                title=param["name"],
                errors="it is mandatory.",
            ),
        )
        return True, order

    if not is_valid_first_last_name(contact["firstName"]):
        errors.append(ERR_FIRST_NAME_FORMAT)

    if not is_valid_first_last_name(contact["lastName"]):
        errors.append(ERR_LAST_NAME_FORMAT)

    if not is_valid_email(contact["email"]):
        errors.append(ERR_EMAIL_FORMAT)

    if contact.get("phone") and not is_valid_phone_number_length(
        join_phone_number(contact["phone"])
    ):
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

    has_error, order = validate_address(order, customer_data)
    has_errors = has_errors or has_error

    has_error, order = validate_contact(order, customer_data)
    has_errors = has_errors or has_error

    has_error, order = validate_3yc(order, customer_data)
    has_errors = has_errors or has_error

    return has_errors, order
