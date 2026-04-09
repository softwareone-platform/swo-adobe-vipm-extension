from pydantic import AliasChoices, Field

from mpt_extension_sdk_v6.models.account import Account, SellerAccount
from mpt_extension_sdk_v6.models.base import BaseModel
from mpt_extension_sdk_v6.models.external_id import ExternalIds
from mpt_extension_sdk_v6.models.product import Product


class Authorization(BaseModel):
    """Authorization model."""

    id: str
    name: str
    revision: int | None = None
    currency: str

    external_ids: ExternalIds | None = Field(
        default=None,
        alias="externalIds",
        validation_alias=AliasChoices("externalIds", "external_ids"),
    )
    owner: SellerAccount | None = None
    product: Product | None = None
    vendor: Account | None = None
