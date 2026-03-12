import logging
from typing import Any, Self

from pydantic import BaseModel, ConfigDict, model_validator

logger = logging.getLogger(__name__)


class BaseSchema(BaseModel):
    """Base schema."""

    model_config = ConfigDict(from_attributes=True, extra="allow", validate_by_name=True)

    @model_validator(mode="after")
    def check_extra(self) -> Self:
        """Temp validation method to check extra fields."""
        if self.__pydantic_extra__:
            logger.warning("Extra fields: %s", self.__pydantic_extra__)

        return self

    def to_dict(self) -> dict[str, Any]:
        """Dump the model using the alias field names."""
        return self.model_dump(by_alias=True)

    @classmethod
    def from_dict(cls, **payload: Any) -> Self:
        """Build a model from an API payload."""
        return cls.model_validate(payload)
