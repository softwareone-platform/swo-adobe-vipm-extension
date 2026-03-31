import logging
from typing import Any, Self

from pydantic import BaseModel, ConfigDict

logger = logging.getLogger(__name__)


class APIBaseSchema(BaseModel):
    """Base schema."""

    model_config = ConfigDict(from_attributes=True, extra="allow", validate_by_name=True)

    def to_dict(self) -> dict[str, Any]:
        """Dump the model using the alias field names."""
        return self.model_dump(by_alias=True)

    @classmethod
    def from_payload(cls, payload: Any) -> Self:
        """Build a model from an API payload."""
        return cls.model_validate(payload, from_attributes=True)
