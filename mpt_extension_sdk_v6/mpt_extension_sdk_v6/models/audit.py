from mpt_extension_sdk_v6.models.base import BaseSchema


class User(BaseSchema):
    """User model."""

    id: str
    name: str
    revision: int


class AuditData(BaseSchema):
    """Audit data model."""

    at: str
    by: User


class Audit(BaseSchema):
    """Audit model."""

    created: AuditData | None = None
    updated: AuditData | None = None
