from pydantic import Field

from mpt_extension_sdk_v6.models.account import SellerAccount
from mpt_extension_sdk_v6.models.agreement import Agreement
from mpt_extension_sdk_v6.models.asset import Asset
from mpt_extension_sdk_v6.models.authorization import Authorization
from mpt_extension_sdk_v6.models.base import BaseModel
from mpt_extension_sdk_v6.models.external_id import ExternalIds
from mpt_extension_sdk_v6.models.parameter import ParameterBag
from mpt_extension_sdk_v6.models.price import Price
from mpt_extension_sdk_v6.models.product import Product, ProductItem
from mpt_extension_sdk_v6.models.subscription import Subscription
from mpt_extension_sdk_v6.models.template import Template


class OrderLine(BaseModel):
    """Order line."""

    id: str
    description: str | None = None
    old_quantity: int = Field(default=0, alias="oldQuantity")
    quantity: int

    asset: Asset | None = None
    product_item: ProductItem = Field(alias="item")
    price: Price
    subscription: Subscription | None = None


class Order(BaseModel):
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
    parameters: ParameterBag = Field(default_factory=ParameterBag)  # noqa: WPS110
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
        if not self.agreement.external_ids:
            return None

        return self.agreement.external_ids.vendor

    @property
    def product_id(self) -> str:
        """Return the product identifier."""
        return self.product.id

    @property
    def seller_id(self) -> str | None:
        """Return the seller identifier when available."""
        return None if self.seller is None else self.seller.id

    @property
    def downsize_lines(self) -> list[OrderLine]:
        """Downsize lines from the order."""
        return [elem for elem in self.lines if elem.quantity < elem.old_quantity]

    @property
    def upsize_lines(self) -> list[OrderLine]:
        """Upsize lines from order."""
        return [elem for elem in self.lines if elem.quantity >= elem.old_quantity > 0]

    @property
    def new_lines(self) -> list[OrderLine]:
        """New lines from the order."""
        return [elem for elem in self.lines if elem.old_quantity == 0]

    def get_line_by_sku(self, sku: str) -> OrderLine:
        """Return the line matching a SKU."""
        for elem in self.lines:
            if elem.product_item.external_ids.vendor in sku:
                return elem

        raise ValueError(f"No line found for SKU: {sku}")
