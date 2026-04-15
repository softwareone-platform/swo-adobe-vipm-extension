from pydantic import Field

from mpt_extension_sdk.models.audit import User
from mpt_extension_sdk.models.base import BaseModel


class Phone(BaseModel):
    """Phone model."""

    prefix: str
    number: str


class Contact(BaseModel):
    """Contact model."""

    email: str | None = None
    first_name: str | None = Field(default=None, alias="firstName")
    last_name: str | None = Field(default=None, alias="lastName")
    name: str

    phone: Phone | None = None
    user: User | None = None
