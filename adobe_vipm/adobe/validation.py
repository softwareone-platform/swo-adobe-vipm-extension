import functools

import regex as re

from adobe_vipm.adobe.config import get_config
from adobe_vipm.adobe.constants import (
    MAXLEN_ADDRESS_LINE_1,
    MAXLEN_ADDRESS_LINE_2,
    MAXLEN_CITY,
    MAXLEN_COMPANY_NAME,
    MAXLEN_PHONE_NUMBER,
    MAXLEN_POSTAL_CODE,
    MINLEN_COMPANY_NAME,
    MINQTY_CONSUMABLES,
    MINQTY_LICENSES,
    REGEX_COMPANY_NAME,
    REGEX_EMAIL,
    REGEX_FIRST_LAST_NAME,
)


def is_valid_company_name_length(name):
    """
    Check if the Company Name length is valid.

    Args:
        name (str): The Company Name string to check.

    Returns:
        bool: True if it is valid, False otherwise.
    """
    return MINLEN_COMPANY_NAME <= len(name) <= MAXLEN_COMPANY_NAME


def is_valid_company_name(name):
    """
    Check if the Company Name contains only characters allowed by the
    Adobe VIPM API.

    Args:
        name (str):  The Company Name string to check.

    Returns:
        bool: Returns True if all the characters contained in the string
        are the allowed ones, False otherwise.
    """
    return REGEX_COMPANY_NAME.match(name)


def is_valid_country(country_code):
    """
    Checks if a Country Code is one of the allowed by the
    Adobe VIPM API.

    Args:
        country_code (str): The Country Code to check for.

    Returns:
        bool: Returns True if is accepted by the Adobe VIPM API
        False otherwise.
    """
    config = get_config()
    return country_code in config.country_codes


def is_valid_state_or_province(country_code, state_or_province):
    """
    Given a Country Code, checks if the provided State or Province Code
    is valid within the Country identified by such Country Code.

    Args:
        country_code (str): A Country Code.
        state_or_province (str): The State or Provice Code to check for.

    Returns:
        bool: Returns True if the provided State or Province Code is valid
        for the Country identified by the provided Country Code, False otherwise.
    """
    config = get_config()
    country = config.get_country(country_code)
    state_code = (
        state_or_province
        if not country.provinces_to_code
        else country.provinces_to_code.get(state_or_province, state_or_province)
    )
    return state_code in country.states_or_provinces


def is_valid_postal_code(country_code, postal_code):
    """
    Checks if the Postal Code is valid within the Country
    identified by the provided Country Code.

    Args:
        country_code (str): A Country Code.
        postal_code (str): The Postal Code to check for.

    Returns:
        bool: Returns True if the providedPostal Code is valid
        for the Country identified by the provided Country Code, False otherwise.
    """
    config = get_config()
    country = config.get_country(country_code)
    return country.postal_code_format_regex is None or re.match(
        country.postal_code_format_regex, postal_code
    )


def _is_valid_maxlength(max_length, field_value):
    return len(field_value) <= max_length


def is_valid_first_last_name(name):
    """
    Check if the First or Last Name contains only characters allowed by the
    Adobe VIPM API.

    Args:
        name (str):  The First or Last Name string to check.

    Returns:
        bool: Returns True if all the characters contained in the string
        are the allowed ones, False otherwise.
    """
    return REGEX_FIRST_LAST_NAME.match(name)


def is_valid_email(email):
    """
    Check if the provided email is a valid email address.

    Args:
        email (str):  The Email string to check.

    Returns:
        bool: Returns True if it is a valid email address, False otherwise.
    """
    return REGEX_EMAIL.match(email)


def _is_valid_minimum_quantity(minimum, quantity):
    if not quantity:
        return True

    p3yc_qty = -1
    try:
        p3yc_qty = int(quantity)
    except ValueError:
        pass

    return p3yc_qty >= minimum


is_valid_postal_code_length = functools.partial(_is_valid_maxlength, MAXLEN_POSTAL_CODE)
is_valid_address_line_1_length = functools.partial(
    _is_valid_maxlength, MAXLEN_ADDRESS_LINE_1
)
is_valid_address_line_2_length = functools.partial(
    _is_valid_maxlength, MAXLEN_ADDRESS_LINE_2
)
is_valid_city_length = functools.partial(_is_valid_maxlength, MAXLEN_CITY)
is_valid_phone_number_length = functools.partial(
    _is_valid_maxlength, MAXLEN_PHONE_NUMBER
)

is_valid_minimum_licenses = functools.partial(
    _is_valid_minimum_quantity, MINQTY_LICENSES
)
is_valid_minimum_consumables = functools.partial(
    _is_valid_minimum_quantity, MINQTY_CONSUMABLES
)
