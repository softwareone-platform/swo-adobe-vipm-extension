from mpt_extension_sdk_v6.models.base import BaseModel


class ExternalIds(BaseModel):
    """External identifiers model."""

    client: str | None = None
    operations: str | None = None
    vendor: str | None = None
