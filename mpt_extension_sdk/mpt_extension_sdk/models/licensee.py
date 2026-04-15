from mpt_extension_sdk.models.address import Address
from mpt_extension_sdk.models.base import BaseModel
from mpt_extension_sdk.models.contact import Contact
from mpt_extension_sdk.models.external_id import ExternalIds


class Licensee(BaseModel):
    """Licensee model."""

    id: str
    name: str
    status: str
    icon: str | None = None

    address: Address | None = None
    contact: Contact | None = None
    external_id: ExternalIds | None = None
