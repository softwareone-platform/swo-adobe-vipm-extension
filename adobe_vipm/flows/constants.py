import re

from adobe_vipm.flows.errors import ValidationError

ORDER_TYPE_PURCHASE = "purchase"
ORDER_TYPE_CHANGE = "change"
ORDER_TYPE_TERMINATION = "termination"

PARAM_ADDRESS = "address"
PARAM_COMPANY_NAME = "companyName"
PARAM_CONTACT = "contact"
PARAM_CUSTOMER_ID = "customerId"
PARAM_MEMBERSHIP_ID = "membershipId"
PARAM_PREFERRED_LANGUAGE = "preferredLanguage"
PARAM_RETRY_COUNT = "retryCount"
PARAM_SUBSCRIPTION_ID = "subscriptionId"

PARAM_PHASE_ORDERING = "ordering"
PARAM_PHASE_FULFILLMENT = "fulfillment"

CANCELLATION_WINDOW_DAYS = 14

MINLEN_COMPANY_NAME = 4
MINLEN_NAME = 1
MAXLEN_POSTAL_CODE = 40
MAXLEN_CITY = 40
MAXLEN_ADDRESS_LINE_1 = 60
MAXLEN_ADDRESS_LINE_2 = 60
MAXLEN_PHONE_NUMBER = 40
MAXLEN_COMPANY_NAME = 59
MAXLEN_NAME = 35

REGEX_COMPANY_NAME = re.compile(r"^[\w ,.＆&・\'()（）\\\"/-]*$")
REGEX_FIRST_LAST_NAME = re.compile(r"^[\w ,.＆&'\\\"]*$")
REGEX_EMAIL = re.compile(r"^[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+$")

ADOBE_ERR_MSG = "The `{title}` is not valid: {details}."

ERR_ADOBE_COMPANY_NAME = ValidationError("VIPMA001", ADOBE_ERR_MSG)
ERR_ADOBE_PREFERRED_LANGUAGE = ValidationError("VIPMA002", ADOBE_ERR_MSG)
ERR_ADOBE_ADDRESS = ValidationError("VIPMA003", ADOBE_ERR_MSG)
ERR_ADOBE_CONTACT = ValidationError("VIPMA004", ADOBE_ERR_MSG)
ERR_ADOBE_MEMBERSHIP_ID = ValidationError("VIPMA005", ADOBE_ERR_MSG)
ERR_ADOBE_MEMBERSHIP_ID_ITEM = ValidationError(
    "VIPMA006",
    "The provided `{title}` contains the item with SKU `{item_sku}` "
    "that is not part of the product definition.",
)

ERR_COMPANY_NAME_LENGTH = ValidationError(
    "VIPMV001",
    "The provided `{title}` length must be between "
    f"{MINLEN_COMPANY_NAME} and {MAXLEN_COMPANY_NAME} characters.",
)
ERR_COMPANY_NAME_CHARS = ValidationError(
    "VIPMV002",
    "The provided `{title}` must only contain letters, digits, spaces, "
    "commas, periods, ampersands, hyphens, apostrophes, parentheses, "
    "forward slashes, backslashes, double quotes, and underscores.",
)
ERR_PREFERRED_LANGUAGE = ValidationError(
    "VIPMV003",
    "The `{title}` must be one of the following: {languages}.",
)
ERR_ADDRESS = ValidationError(
    "VIPMV004",
    "The `{title}` contains invalid components: {errors}.",
)

ERR_COUNTRY_CODE = "The provided `Country` is not valid"
ERR_STATE_OR_PROVINCE = "The provided `State/Region` is not valid"
ERR_POSTAL_CODE_FORMAT = "The provided `ZIP/Postal code` is not valid"
ERR_POSTAL_CODE_LENGTH = (
    "The provided `ZIP/Postal code` is too long, "
    f"the maximum length is {MAXLEN_POSTAL_CODE} characters"
)
ERR_ADDRESS_LINE_1_LENGTH = (
    "The provided `Address line 1` is too long, the maximum "
    f"length is {MAXLEN_ADDRESS_LINE_1} characters"
)
ERR_ADDRESS_LINE_2_LENGTH = (
    "The provided `Address line 2` is too long, the maximum "
    f"length is {MAXLEN_ADDRESS_LINE_2} characters"
)
ERR_CITY_LENGTH = f"The provided `City` is too long, the maximum length is {MAXLEN_CITY} characters"
ERR_CONTACT = ValidationError(
    "VIPMV005",
    "The `{title}` contains invalid components: {errors}.",
)
ERR_FIRST_NAME_FORMAT = (
    "The provided `First name` must only contain letters, "
    "digits, spaces, commas, periods, ampersands, apostrophes, "
    "backslashes, and double quotes."
)
ERR_LAST_NAME_FORMAT = (
    "The provided `Last name` must only contain letters, "
    "digits, spaces, commas, periods, ampersands, apostrophes, "
    "backslashes, and double quotes."
)
ERR_EMAIL_FORMAT = "The provided `Email` is not valid"
ERR_PHONE_NUMBER_LENGTH = (
    "The provided `Phone number` is too long, "
    f"the maximum length is {MAXLEN_PHONE_NUMBER} characters"
)
