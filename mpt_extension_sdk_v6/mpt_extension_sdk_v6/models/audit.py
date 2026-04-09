from mpt_extension_sdk_v6.models.base import BaseModel


class User(BaseModel):
    """User model."""

    id: str
    name: str
    revision: int


class AuditData(BaseModel):
    """Audit data model."""

    at: str

    by: User


class Audit(BaseModel):
    """Audit model."""

    created: AuditData | None = None
    updated: AuditData | None = None
