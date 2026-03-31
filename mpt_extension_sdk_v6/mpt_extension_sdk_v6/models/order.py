from typing import Any

from pydantic import Field

from mpt_extension_sdk_v6.models.account import SellerAccount
from mpt_extension_sdk_v6.models.agreement import Agreement
from mpt_extension_sdk_v6.models.asset import Asset
from mpt_extension_sdk_v6.models.authorization import Authorization
from mpt_extension_sdk_v6.models.base import BaseSchema
from mpt_extension_sdk_v6.models.external_id import ExternalIds
from mpt_extension_sdk_v6.models.parameter import ParameterBag
from mpt_extension_sdk_v6.models.price import Price
from mpt_extension_sdk_v6.models.product import Product, ProductItem
from mpt_extension_sdk_v6.models.subscription import Subscription
from mpt_extension_sdk_v6.models.template import Template


class OrderLine(BaseSchema):
    """Order line."""

    id: str
    description: str | None = None
    old_quantity: int = Field(default=0, alias="oldQuantity")
    quantity: int

    asset: Asset | None = None
    product_item: ProductItem = Field(alias="item")
    price: Price
    subscription: Subscription | None = None


class Order(BaseSchema):
    """Order."""

    id: str
    revision: int | None = None
    status: str  # TODO: add enum
    type: str

    agreement: Agreement
    assets: list[Asset] = Field(default_factory=list)
    authorization: Authorization
    external_ids: ExternalIds = Field(alias="externalIds")
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

    def complete(self) -> None:
        """Mark the order as completed."""
        self.status = "Completed"

    def get_line_by_sku(self, sku: str) -> OrderLine:
        """Return the line matching a SKU."""
        for line in self.lines:
            if line.product_item.external_ids.vendor in sku:
                return line

        raise ValueError(f"No line found for SKU: {sku}")

    def set_template(self, template: dict[str, Any]) -> None:
        """Update the order template from a client model or plain payload."""
        self.template = Template.model_validate(template, from_attributes=True)
