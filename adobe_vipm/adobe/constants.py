import regex as re

STATUS_PROCESSED = "1000"
STATUS_PENDING = "1002"
STATUS_INACTIVE_OR_GENERIC_FAILURE = "1004"
STATUS_ORDER_CANCELLED = "1008"
STATUS_ORDER_INACTIVE_DISTRIBUTOR = "1020"
STATUS_ORDER_INACTIVE_RESELLER = "1022"
STATUS_ORDER_INACTIVE_CUSTOMER = "1024"
STATUS_ORDER_INVALID_CUSTOMER_ID = "1026"
STATUS_INVALID_FIELDS = "1117"
STATUS_INVALID_ADDRESS = "1118"
STATUS_INVALID_MINIMUM_QUANTITY = "1135"
STATUS_ACCOUNT_ALREADY_EXISTS = "1127"
STATUS_TRANSFER_INVALID_MEMBERSHIP = "5115"
STATUS_TRANSFER_INVALID_MEMBERSHIP_OR_TRANSFER_IDS = "5116"
STATUS_TRANSFER_INELIGIBLE = "5117"
STATUS_TRANSFER_ALREADY_TRANSFERRED = "5118"
STATUS_TRANSFER_INACTIVE_RESELLER = "5119"
STATUS_TRANSFER_NO_ADMIN_CONTACTS = "5120"
STATUS_TRANSFER_IN_PROGRESS = "5121"
STATUS_TRANSFER_INACTIVE_ACCOUNT = "1010"
STATUS_INVALID_RENEWAL_STATE = "3120"


ORDER_STATUS_DESCRIPTION = {
    STATUS_INACTIVE_OR_GENERIC_FAILURE: "Inactive account, failed order or inactive subscription.",
    STATUS_ORDER_CANCELLED: "Order has been cancelled.",
    STATUS_ORDER_INACTIVE_DISTRIBUTOR: "Distributor is inactive.",
    STATUS_ORDER_INACTIVE_RESELLER: "Reseller is inactive.",
    STATUS_ORDER_INACTIVE_CUSTOMER: "Customer is inactive.",
    STATUS_ORDER_INVALID_CUSTOMER_ID: "The provided customer identifier is invalid.",
}

UNRECOVERABLE_ORDER_STATUSES = list(ORDER_STATUS_DESCRIPTION.keys())

UNRECOVERABLE_TRANSFER_STATUSES = [
    STATUS_TRANSFER_INELIGIBLE,
    STATUS_TRANSFER_ALREADY_TRANSFERRED,
    STATUS_TRANSFER_INACTIVE_RESELLER,
    STATUS_TRANSFER_NO_ADMIN_CONTACTS,
    STATUS_TRANSFER_IN_PROGRESS,
]

ORDER_TYPE_NEW = "NEW"
ORDER_TYPE_PREVIEW = "PREVIEW"
ORDER_TYPE_PREVIEW_RENEWAL = "PREVIEW_RENEWAL"
ORDER_TYPE_RENEWAL = "RENEWAL"
ORDER_TYPE_RETURN = "RETURN"


MINLEN_COMPANY_NAME = 4
MINLEN_NAME = 1
MAXLEN_POSTAL_CODE = 40
MAXLEN_CITY = 40
MAXLEN_ADDRESS_LINE_1 = 60
MAXLEN_ADDRESS_LINE_2 = 60
MAXLEN_PHONE_NUMBER = 40
MAXLEN_COMPANY_NAME = 59
MAXLEN_NAME = 35
MINQTY_LICENSES = 10
MINQTY_CONSUMABLES = 1000

REGEX_COMPANY_NAME = re.compile(r"^[\w ,.＆&・\'()（）\\\"/-]*$")
REGEX_FIRST_LAST_NAME = re.compile(r"^[\w ,.＆&'\\\"]*$")
REGEX_EMAIL = re.compile(r"^[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+$")
REGEX_SANITIZE_COMPANY_NAME = re.compile(r"[^\w ,.＆&・\'()（）\\\"/-]")
REGEX_SANITIZE_FIRST_LAST_NAME = re.compile(r"[^\p{L} 0-9,.＆&' \-\\\"]")

STATUS_3YC_ACCEPTED = "ACCEPTED"
STATUS_3YC_DECLINED = "DECLINED"
STATUS_3YC_COMMITTED = "COMMITTED"
STATUS_3YC_ACTIVE = "ACTIVE"
STATUS_3YC_REQUESTED = "REQUESTED"
STATUS_3YC_NONCOMPLIANT = "NONCOMPLIANT"
STATUS_3YC_EXPIRED = "EXPIRED"
OFFER_TYPE_LICENSE = "LICENSE"
OFFER_TYPE_CONSUMABLES = "CONSUMABLES"

CANCELLATION_WINDOW_DAYS = 14
