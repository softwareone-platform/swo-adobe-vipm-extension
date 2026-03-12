from mpt_extension_sdk_v6.api.schemas.base import BaseSchema
from mpt_extension_sdk_v6.models.audit import Audit
from mpt_extension_sdk_v6.models.product import Product


class Template(BaseSchema):
    """Template model."""

    id: str
    name: str | None = None
    revision: int | None = None
    content: str | None = None
    type: str | None = None
    default: bool | None = None
    product: Product | None = None
    audit: Audit | None = None
