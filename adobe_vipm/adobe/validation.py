import functools
import re

from adobe_vipm.adobe.config import get_config
from adobe_vipm.adobe.constants import (
    MAXLEN_ADDRESS_LINE_1,
    MAXLEN_ADDRESS_LINE_2,
    MAXLEN_CITY,
    MAXLEN_COMPANY_NAME,
    MAXLEN_PHONE_NUMBER,
    MAXLEN_POSTAL_CODE,
    MINLEN_COMPANY_NAME,
    REGEX_COMPANY_NAME,
    REGEX_EMAIL,
    REGEX_FIRST_LAST_NAME,
)


def is_valid_company_name_length(name):
    return (MINLEN_COMPANY_NAME <= len(name) <= MAXLEN_COMPANY_NAME)


def is_valid_company_name(name):
    return REGEX_COMPANY_NAME.match(name)


def is_valid_preferred_language(language_code):
    config = get_config()
    return language_code in config.language_codes


def is_valid_country(country_code):
    config = get_config()
    return country_code in config.country_codes


def is_valid_state_or_province(country_code, state_or_province):
    config = get_config()
    country = config.get_country(country_code)
    return state_or_province in country.states_or_provinces


def is_valid_postal_code(country_code, postal_code):
    config = get_config()
    country = config.get_country(country_code)
    return country.postal_code_format_regex is None or re.match(
        country.postal_code_format_regex, postal_code
    )


def _is_valid_maxlength(max_length, field_value):
    return len(field_value) <= max_length


def is_valid_first_last_name(name):
    return REGEX_FIRST_LAST_NAME.match(name)


def is_valid_email(email):
    return REGEX_EMAIL.match(email)


is_valid_postal_code_length = functools.partial(_is_valid_maxlength, MAXLEN_POSTAL_CODE)
is_valid_address_line_1_length = functools.partial(_is_valid_maxlength, MAXLEN_ADDRESS_LINE_1)
is_valid_address_line_2_length = functools.partial(_is_valid_maxlength, MAXLEN_ADDRESS_LINE_2)
is_valid_city_length = functools.partial(_is_valid_maxlength, MAXLEN_CITY)
is_valid_phone_number_length = functools.partial(_is_valid_maxlength, MAXLEN_PHONE_NUMBER)