from pydantic import Field

from mpt_extension_sdk_v6.models.account import Account, BuyerAccount, SellerAccount
from mpt_extension_sdk_v6.models.asset import AssetSimple
from mpt_extension_sdk_v6.models.authorization import Authorization
from mpt_extension_sdk_v6.models.base import BaseModel
from mpt_extension_sdk_v6.models.external_id import ExternalIds
from mpt_extension_sdk_v6.models.licensee import Licensee
from mpt_extension_sdk_v6.models.parameter import ParameterBag
from mpt_extension_sdk_v6.models.product import Product, ProductItem
from mpt_extension_sdk_v6.models.subscription import SubscriptionSimple


class AgreementLine(BaseModel):
    """Agreement line model."""

    id: str
    description: str | None = None
    quantity: int
    status: str | None = None

    product_item: ProductItem = Field(alias="item")


class Agreement(BaseModel):
    """Agreement model."""

    id: str
    icon: str | None = None
    name: str
    revision: int | None = None
    status: str | None = None

    authorization: Authorization | None = None
    assets: list[AssetSimple] = Field(default_factory=list)
    buyer: BuyerAccount | None = None
    client: Account
    external_ids: ExternalIds | None = Field(default=None, alias="externalIds")
    licensee: Licensee
    lines: list[AgreementLine] = Field(default_factory=list)
    parameters: ParameterBag  # noqa: WPS110
    product: Product
    seller: SellerAccount | None = None
    subscriptions: list[SubscriptionSimple] = Field(default_factory=list)
    vendor: Account | None = None
