from pydantic import Field

from mpt_extension_sdk_v6.models.audit import User
from mpt_extension_sdk_v6.models.base import BaseSchema


class Phone(BaseSchema):
    """Phone model."""

    prefix: str
    number: str


class Contact(BaseSchema):
    """Contact model."""

    email: str | None = None
    first_name: str | None = Field(default=None, alias="firstName")
    name: str
    last_name: str | None = Field(default=None, alias="lastName")

    phone: Phone | None = None
    user: User | None = None
