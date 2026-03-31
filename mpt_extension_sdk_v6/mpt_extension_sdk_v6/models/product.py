from pydantic import Field

from mpt_extension_sdk_v6.models.base import BaseSchema


class ExternalIds(BaseSchema):
    """External identifiers  model."""

    vendor: str | None = None
    seller: str | None = None


class Product(BaseSchema):
    """Product  model."""

    id: str
    icon: str | None = None
    name: str
    revision: int | None = None

    external_ids: ExternalIds | None = Field(default=None, alias="externalIds")
    long_description: str | None = Field(default=None, alias="longDescription")
    short_description: str | None = Field(default=None, alias="shortDescription")


class ProductItem(BaseSchema):
    """Product item."""

    id: str
    name: str
    description: str | None = None

    external_ids: ExternalIds | None = Field(default=None, alias="externalIds")
