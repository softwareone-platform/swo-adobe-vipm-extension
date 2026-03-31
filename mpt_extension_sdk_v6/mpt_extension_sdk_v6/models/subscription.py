from pydantic import Field

from mpt_extension_sdk_v6.models.base import BaseSchema, ISODatetime
from mpt_extension_sdk_v6.models.external_id import ExternalIds
from mpt_extension_sdk_v6.models.parameter import ParameterBag
from mpt_extension_sdk_v6.models.product import ProductItem


class SubscriptionLine(BaseSchema):
    """Subscription line model."""

    id: str
    description: str | None = None
    quantity: int
    status: str | None = None

    product_item: ProductItem = Field(alias="item")


class SubscriptionSimple(BaseSchema):
    """Subscription model with simple details"""

    id: str
    name: str
    revision: int | None = None


class Subscription(SubscriptionSimple):
    """Subscription model."""

    auto_renew: bool | None = Field(default=None, alias="autoRenew")
    commitment_date: ISODatetime | None = Field(default=None, alias="commitmentDate")
    start_date: ISODatetime | None = Field(default=None, alias="startDate")
    termination_date: ISODatetime | None = Field(default=None, alias="terminationDate")

    external_ids: ExternalIds = Field(alias="externalIds")
    lines: list[SubscriptionLine] = Field(default_factory=list)
    parameters: ParameterBag = Field(default_factory=ParameterBag)
