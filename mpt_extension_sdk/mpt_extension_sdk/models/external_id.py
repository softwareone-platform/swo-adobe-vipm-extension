from mpt_extension_sdk.models.base import BaseModel


class ExternalIds(BaseModel):
    """External identifiers model."""

    client: str | None = None
    operations: str | None = None
    vendor: str | None = None
