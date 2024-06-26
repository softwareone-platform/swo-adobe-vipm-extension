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
)
from adobe_vipm.flows.errors import ValidationError

ORDER_TYPE_PURCHASE = "Purchase"
ORDER_TYPE_CHANGE = "Change"
ORDER_TYPE_TERMINATION = "Termination"

PARAM_ADDRESS = "address"
PARAM_ADOBE_SKU = "adobeSKU"
PARAM_COMPANY_NAME = "companyName"
PARAM_CONTACT = "contact"
PARAM_CUSTOMER_ID = "customerId"
PARAM_MEMBERSHIP_ID = "membershipId"
PARAM_NEXT_SYNC_DATE = "nextSync"
PARAM_RETRY_COUNT = "retryCount"
PARAM_AGREEMENT_TYPE = "agreementType"
PARAM_3YC = "3YC"
PARAM_3YC_RECOMMITMENT = "3YCRecommitment"
PARAM_3YC_LICENSES = "3YCLicenses"
PARAM_3YC_CONSUMABLES = "3YCConsumables"
PARAM_3YC_ENROLL_STATUS = "3YCEnrollStatus"
PARAM_3YC_COMMITMENT_REQUEST_STATUS = "3YCCommitmentRequestStatus"
PARAM_3YC_RECOMMITMENT_REQUEST_STATUS = "3YCRecommitmentRequestStatus"
PARAM_3YC_START_DATE = "3YCStartDate"
PARAM_3YC_END_DATE = "3YCEndDate"
PARAM_MARKET_SEGMENT_ELIGIBILITY_STATUS = "marketSegmentEligibilityStatus"

STATUS_MARKET_SEGMENT_ELIGIBLE = "eligible"
STATUS_MARKET_SEGMENT_NOT_ELIGIBLE = "not-eligible"
STATUS_MARKET_SEGMENT_PENDING = "pending"

REQUIRED_CUSTOMER_ORDER_PARAMS = (
    PARAM_COMPANY_NAME,
    PARAM_ADDRESS,
    PARAM_CONTACT,
)
OPTIONAL_CUSTOMER_ORDER_PARAMS = (PARAM_3YC, PARAM_3YC_CONSUMABLES, PARAM_3YC_LICENSES)
NEW_CUSTOMER_PARAMETERS = (
    REQUIRED_CUSTOMER_ORDER_PARAMS + OPTIONAL_CUSTOMER_ORDER_PARAMS
)

PARAM_PHASE_ORDERING = "ordering"
PARAM_PHASE_FULFILLMENT = "fulfillment"

CANCELLATION_WINDOW_DAYS = 14

ADOBE_ERR_MSG = "The `{title}` is not valid: {details}."

ERR_ADOBE_COMPANY_NAME = ValidationError("VIPMA001", ADOBE_ERR_MSG)
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
ERR_ADDRESS = ValidationError(
    "VIPMV004",
    "The `{title}` contains invalid components: {errors}.",
)

ERR_COUNTRY_CODE = "The provided `Country` is not valid"
ERR_STATE_OR_PROVINCE = "The provided `State/Region` is not valid"
ERR_STATE_DID_YOU_MEAN = " (Did you mean {suggestion} ?)"
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
ERR_CITY_LENGTH = (
    f"The provided `City` is too long, the maximum length is {MAXLEN_CITY} characters"
)
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

ERR_VIPM_UNHANDLED_EXCEPTION = ValidationError(
    "VIPM001",
    "Order can't be processed. Failure reason: {error}",
)

ERR_3YC_QUANTITY_LICENSES = ValidationError(
    "VIPMV006",
    "The `{title}` must be an integer "
    f"number equal to {MINQTY_LICENSES} or greater.",
)

ERR_3YC_QUANTITY_CONSUMABLES = ValidationError(
    "VIPMV007",
    "The `{title}` must be an integer "
    f"number equal to {MINQTY_CONSUMABLES} or greater.",
)

ERR_3YC_NO_MINIMUMS = ValidationError(
    "VIPMV008",
    "To request 3-year commitment benefits you must fill at least one parameter between "
    "`{title_min_licenses}` and `{title_min_consumables}`.",
)
ERR_DUPLICATED_ITEMS = ValidationError(
    "VIPMV009",
    "The order cannot contain multiple lines for the same item: {duplicates}.",
)
ERR_EXISTING_ITEMS = ValidationError(
    "VIPMV010", "The order cannot contain new lines for an existing item: {duplicates}."
)
ERR_ADOBE_ERROR = ValidationError("VIPMV011", "Adobe returned an error: {details}.")
ERR_ADOBE_MEMBERSHIP_ID_EMPTY = ValidationError(
    "VIPMV012", "No active items have been found for this membership."
)

ERR_ADOBE_MEMBERSHIP_NOT_FOUND = "Membership not found"
ERR_ADOBE_UNEXPECTED_ERROR = "Adobe returned an unexpected error"


MPT_ORDER_STATUS_PROCESSING = "Processing"
MPT_ORDER_STATUS_QUERYING = "Querying"
MPT_ORDER_STATUS_COMPLETED = "Completed"

TEMPLATE_NAME_TRANSFER = "Transfer"
TEMPLATE_NAME_BULK_MIGRATE = "BulkMigrate"
TEMPLATE_NAME_PURCHASE = "Purchase"
TEMPLATE_NAME_CHANGE = "Change"
TEMPLATE_NAME_TERMINATION = "Termination"

MARKET_SEGMENT_COMMERCIAL = "COM"
MARKET_SEGMENT_EDUCATION = "EDU"
MARKET_SEGMENT_GOVERNMENT = "GOV"

FAKE_CUSTOMERS_IDS = {
    MARKET_SEGMENT_COMMERCIAL: "1234567890",
    MARKET_SEGMENT_GOVERNMENT: "1234567890GOV",
    MARKET_SEGMENT_EDUCATION: "1234567890EDU",
}
