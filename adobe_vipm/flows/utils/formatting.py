import re

import phonenumbers
from markdown_it import MarkdownIt

TRACE_ID_REGEX = re.compile(r"(\(00-[0-9a-f]{32}-[0-9a-f]{16}-01\))")


def split_phone_number(phone_number, country):
    if not phone_number:
        return

    pn = None
    try:
        pn = phonenumbers.parse(phone_number, keep_raw_input=True)
    except phonenumbers.NumberParseException:
        try:
            pn = phonenumbers.parse(phone_number, country, keep_raw_input=True)
        except phonenumbers.NumberParseException:
            return

    country_code = f"+{pn.country_code}"
    leading_zero = "0" if pn.italian_leading_zero else ""
    number = f"{leading_zero}{pn.national_number}{pn.extension or ''}".strip()
    return {
        "prefix": country_code,
        "number": number,
    }


def md2html(template):
    return MarkdownIt("commonmark", {"breaks": True, "html": True}).render(template)


def strip_trace_id(traceback):
    return TRACE_ID_REGEX.sub("(<omitted>)", traceback)


def get_address(data):
    """
    Set the address fields in the address object.
    Args:
        address (dict): The address object to update.
        data (dict): The data to set.
    """
    return {
        "country": data.get("country", ""),
        "state": data.get("region", ""),
        "city": data.get("city", ""),
        "addressLine1": data.get("addressLine1", ""),
        "addressLine2": data.get("addressLine2", ""),
        "postCode": data.get("postalCode", ""),
    }
