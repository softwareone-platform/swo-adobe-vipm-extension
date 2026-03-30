from typing import Any, Self

from pydantic import BaseModel, ConfigDict, Field

from adobe_vipm.adobe.constants import UNRECOVERABLE_ORDER_STATUSES, AdobeStatus
from adobe_vipm.adobe.utils import find_first


class AdobeBaseSchema(BaseModel):
    """Base Adobe schema with dict-like compatibility helpers."""

    model_config = ConfigDict(extra="allow", from_attributes=True, validate_by_name=True)

    def to_dict(self) -> dict[str, Any]:
        """Dump the model using Adobe API field names."""
        return self.model_dump(by_alias=True, exclude_none=True)

    @classmethod
    def from_payload(cls, payload: Any) -> Self:
        """Build a schema from an Adobe API payload."""
        return cls.model_validate(payload)


class AdobeLink(AdobeBaseSchema):
    """Adobe hypermedia link."""

    headers: list[dict[str, Any]] = Field(default_factory=list)
    method: str
    uri: str


class AdobeLinks(AdobeBaseSchema):
    """Adobe links container."""

    next_link: AdobeLink = Field(default=AdobeLink, alias="next")
    prev_link: AdobeLink = Field(default=AdobeLink, alias="prev")
    self_link: AdobeLink = Field(alias="self")


class AdobeContact(AdobeBaseSchema):
    """Adobe customer contact."""

    email: str
    first_name: str = Field(alias="firstName")
    last_name: str = Field(alias="lastName")
    phone_number: str | None = Field(default=None, alias="phoneNumber")


class AdobeAddress(AdobeBaseSchema):
    """Adobe customer address."""

    address_line_1: str = Field(alias="addressLine1")
    address_line_2: str | None = Field(default=None, alias="addressLine2")
    city: str
    country: str
    phone_number: str | None = Field(default=None, alias="phoneNumber")
    postal_code: str = Field(alias="postalCode")
    region: str


class AdobeCompanyProfile(AdobeBaseSchema):
    """Adobe company profile."""

    company_name: str = Field(alias="companyName")
    market_segment: str = Field(alias="marketSegment")
    market_sub_segments: list[str] = Field(default_factory=list, alias="marketSubSegments")
    preferred_language: str = Field(alias="preferredLanguage")

    address: AdobeAddress
    contacts: list[AdobeContact] = Field(default_factory=list)


class CustomerDiscount(AdobeBaseSchema):
    """Adobe customer discount."""

    offer_type: str = Field(alias="offerType")
    level: str


class AdobeLinkedMembership(AdobeBaseSchema):
    """Adobe linked membership."""

    id: str
    benefit_types: list[str] = Field(default_factory=list, alias="benefitTypes")
    creation_date: str = Field(alias="creationDate")
    country: str | None = None
    linked_membership_type: str = Field(alias="linkedMembershipType")
    name: str
    type: str


class AdobeCustomer(AdobeBaseSchema):
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
    linked_membership: AdobeLinkedMembership = Field(
        default=AdobeLinkedMembership, alias="linkedMembership"
    )
    links: AdobeLinks

    @property
    def three_yc_commitment(self) -> dict[str, Any]:
        """Three year commitment object from the customer object."""
        benefit_three_yc = find_first(
            lambda benefit: benefit["type"] == "THREE_YEAR_COMMIT",
            self.benefits,
            {},
        )
        return benefit_three_yc.get("commitmentRequest", {}) or {}

    def get_three_yc_commitment_request(self, *, is_recommitment=False) -> dict[str, Any]:
        """
        Extract the commitment or recommitment request object from the customer object.

        Args:
            is_recommitment (bool): If True it search for a recommitment request.
            Default to False.

        Returns:
            dict: The commitment or recommitment request object if
            it exists or an empty object.
        """
        recommitment_or_commitment = (
            "recommitmentRequest" if is_recommitment else "commitmentRequest"
        )
        benefit_three_yc = find_first(
            lambda benefit: benefit["type"] == "THREE_YEAR_COMMIT",
            self.benefits,
            {},
        )

        return benefit_three_yc.get(recommitment_or_commitment, {})


class AdobeOrderPromotion(AdobeBaseSchema):
    """Adobe order promotion entry."""

    code: str
    result: str


class AdobeOrderLineItemPricing(AdobeBaseSchema):
    """Adobe pricing details for an order line item."""

    discounted_partner_price: float = Field(alias="discountedPartnerPrice")
    line_item_partner_price: float = Field(alias="lineItemPartnerPrice")
    net_partner_price: float = Field(alias="netPartnerPrice")
    partner_price: float = Field(alias="partnerPrice")


class FlexDiscount(AdobeBaseSchema):
    """Adobe flexible discount."""

    id: str
    code: str
    result: str


class AdobeOrderLineItem(AdobeBaseSchema):
    """Adobe order line item."""

    currency_code: str = Field(alias="currencyCode")
    deployment_id: str | None = Field(default=None, alias="deploymentId")
    ext_line_item_number: int = Field(alias="extLineItemNumber")
    offer_id: str = Field(alias="offerId")
    prorated_days: int | None = Field(default=None, alias="proratedDays")
    quantity: int
    status: str
    subscription_id: str | None = Field(default=None, alias="subscriptionId")

    flex_discounts: list[FlexDiscount] = Field(default_factory=list, alias="flexDiscounts")
    pricing: AdobeOrderLineItemPricing | None = None
    promotions: list[AdobeOrderPromotion] = Field(default_factory=list)

    @property
    def partial_sku(self):
        """Return the partial SKU."""
        return self.offer_id[:10]


class AdobeOrderPricingSummary(AdobeBaseSchema):
    """Adobe aggregated pricing for an order."""

    currency_code: str = Field(alias="currencyCode")
    total_line_item_partner_price: float = Field(alias="totalLineItemPartnerPrice")


class AdobeOrder(AdobeBaseSchema):
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

    @property
    def flex_discounts(self) -> list[dict[str, Any]]:
        """Flexible discounts."""
        return [
            {
                "extLineItemNumber": line.ext_line_item_number,
                "offerId": line.offer_id,
                "subscriptionId": line.subscription_id,
                "flexDiscountCode": [discount.code for discount in line.flex_discounts],
            }
            for line in self.line_items
            if line.flex_discounts
        ]

    # REFACTOR: change order_id to id
    @property
    def id(self) -> str:
        """Order ID."""
        return self.order_id

    @property
    def is_pending(self) -> bool:
        """Return True if the order is pending."""
        return self.status == AdobeStatus.PENDING

    @property
    def is_processed(self) -> bool:
        """Return True if the order is processed."""
        return self.status == AdobeStatus.PROCESSED

    @property
    def is_unrecoverable(self) -> bool:
        """Return True if the order is in an unrecoverable state."""
        return self.status in UNRECOVERABLE_ORDER_STATUSES


class AdobeOrderCollection(AdobeBaseSchema):
    """Adobe paginated order response."""

    count: int | None = None
    limit: int | None = None
    offset: int | None = None
    total_count: int = Field(alias="totalCount")

    items: list[AdobeOrder] = Field(default_factory=list)
    links: AdobeLinks | None = None


class AdobePreviewOrderPricing(AdobeBaseSchema):
    """Pricing details returned for a preview order line item."""

    partner_price: float | None = Field(default=None, alias="partnerPrice")
    discounted_partner_price: float | None = Field(default=None, alias="discountedPartnerPrice")
    net_partner_price: float | None = Field(default=None, alias="netPartnerPrice")
    line_item_partner_price: float | None = Field(default=None, alias="lineItemPartnerPrice")


class AdobePreviewOrderFlexDiscount(AdobeBaseSchema):
    """Flexible discount result returned for a preview order line item."""

    id: str
    code: str
    result: str


class AdobePreviewOrderLineItem(AdobeBaseSchema):
    """Line item returned in an Adobe preview order response."""

    ext_line_item_number: int = Field(alias="extLineItemNumber")
    offer_id: str = Field(alias="offerId")
    quantity: int
    subscription_id: str | None = Field(default=None, alias="subscriptionId")
    status: str | None = None
    currency_code: str | None = Field(default=None, alias="currencyCode")
    deployment_id: str | None = Field(default=None, alias="deploymentId")
    flex_discounts: list[AdobePreviewOrderFlexDiscount] = Field(
        default_factory=list, alias="flexDiscounts"
    )
    prorated_days: int | None = Field(default=None, alias="proratedDays")
    pricing: AdobePreviewOrderPricing | None = None


class AdobePreviewOrderPricingSummary(AdobeBaseSchema):
    """Pricing summary returned by Adobe preview order response."""

    total_line_item_partner_price: float = Field(alias="totalLineItemPartnerPrice")
    currency_code: str = Field(alias="currencyCode")


class AdobePreviewOrder(AdobeBaseSchema):
    """Adobe preview order response model."""

    reference_order_id: str | None = Field(default=None, alias="referenceOrderId")
    external_reference_id: str = Field(alias="externalReferenceId")
    order_id: str | None = Field(default=None, alias="orderId")
    customer_id: str | None = Field(default=None, alias="customerId")
    currency_code: str | None = Field(default=None, alias="currencyCode")
    order_type: str = Field(alias="orderType")
    creation_date: str | None = Field(default=None, alias="creationDate")
    status: str | None = None
    line_items: list[AdobePreviewOrderLineItem] = Field(alias="lineItems")
    pricing_summary: list[AdobePreviewOrderPricingSummary] = Field(
        default_factory=list, alias="pricingSummary"
    )

    @property
    def prices(self) -> dict[str, float | None]:
        """Prices."""
        return {line.offer_id: line.pricing.discounted_partner_price for line in self.line_items}

    @property
    def skus(self) -> list[str]:
        """SKUs."""
        return [line.offer_id for line in self.line_items]


class AdobeSubscriptionAutoRenewal(AdobeBaseSchema):
    """Adobe subscription auto-renewal settings."""

    enabled: bool
    flex_discount_codes: list[str] = Field(default_factory=list, alias="flexDiscountCodes")
    renewal_code: str | None = Field(default=None, alias="renewalCode")
    renewal_quantity: int = Field(alias="renewalQuantity")


class AdobeSubscription(AdobeBaseSchema):
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

    # REFACTOR: change subscription_id to id
    @property
    def id(self) -> str:
        """Subscription ID."""
        return self.subscription_id

    @property
    def is_processed(self) -> bool:
        """Status if processed."""
        return self.status == AdobeStatus.PROCESSED


class AdobeSubscriptionCollection(AdobeBaseSchema):
    """Adobe paginated subscription response."""

    items: list[AdobeSubscription] = Field(default_factory=list)
    links: AdobeLinks | None = None
    total_count: int = Field(alias="totalCount")


class AdobePriceListOffer(AdobeBaseSchema):
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


class AdobePriceList(AdobeBaseSchema):
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
