from pydantic import Field

from mpt_extension_sdk_v6.models.base import BaseModel


class ExternalIds(BaseModel):
    """External identifiers model."""

    seller: str | None = None
    vendor: str | None = None


class Product(BaseModel):
    """Product  model."""

    id: str
    icon: str | None = None
    name: str
    revision: int | None = None

    external_ids: ExternalIds | None = Field(default=None, alias="externalIds")
    long_description: str | None = Field(default=None, alias="longDescription")
    short_description: str | None = Field(default=None, alias="shortDescription")


class ProductItem(BaseModel):
    """Product item."""

    id: str
    name: str
    description: str | None = None

    external_ids: ExternalIds | None = Field(default=None, alias="externalIds")
