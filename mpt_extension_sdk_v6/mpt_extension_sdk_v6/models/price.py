from pydantic import Field

from mpt_extension_sdk_v6.models.base import BaseSchema, FloatDecimal


class Price(BaseSchema):
    """Price model."""

    currency: str
    default_markup: FloatDecimal | None = Field(default=None, alias="defaultMarkup")
    ppxy: FloatDecimal | None = Field(default=None, alias="PPxY")
    ppxm: FloatDecimal | None = Field(default=None, alias="PPxM")
    ppx1: FloatDecimal | None = Field(default=None, alias="PPx1")
    spxy: FloatDecimal | None = Field(default=None, alias="SPxY")
    spxm: FloatDecimal | None = Field(default=None, alias="SPxM")
    spx1: FloatDecimal | None = Field(default=None, alias="SPx1")
    unit_pp: FloatDecimal | None = Field(default=None, alias="unitPP")
    unit_sp: FloatDecimal | None = Field(default=None, alias="unitSP")
