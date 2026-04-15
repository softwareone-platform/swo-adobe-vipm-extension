import datetime as dt
import logging
from decimal import Decimal
from typing import Annotated, Any, Self

from pydantic import BaseModel as PydanticBaseModel
from pydantic import ConfigDict, PlainSerializer

logger = logging.getLogger(__name__)

FloatDecimal = Annotated[Decimal, PlainSerializer(lambda el: float(el), return_type=float)]  # noqa: PLW0108, WPS506
ISODatetime = Annotated[
    dt.datetime,
    PlainSerializer(lambda el: el.isoformat(), return_type=str, when_used="json-unless-none"),
]


class BaseModel(PydanticBaseModel):
    """Base schema."""

    model_config = ConfigDict(
        from_attributes=True, extra="allow", validate_by_name=True, frozen=True
    )

    def to_dict(self) -> dict[str, Any]:
        """Dump the model using the alias field names."""
        return self.model_dump(by_alias=True, exclude_none=True, mode="json")

    @classmethod
    def from_payload(cls, payload: Any) -> Self:
        """Build a model from an API payload."""
        return cls.model_validate(payload, from_attributes=True)
