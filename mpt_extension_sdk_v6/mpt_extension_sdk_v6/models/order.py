from typing import Any, Self

from pydantic import AliasChoices, Field

from mpt_extension_sdk_v6.api.schemas.base import BaseSchema
from mpt_extension_sdk_v6.models.account import SellerAccount
from mpt_extension_sdk_v6.models.agreement import Agreement
from mpt_extension_sdk_v6.models.authorization import Authorization
from mpt_extension_sdk_v6.models.external_id import ExternalIds
from mpt_extension_sdk_v6.models.parameter import ParameterBag
from mpt_extension_sdk_v6.models.product import Product, ProductItem
from mpt_extension_sdk_v6.models.subscription import Subscription
from mpt_extension_sdk_v6.models.template import Template


class OrderLine(BaseSchema):
    """Order line."""

    id: str
    description: str | None = None
    old_quantity: int = Field(
        default=0,
        alias="oldQuantity",
        validation_alias=AliasChoices("oldQuantity", "old_quantity"),
    )
    quantity: int

    item: ProductItem


class Order(BaseSchema):
    """Order."""

    id: str
    external_ids: ExternalIds = Field(alias="externalIds")
    revision: int | None = None
    status: str
    type: str

    agreement: Agreement
    authorization: Authorization
    lines: list[OrderLine] = Field(default_factory=list)
    parameters: ParameterBag = Field(default_factory=ParameterBag)
    product: Product
    seller: SellerAccount | None = None
    subscriptions: list[Subscription] = Field(default_factory=list)
    template: Template | None = None

    @property
    def agreement_id(self) -> str:
        """Return the agreement identifier."""
        return self.agreement.id

    @property
    def authorization_id(self) -> str:
        """Return the authorization identifier."""
        return self.authorization.id

    @property
    def customer_id(self) -> str | None:
        """Return the customer identifier from fulfillment parameters."""
        return self.parameters.get_fulfillment_value("customerId")

    @property
    def downsize_lines(self) -> list[OrderLine]:
        """Downsize lines from the order."""
        return [line for line in self.lines if line.quantity < line.old_quantity]

    @property
    def upsize_lines(self) -> list[OrderLine]:
        """Upsize lines from order."""
        return [line for line in self.lines if line.quantity >= line.old_quantity > 0]

    @property
    def new_lines(self) -> list[OrderLine]:
        """New lines from the order."""
        return [line for line in self.lines if line.old_quantity == 0]

    @property
    def product_id(self) -> str:
        """Return the product identifier."""
        return self.product.id

    @property
    def seller_id(self) -> str | None:
        """Return the seller identifier when available."""
        return None if self.seller is None else self.seller.id

    @classmethod
    def from_payload(cls, payload: Any) -> Self:
        """Build an order from an MPT client resource or plain payload."""
        return cls.model_validate(payload, from_attributes=True)

    def set_template(self, template: Any) -> None:
        """Update the order template from a client model or plain payload."""
        self.template = Template.model_validate(template, from_attributes=True)
