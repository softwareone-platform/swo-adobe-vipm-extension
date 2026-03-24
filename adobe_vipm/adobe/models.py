from typing import Any, Self

from pydantic import BaseModel, ConfigDict, Field


class BaseSchema(BaseModel):
    """Base Adobe schema with dict-like compatibility helpers."""

    model_config = ConfigDict(extra="allow", from_attributes=True, validate_by_name=True)

    def to_dict(self) -> dict[str, Any]:
        """Dump the model using Adobe API field names."""
        return self.model_dump(by_alias=True, exclude_none=True)

    @classmethod
    def from_payload(cls, payload: Any) -> Self:
        """Build a schema from an Adobe API payload."""
        return cls.model_validate(payload)


class AdobeLink(BaseSchema):
    """Adobe hypermedia link."""

    headers: list[dict[str, Any]] = Field(default_factory=list)
    method: str
    uri: str


class AdobeLinks(BaseSchema):
    """Adobe links container."""

    next_link: AdobeLink | None = Field(default=None, alias="next")
    prev_link: AdobeLink | None = Field(default=None, alias="prev")
    self_link: AdobeLink = Field(alias="self")


class AdobeContact(BaseSchema):
    """Adobe customer contact."""

    email: str
    first_name: str = Field(alias="firstName")
    last_name: str = Field(alias="lastName")
    phone_number: str | None = Field(default=None, alias="phoneNumber")


class AdobeAddress(BaseSchema):
    """Adobe customer address."""

    address_line_1: str = Field(alias="addressLine1")
    address_line_2: str | None = Field(default=None, alias="addressLine2")
    city: str
    country: str
    phone_number: str | None = Field(default=None, alias="phoneNumber")
    postal_code: str = Field(alias="postalCode")
    region: str


class AdobeCompanyProfile(BaseSchema):
    """Adobe company profile."""

    company_name: str = Field(alias="companyName")
    market_segment: str = Field(alias="marketSegment")
    market_sub_segments: list[str] = Field(default_factory=list, alias="marketSubSegments")
    preferred_language: str = Field(alias="preferredLanguage")

    address: AdobeAddress
    contacts: list[AdobeContact] = Field(default_factory=list)


class CustomerDiscount(BaseSchema):
    """Adobe customer discount."""

    offer_type: str = Field(alias="offerType")
    level: str


class AdobeLinkedMembership(BaseSchema):
    """Adobe linked membership."""

    id: str
    benefit_types: list[str] = Field(default_factory=list, alias="benefitTypes")
    creation_date: str = Field(alias="creationDate")
    country: str | None = None
    linked_membership_type: str = Field(alias="linkedMembershipType")
    name: str
    type: str


class AdobeCustomer(BaseSchema):
    """Adobe customer account."""

    benefits: list[dict[str, Any]] = Field(default_factory=list)
    coterm_date: str | None = Field(default=None, alias="cotermDate")
    creation_date: str = Field(alias="creationDate")
    customer_id: str = Field(alias="customerId")
    external_reference_id: str = Field(alias="externalReferenceId")
    global_sales_enabled: bool = Field(alias="globalSalesEnabled")
    reseller_id: str = Field(alias="resellerId")
    status: str

    company_profile: AdobeCompanyProfile = Field(alias="companyProfile")
    discounts: list[CustomerDiscount] = Field(default_factory=list)
    linked_membership: AdobeLinkedMembership | None = Field(
        default=None,
        alias="linkedMembership",
    )
    links: AdobeLinks


class AdobeOrderPromotion(BaseSchema):
    """Adobe order promotion entry."""

    code: str
    result: str


class AdobeOrderLineItemPricing(BaseSchema):
    """Adobe pricing details for an order line item."""

    discounted_partner_price: float = Field(alias="discountedPartnerPrice")
    line_item_partner_price: float = Field(alias="lineItemPartnerPrice")
    net_partner_price: float = Field(alias="netPartnerPrice")
    partner_price: float = Field(alias="partnerPrice")


class AdobeOrderLineItem(BaseSchema):
    """Adobe order line item."""

    currency_code: str = Field(alias="currencyCode")
    ext_line_item_number: int = Field(alias="extLineItemNumber")
    deployment_id: str | None = Field(default=None, alias="deploymentId")
    offer_id: str = Field(alias="offerId")
    prorated_days: int | None = Field(default=None, alias="proratedDays")
    quantity: int
    status: str
    subscription_id: str | None = Field(default=None, alias="subscriptionId")

    pricing: AdobeOrderLineItemPricing | None = None
    promotions: list[AdobeOrderPromotion] = Field(default_factory=list)


class AdobeOrderPricingSummary(BaseSchema):
    """Adobe aggregated pricing for an order."""

    currency_code: str = Field(alias="currencyCode")
    total_line_item_partner_price: float = Field(alias="totalLineItemPartnerPrice")


class AdobeOrder(BaseSchema):
    """Adobe order resource."""

    creation_date: str = Field(alias="creationDate")
    customer_id: str = Field(alias="customerId")
    currency_code: str = Field(alias="currencyCode")
    external_reference_id: str = Field(alias="externalReferenceId")
    order_id: str = Field(alias="orderId")
    order_type: str = Field(alias="orderType")
    reference_order_id: str | None = Field(default=None, alias="referenceOrderId")
    referenced_order_id: str | None = Field(default=None, alias="referencedOrderId")
    source: str | None = None
    status: str

    line_items: list[AdobeOrderLineItem] = Field(default_factory=list, alias="lineItems")
    links: AdobeLinks | None = None
    pricing_summary: list[AdobeOrderPricingSummary] = Field(
        default_factory=list, alias="pricingSummary"
    )


class AdobeOrderCollection(BaseSchema):
    """Adobe paginated order response."""

    count: int | None = None
    limit: int | None = None
    offset: int | None = None
    total_count: int = Field(alias="totalCount")

    items: list[AdobeOrder] = Field(default_factory=list)
    links: AdobeLinks | None = None


class AdobeSubscriptionAutoRenewal(BaseSchema):
    """Adobe subscription auto-renewal settings."""

    enabled: bool
    flex_discount_codes: list[str] = Field(default_factory=list, alias="flexDiscountCodes")
    renewal_code: str | None = Field(default=None, alias="renewalCode")
    renewal_quantity: int = Field(alias="renewalQuantity")


class AdobeSubscription(BaseSchema):
    """Adobe subscription resource."""

    allowed_actions: list[str] = Field(default_factory=list, alias="allowedActions")
    creation_date: str = Field(alias="creationDate")
    current_quantity: int = Field(alias="currentQuantity")
    currency_code: str = Field(alias="currencyCode")
    deployment_id: str | None = Field(default=None, alias="deploymentId")
    offer_id: str = Field(alias="offerId")
    renewal_date: str = Field(alias="renewalDate")
    subscription_id: str = Field(alias="subscriptionId")
    used_quantity: int = Field(alias="usedQuantity")
    status: str

    auto_renewal: AdobeSubscriptionAutoRenewal = Field(alias="autoRenewal")
    links: AdobeLinks


class AdobeSubscriptionCollection(BaseSchema):
    """Adobe paginated subscription response."""

    items: list[AdobeSubscription] = Field(default_factory=list)
    links: AdobeLinks | None = None
    total_count: int = Field(alias="totalCount")


class AdobePriceListOffer(BaseSchema):
    """Adobe offer entry inside a price list."""

    additional_detail: str | None = Field(default=None, alias="additionalDetail")
    discount_code: str | None = Field(default=None, alias="discountCode")
    duration: str | None = None
    estimated_street_price: str | None = Field(default=None, alias="estimatedStreetPrice")
    first_order_date: str | None = Field(default=None, alias="firstOrderDate")
    language: str | None = None
    last_order_date: str | None = Field(default=None, alias="lastOrderDate")
    level_details: str | None = Field(default=None, alias="levelDetails")
    offer_id: str = Field(alias="offerId")
    operating_system: str | None = Field(default=None, alias="operatingSystem")
    partner_price: str | None = Field(default=None, alias="partnerPrice")
    pool: str | None = None
    product_family: str = Field(alias="productFamily")
    product_type: str | None = Field(default=None, alias="productType")
    product_type_detail: str | None = Field(default=None, alias="productTypeDetail")
    users: str | None = None
    version: str | None = None


class AdobePriceList(BaseSchema):
    """Adobe price list response."""

    currency: str
    count: int
    limit: int
    market_segment: str = Field(alias="marketSegment")
    offset: int
    price_list_month: str = Field(alias="priceListMonth")
    price_list_type: str = Field(alias="priceListType")
    region: str
    total_count: int = Field(alias="totalCount")

    offers: list[AdobePriceListOffer] = Field(default_factory=list)
