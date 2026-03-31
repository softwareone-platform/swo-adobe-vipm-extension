from pydantic import Field

from mpt_extension_sdk_v6.models.base import BaseSchema
from mpt_extension_sdk_v6.models.external_id import ExternalIds
from mpt_extension_sdk_v6.models.parameter import ParameterBag
from mpt_extension_sdk_v6.models.price import Price
from mpt_extension_sdk_v6.models.template import Template


class AssetLine(BaseSchema):
    """Asset line model."""

    id: str
    old_quantity: int
    quantity: int

    price: Price


class AssetSimple(BaseSchema):
    """Asset model."""

    id: str
    name: str
    revision: int | None = None
    status: str


class Asset(AssetSimple):
    """Asset model."""

    external_id: ExternalIds | None = None
    price: Price
    lines: list[AssetLine] = Field(default_factory=list)
    template: Template | None = None
    parameters: ParameterBag | None = None
