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
ORDER_TYPE_CONFIGURATION = "Configuration"

PARAM_ADDRESS = "address"
PARAM_ADOBE_SKU = "adobeSKU"
PARAM_COMPANY_NAME = "companyName"
PARAM_CONTACT = "contact"
PARAM_CUSTOMER_ID = "customerId"
PARAM_MEMBERSHIP_ID = "membershipId"
PARAM_NEXT_SYNC_DATE = "nextSync"
PARAM_COTERM_DATE = "cotermDate"
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
PARAM_CURRENT_QUANTITY = "currentQuantity"
PARAM_RENEWAL_QUANTITY = "renewalQuantity"
PARAM_RENEWAL_DATE = "renewalDate"
PARAM_DUE_DATE = "dueDate"
PARAM_RETRY_COUNT = "retryCount"
PARAM_GLOBAL_CUSTOMER = "globalCustomer"
PARAM_DEPLOYMENTS = "deployments"
PARAM_DEPLOYMENT_ID = "deploymentId"
PARAM_LAST_SYNC_DATE = "lastSyncDate"

STATUS_MARKET_SEGMENT_ELIGIBLE = "eligible"
STATUS_MARKET_SEGMENT_NOT_ELIGIBLE = "not-eligible"
STATUS_MARKET_SEGMENT_PENDING = "pending"

REQUIRED_CUSTOMER_ORDER_PARAMS = (
    PARAM_COMPANY_NAME,
    PARAM_ADDRESS,
    PARAM_CONTACT,
)
OPTIONAL_CUSTOMER_ORDER_PARAMS = (PARAM_3YC, PARAM_3YC_CONSUMABLES, PARAM_3YC_LICENSES)
NEW_CUSTOMER_PARAMETERS = REQUIRED_CUSTOMER_ORDER_PARAMS + OPTIONAL_CUSTOMER_ORDER_PARAMS

PARAM_PHASE_ORDERING = "ordering"
PARAM_PHASE_FULFILLMENT = "fulfillment"

CANCELLATION_WINDOW_DAYS = 14
GLOBAL_SUFFIX = "_global"
LAST_TWO_WEEKS_DAYS = 13

ADOBE_ERR_MSG = "The `{title}` is not valid: {details}."

ERR_ADOBE_COMPANY_NAME = ValidationError("VIPM0001", ADOBE_ERR_MSG)
ERR_ADOBE_ADDRESS = ValidationError("VIPM0003", ADOBE_ERR_MSG)
ERR_ADOBE_CONTACT = ValidationError("VIPM0004", ADOBE_ERR_MSG)
ERR_ADOBE_MEMBERSHIP_ID = ValidationError("VIPM0005", ADOBE_ERR_MSG)
ERR_ADOBE_MEMBERSHIP_ID_ITEM = ValidationError(
    "VIPM0006",
    "The provided `{title}` contains the item with SKU `{item_sku}` "
    "that is not part of the product definition.",
)
ERR_ADOBE_MEMBERSHIP_ID_INACTIVE_ACCOUNT = ValidationError(
    "VIPM0007",
    "Customer account is inactive or blocked. Adobe status code is `{status}`.",
)

ERR_COMPANY_NAME_LENGTH = ValidationError(
    "VIPM0008",
    "The provided `{title}` length must be between "
    f"{MINLEN_COMPANY_NAME} and {MAXLEN_COMPANY_NAME} characters.",
)
ERR_COMPANY_NAME_CHARS = ValidationError(
    "VIPM0009",
    "The provided `{title}` must only contain letters, digits, spaces, "
    "commas, periods, ampersands, hyphens, apostrophes, parentheses, "
    "forward slashes, backslashes, double quotes, and underscores.",
)
ERR_ADDRESS = ValidationError(
    "VIPM0010",
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
ERR_CITY_LENGTH = f"The provided `City` is too long, the maximum length is {MAXLEN_CITY} characters"
ERR_CONTACT = ValidationError(
    "VIPM0011",
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
    "VIPM0012",
    "Order can't be processed. Failure reason: {error}.",
)

ERR_3YC_QUANTITY_LICENSES = ValidationError(
    "VIPM0013",
    f"The minimum number of licenses must be numeric "
    f"and greater than or equal to ten ({MINQTY_LICENSES}).",
)

ERR_3YC_QUANTITY_CONSUMABLES = ValidationError(
    "VIPM0014",
    f"The minimum number of consumables must be numeric "
    f"and greater than or equal to one thousand ({MINQTY_CONSUMABLES}).",
)

ERR_3YC_NO_MINIMUMS = ValidationError(
    "VIPM0015",
    "To request 3-year commitment benefits you must fill at least one parameter between "
    "`{title_min_licenses}` and `{title_min_consumables}`.",
)
ERR_DUPLICATED_ITEMS = ValidationError(
    "VIPM0016",
    "The order cannot contain multiple lines for the same item: {duplicates}.",
)
ERR_EXISTING_ITEMS = ValidationError(
    "VIPM0017", "The order cannot contain new lines for an existing item: {duplicates}."
)

ERR_ADOBE_ERROR = ValidationError("VIPM0011", "Adobe returned an error: {details}.")
ERR_ADOBE_MEMBERSHIP_ID_EMPTY = ValidationError(
    "VIPM0018", "No active items have been found for this membership."
)

ERR_ADOBE_MEMBERSHIP_PROCESSING = ValidationError(
    "VIPM0032", "Error processing the membership {membership_id}: {error}"
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
TEMPLATE_NAME_DELAYED = "Delayed"
TEMPLATE_NAME_TERMINATION = "Termination"
TEMPLATE_CONFIGURATION_AUTORENEWAL_ENABLE = "EnableAutoRenewal"
TEMPLATE_CONFIGURATION_AUTORENEWAL_DISABLE = "DisableAutoRenewal"

MARKET_SEGMENT_COMMERCIAL = "COM"
MARKET_SEGMENT_EDUCATION = "EDU"
MARKET_SEGMENT_GOVERNMENT = "GOV"

FAKE_CUSTOMERS_IDS = {
    MARKET_SEGMENT_COMMERCIAL: "1234567890",
    MARKET_SEGMENT_GOVERNMENT: "1234567890GOV",
    MARKET_SEGMENT_EDUCATION: "1234567890EDU",
}

ERR_INVALID_DOWNSIZE_QUANTITY = ValidationError(
    "VIPM0019", "Could not find suitable returnable orders for all items.\n{messages}"
)

ERR_INVALID_ITEM_DOWNSIZE_QUANTITY_ANY_COMBINATION = " or any combination of these values,"

ERR_INVALID_ITEM_DOWNSIZE_QUANTITY = (
    "Cannot reduce item `{item}` quantity by {delta}. "
    "Please reduce the quantity by {available_quantities},{any_combination} or wait until {date} "
    "when there are no returnable orders to modify your renewal quantity."
)

ERR_INVALID_TERMINATION_ORDER_QUANTITY = ValidationError(
    "VIPM0033",
    "Cannot return the entire quantity of all subscriptions in this order. "
    "Consider disabling auto-renewal for these subscriptions "
    "instead using a Configuration Order.",
)

ERR_INVALID_ITEM_DOWNSIZE_FIRST_PO = (
    "Cannot reduce item `{item}` quantity by {delta} and there "
    "is only one returnable order which would reduce the quantity to zero. "
    "Consider placing a Termination order for this subscription instead and "
    "place a new order for {quantity} licenses."
)

ERR_DOWNSIZE_MINIMUM_3YC_LICENSES = (
    "The order has failed. The reduction in quantity would place the account"
    " below the minimum commitment of {minimum_licenses} licenses for the three-year commitment."
)


ERR_DOWNSIZE_MINIMUM_3YC_CONSUMABLES = (
    "The order has failed. The reduction in quantity would place the account below the minimum"
    " commitment of {minimum_consumables} consumables for the three-year commitment."
)


ERR_DOWNSIZE_MINIMUM_3YC_GENERIC = (
    "The order has failed. The reduction in quantity would place the account below the "
    "minimum commitment of {minimum_licenses} licenses or {minimum_consumables} consumables"
    " for the three-year commitment."
)

ERR_DOWNSIZE_MINIMUM_3YC_VALIDATION = ValidationError(
    "VIPM0020",
    "{error}",
)

ERR_COMMITMENT_3YC_LICENSES = (
    "The quantity selected of {selected_licenses} would place the account below the "
    "minimum commitment of {minimum_licenses} licenses for the three-year commitment."
)

ERR_COMMITMENT_3YC_CONSUMABLES = (
    "The quantity selected of {selected_consumables} would place the account below the "
    "minimum commitment of {minimum_consumables} consumables for the three-year commitment."
)

ERR_COMMITMENT_3YC_VALIDATION = ValidationError(
    "VIPM0034",
    "{error}",
)

ERR_COMMITMENT_3YC_EXPIRED_REJECTED_NO_COMPLIANT = ValidationError(
    "VIPM0035",
    "The 3-year commitment is in status {status}. Please contact support to renew the commitment.",
)

ERR_UPDATING_TRANSFER_ITEMS = ValidationError(
    "VIPM0021",
    "Do not add or remove items, and do not modify the quantities of any items. "
    "You may make these changes using a Change order once this order completes.",
)

ERR_NO_RETURABLE_ERRORS_FOUND = ValidationError(
    "VIPM0022",
    "No Adobe orders that match the desired quantity delta have been found for the "
    "following SKUs: {non_returnable_skus}.",
)

ERR_INVALID_RENEWAL_STATE = ValidationError(
    "VIPM0023", "Can't update renewal quantity. Adobe API error: {error}."
)

ERR_MARKET_SEGMENT_NOT_ELIGIBLE = ValidationError(
    "VIPM0024", "The agreement is not eligible for market segment {segment}."
)

ERR_DUE_DATE_REACHED = ValidationError(
    "VIPM0025",
    "Due date {due_date} for order processing is reached.",
)

ERR_COTERM_DATE_IN_LAST_24_HOURS = ValidationError(
    "VIPM0034",
    "Orders cannot be placed within 24 hours of the renewal date. "
    "Please wait until after the renewal date and make your required "
    "changes with Change, Configuration, or Termination Orders.",
)

ERR_UNRECOVERABLE_ADOBE_ORDER_STATUS = ValidationError(
    "VIPM0026",
    "Unrecoverable Adobe Order status: {description}",
)

ERR_UNEXPECTED_ADOBE_ERROR_STATUS = ValidationError(
    "VIPM0027",
    "Unexpected status ({status}) received from Adobe.",
)

ERR_ADOBE_TRANSFER_PREVIEW = ValidationError(
    "VIPM0028",
    "Adobe API transfer validation error. {error}.",
)

ERR_MEMBERSHIP_ITEMS_DONT_MATCH = ValidationError(
    "VIPM0029",
    "The items owned by the given membership don't match the order (sku or quantity): {lines}.",
)

ERR_MEMBERSHIP_HAS_BEEN_TRANSFERED = ValidationError(
    "VIPM0030",
    "Membership has already been migrated.",
)

ERR_ADOBE_SUBSCRIPTION_UPDATE_ERROR = ValidationError("VIPM0031", "{error}")

ERR_NO_SUBSCRIPTIONS_WITHOUT_DEPLOYMENT = (
    "No subscriptions found without deployment ID to be added to the main agreement",
)
