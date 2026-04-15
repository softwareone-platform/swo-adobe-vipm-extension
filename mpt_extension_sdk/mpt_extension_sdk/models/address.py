from pydantic import Field

from mpt_extension_sdk.models.base import BaseModel


class Address(BaseModel):
    """Address model."""

    address_line1: str = Field(alias="AddressLine1")
    address_line2: str | None = Field(default=None, alias="AddressLine2")
    city: str
    country: str
    post_code: str = Field(alias="postCode")
    state: str
