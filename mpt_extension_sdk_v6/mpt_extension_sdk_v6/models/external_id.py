from mpt_extension_sdk_v6.models.base import BaseSchema


class ExternalIds(BaseSchema):
    """External identifiers  model."""

    client: str | None = None
    operations: str | None = None
    vendor: str | None = None
