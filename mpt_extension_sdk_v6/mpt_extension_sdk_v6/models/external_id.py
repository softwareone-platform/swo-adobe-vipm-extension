from mpt_extension_sdk_v6.api.schemas.base import BaseSchema


class ExternalIds(BaseSchema):
    """External identifiers  model."""

    client: str | None = None
    operations: str | None = None
    vendor: str | None = None
