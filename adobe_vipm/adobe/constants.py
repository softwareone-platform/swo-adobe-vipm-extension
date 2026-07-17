import json
import os
import types
from enum import StrEnum

import regex as re


class AdobeOrderStatus(StrEnum):
    """Adobe order statuses. A transfer is an order of type TRANSFER and shares this enum."""

    COMPLETE = "1000"
    OPEN = "1002"
    FAILED = "1004"
    CANCELLED = "1008"
    FAILED_INVALID_ADDRESS = "1010"
    FAILED_INACTIVE_DISTRIBUTOR = "1020"
    FAILED_INACTIVE_RESELLER = "1022"
    FAILED_INACTIVE_CUSTOMER = "1024"
    FAILED_INVALID_CUSTOMER_ID = "1026"


class AdobeSubscriptionStatus(StrEnum):
    """Adobe subscription statuses."""

    ACTIVE = "1000"
    PENDING = "1002"
    INACTIVE = "1004"
    SCHEDULED = "1009"


class AdobeDeploymentStatus(StrEnum):
    """Adobe deployment statuses."""

    ACTIVE = "1000"
    INACTIVE = "1004"


class AdobeErrorCode(StrEnum):
    """Adobe API error response codes."""

    INVALID_CUSTOMER = "1116"
    INVALID_FIELDS = "1117"
    INVALID_ADDRESS = "1118"
    REQUEST_IS_MISSING_REQUIRED_FIELDS = "1122"
    INTERNAL_SERVER_ERROR = "1124"
    INVALID_MINIMUM_QUANTITY = "1135"
    INVALID_COUNTRY_FOR_PARTNER = "1178"
    CUSTOMER_NOT_QUALIFIED_FOR_FLEX_DISCOUNT = "2141"
    INACTIVE_SUBSCRIPTION_NOT_EDITABLE = "3119"
    INVALID_RENEWAL_STATE = "3120"
    RENEWAL_NOT_IN_WINDOW = "3122"
    LINE_ITEM_OFFER_ID_EXPIRED = "3123"
    INVALID_MEMBERSHIP_ID = "5115"
    INVALID_MEMBERSHIP_OR_TRANSFER_ID = "5116"
    INELIGIBLE_TRANSFER = "5117"
    CUSTOMER_ALREADY_TRANSFERRED = "5118"
    RESELLER_INACTIVE_FOR_TRANSFER = "5119"
    NO_ADMIN_CONTACTS_FOR_TRANSFER = "5120"
    TRANSFER_IN_PROGRESS = "5121"


class ResellerChangeAction(StrEnum):
    """Reseller change action."""

    PREVIEW = "PREVIEW"
    COMMIT = "COMMIT"


ORDER_STATUS_DESCRIPTION = types.MappingProxyType({
    AdobeOrderStatus.FAILED: "Order has failed.",
    AdobeOrderStatus.CANCELLED: "Order has been cancelled.",
    AdobeOrderStatus.FAILED_INACTIVE_DISTRIBUTOR: "Distributor is inactive.",
    AdobeOrderStatus.FAILED_INACTIVE_RESELLER: "Reseller is inactive.",
    AdobeOrderStatus.FAILED_INACTIVE_CUSTOMER: "Customer is inactive.",
    AdobeOrderStatus.FAILED_INVALID_CUSTOMER_ID: "The provided customer identifier is invalid.",
})

SUBSCRIPTION_STATUS_DESCRIPTION = types.MappingProxyType({
    AdobeSubscriptionStatus.INACTIVE: "Subscription is inactive.",
})

UNRECOVERABLE_ORDER_STATUSES = tuple(ORDER_STATUS_DESCRIPTION.keys())

ORDER_TYPE_NEW = "NEW"
ORDER_TYPE_PREVIEW = "PREVIEW"
ORDER_TYPE_PREVIEW_RENEWAL = "PREVIEW_RENEWAL"
ORDER_TYPE_PREVIEW_SWITCH = "PREVIEW_SWITCH"
ORDER_TYPE_RENEWAL = "RENEWAL"
ORDER_TYPE_RETURN = "RETURN"
ORDER_TYPE_SWITCH = "SWITCH"

MANUAL_RENEWAL_ACTION = "MANUAL_RENEWAL"


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

REGEX_COMPANY_NAME = re.compile(r"^[\w ,.＆&・\'()（）\\\"/-]*$")  # noqa: RUF001
REGEX_EMAIL = re.compile(r"^[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+$")
REGEX_FIRST_LAST_NAME = re.compile(r"^[\w ,.＆&'\\\"]*$")  # noqa: RUF001
REGEX_SANITIZE_COMPANY_NAME = re.compile(r"[^\w ,.＆&・\'()（）\\\"/-]")  # noqa: RUF001
REGEX_SANITIZE_FIRST_LAST_NAME = re.compile(r"[^\p{L} 0-9,.＆&' \-\\\"]")  # noqa: RUF001


class ThreeYearCommitmentStatus(StrEnum):
    """Three year commitments statuses."""

    ACCEPTED = "ACCEPTED"
    DECLINED = "DECLINED"
    COMMITTED = "COMMITTED"
    ACTIVE = "ACTIVE"
    REQUESTED = "REQUESTED"
    NONCOMPLIANT = "NONCOMPLIANT"
    EXPIRED = "EXPIRED"


THREE_YC_TEMP_3YC_STATUSES = (
    ThreeYearCommitmentStatus.REQUESTED,
    ThreeYearCommitmentStatus.ACCEPTED,
)


class OfferType(StrEnum):
    """Offer type for customer."""

    LICENSE = "LICENSE"
    CONSUMABLES = "CONSUMABLES"


CANCELLATION_WINDOW_DAYS = 14

MPT_NOTIFY_CATEGORIES = json.loads(
    os.getenv("MPT_NOTIFY_CATEGORIES", '{"ORDERS": "NTC-0000-0006"}')
)
