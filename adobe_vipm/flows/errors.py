from dataclasses import dataclass
from typing import Any


@dataclass
class ValidationError:
    """Validation error."""

    id: str
    message: str

    def to_dict(self, **kwargs) -> dict[str, Any]:
        """Converts validation error to the MPT error message dict."""
        return {
            "id": self.id,
            "message": self.message.format(**kwargs),
        }
