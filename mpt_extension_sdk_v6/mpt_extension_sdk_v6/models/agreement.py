from pydantic import AliasChoices, Field

from mpt_extension_sdk_v6.api.schemas.base import BaseSchema
from mpt_extension_sdk_v6.models.account import Account, SellerAccount
from mpt_extension_sdk_v6.models.authorization import Authorization
from mpt_extension_sdk_v6.models.external_id import ExternalIds
from mpt_extension_sdk_v6.models.parameter import ParameterBag
from mpt_extension_sdk_v6.models.product import Product, ProductItem
from mpt_extension_sdk_v6.models.subscription import Subscription


class AgreementLine(BaseSchema):
    """Agreement line model."""

    id: str
    quantity: int
    item: ProductItem
    status: str | None = None
    description: str | None = None


class Agreement(BaseSchema):
    """Agreement model."""

    id: str
    name: str
    icon: str | None = None
    revision: int | None = None
    status: str | None = None
    authorization: Authorization | None = None
    vendor: Account | None = None
    client: Account | None = None
    seller: SellerAccount | None = None
    product: Product | None = None
    external_ids: ExternalIds | None = Field(
        default=None,
        alias="externalIds",
        validation_alias=AliasChoices("externalIds", "external_ids"),
    )
    parameters: ParameterBag | None = None
    lines: list[AgreementLine] | None = None
    subscriptions: list[Subscription] = Field(default_factory=list)
