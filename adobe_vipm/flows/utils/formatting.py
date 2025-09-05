import re

import phonenumbers
from markdown_it import MarkdownIt

TRACE_ID_REGEX = re.compile(r"(\(00-[0-9a-f]{32}-[0-9a-f]{16}-01\))")


def split_phone_number(phone_number: str, country: str) -> dict:
    """
    Splits phone number to components.

    Args:
        phone_number: phone number.
        country: country code.

    Returns:
        Formatted phone number dictionary with 'prefix' and 'number' properties.
    """
    if not phone_number:
        return None

    pn = None
    try:
        pn = phonenumbers.parse(phone_number, keep_raw_input=True)
    except phonenumbers.NumberParseException:
        try:
            pn = phonenumbers.parse(phone_number, country, keep_raw_input=True)
        except phonenumbers.NumberParseException:
            return None

    country_code = f"+{pn.country_code}"
    leading_zero = "0" if pn.italian_leading_zero else ""
    number = f"{leading_zero}{pn.national_number}{pn.extension or ''}".strip()
    return {
        "prefix": country_code,
        "number": number,
    }


def md2html(template: str) -> str:
    """Converts MD template to html."""
    return MarkdownIt("commonmark", {"breaks": True, "html": True}).render(template)


def strip_trace_id(traceback: str) -> str:
    """Strip <omitter> from traceback."""
    return TRACE_ID_REGEX.sub("(<omitted>)", traceback)


def get_address(address: dict) -> dict:
    """
    Set the address fields in the address object.

    Args:
        address: The address to set.

    Returns:
        Mapped dictionary of the Adobe address following MPT Address type parameter format.
    """
    return {
        "country": address.get("country", ""),
        "state": address.get("region", ""),
        "city": address.get("city", ""),
        "addressLine1": address.get("addressLine1", ""),
        "addressLine2": address.get("addressLine2", ""),
        "postCode": address.get("postalCode", ""),
    }
