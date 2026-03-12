from mpt_extension_sdk_v6.api.schemas.base import BaseSchema


class Account(BaseSchema):
    """Account model."""

    id: str
    name: str
    icon: str | None = None
    revision: int | None = None


class SellerAccount(Account):
    """Seller  model."""

    currency: str | None = None
