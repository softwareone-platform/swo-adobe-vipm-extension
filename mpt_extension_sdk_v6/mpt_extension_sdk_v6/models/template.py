from mpt_extension_sdk_v6.models.audit import Audit
from mpt_extension_sdk_v6.models.base import BaseModel
from mpt_extension_sdk_v6.models.product import Product


class Template(BaseModel):
    """Template model."""

    id: str
    content: str | None = None  # noqa: WPS110
    default: bool | None = None
    name: str | None = None
    revision: int | None = None
    type: str | None = None

    audit: Audit | None = None
    product: Product | None = None
