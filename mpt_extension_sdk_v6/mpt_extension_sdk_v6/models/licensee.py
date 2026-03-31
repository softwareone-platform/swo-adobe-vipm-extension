from mpt_extension_sdk_v6.models.address import Address
from mpt_extension_sdk_v6.models.base import BaseSchema
from mpt_extension_sdk_v6.models.contact import Contact
from mpt_extension_sdk_v6.models.external_id import ExternalIds


class Licensee(BaseSchema):
    """Licensee model."""

    id: str
    name: str
    status: str
    icon: str | None = None

    address: Address | None = None
    contact: Contact | None = None
    external_id: ExternalIds | None = None
