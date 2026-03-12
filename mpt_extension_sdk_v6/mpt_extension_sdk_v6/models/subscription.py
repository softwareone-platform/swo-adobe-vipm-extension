import datetime as dt
from typing import Any, Self

from pydantic import AliasChoices, Field

from mpt_extension_sdk_v6.api.schemas.base import BaseSchema
from mpt_extension_sdk_v6.models.external_id import ExternalIds
from mpt_extension_sdk_v6.models.parameter import ParameterBag
from mpt_extension_sdk_v6.models.product import ProductItem


class SubscriptionLine(BaseSchema):
    """Subscription line model."""

    id: str
    quantity: int
    item: ProductItem
    status: str | None = None
    description: str | None = None


class Subscription(BaseSchema):
    """Subscription model."""

    id: str
    auto_renew: bool | None = Field(
        default=None,
        alias="autoRenew",
        validation_alias=AliasChoices("autoRenew", "auto_renew"),
    )
    commitment_date: dt.datetime | None = Field(
        default=None,
        alias="commitmentDate",
        validation_alias=AliasChoices("commitmentDate", "commitment_date"),
    )
    external_ids: ExternalIds | None = Field(
        default=None,
        alias="externalIds",
        validation_alias=AliasChoices("externalIds", "external_ids"),
    )
    name: str
    revision: int | None = None
    status: str | None = None
    start_date: dt.datetime | None = Field(
        default=None,
        alias="startDate",
        validation_alias=AliasChoices("startDate", "start_date"),
    )
    termination_date: dt.datetime | None = Field(
        default=None,
        alias="terminationDate",
        validation_alias=AliasChoices("terminationDate", "termination_date"),
    )

    parameters: ParameterBag | None = None
    lines: list[SubscriptionLine] | None = None

    @classmethod
    def from_payload(cls, payload: Any) -> Self:
        """Build a subscription from an MPT client resource or plain payload."""
        return cls.model_validate(payload, from_attributes=True)
