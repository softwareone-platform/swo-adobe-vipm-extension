import json
from functools import wraps

from requests import HTTPError, JSONDecodeError


class MPTError(Exception):
    """Base exception for MPT errors."""


class MPTHttpError(MPTError):
    """Base exception for MPT Http errors."""

    def __init__(self, status_code: int, content: str):
        self.status_code = status_code
        self.content = content
        super().__init__(f"{self.status_code} - {self.content}")


class MPTAPIError(MPTHttpError):
    """Base exception for MPT API errors."""

    def __init__(self, status_code, payload):
        super().__init__(status_code, json.dumps(payload))
        self.payload = payload
        self.status = payload.get("status")
        self.title = payload.get("title")
        self.detail = payload.get("detail")
        self.trace_id = payload.get("traceId")
        self.errors = payload.get("errors")

    def __str__(self):
        base = f"{self.status} {self.title} - {self.detail} ({self.trace_id})"

        if self.errors:
            return f"{base}\n{json.dumps(self.errors, indent=2)}"
        return base

    def __repr__(self):
        return str(self.payload)


def wrap_http_error(func):
    """Wraps and processes http errors for provided function."""

    @wraps(func)
    def _wrapper(*args, **kwargs):
        try:
            return func(*args, **kwargs)
        except HTTPError as error:
            try:
                raise MPTAPIError(error.response.status_code, error.response.json())
            except JSONDecodeError:
                raise MPTHttpError(error.response.status_code, error.response.content.decode())

    return _wrapper


# TODO: why not dataclass?
class ValidationError:
    """Validation error."""

    def __init__(self, message_id, message):
        self.id = message_id
        self.message = message

    def to_dict(self, **kwargs):
        """Converts validation error to the MPT error message dict."""
        return {
            "id": self.id,
            "message": self.message.format(**kwargs),
        }


class ValidationBusinessError(Exception):
    """Validation business error."""


class GovernmentLGANotValidOrderError(ValidationBusinessError):
    """Government without LGA."""


class GovernmentNotValidOrderError(ValidationBusinessError):
    """Government without LGA."""


class AirTableError(Exception):
    """Base exception to Airtable Error."""


class AirTableHttpError(AirTableError):
    """Base exception for Airtable Http Error."""

    def __init__(self, status_code: int, content: str):
        self.status_code = status_code
        self.content = content
        super().__init__(f"{self.status_code} - {self.content}")


class AirTableAPIError(AirTableHttpError):
    """Base exception for Airtable API Error."""

    def __init__(self, status_code: int, payload) -> None:
        super().__init__(status_code, json.dumps(payload))
        self.payload = payload
        self.code = status_code
        self.message = payload.get("error", {}).get("message", "")

    def __str__(self) -> str:
        return f"{self.code} - {self.message}"

    def __repr__(self) -> str:
        return str(self.payload)


def wrap_airtable_http_error(func):
    """Wraps and processes http errors for provided function."""

    @wraps(func)
    def _wrapper(*args, **kwargs):
        try:
            return func(*args, **kwargs)
        except HTTPError as error:
            try:
                raise AirTableAPIError(error.response.status_code, error.response.json())
            except JSONDecodeError:
                raise AirTableHttpError(error.response.status_code, error.response.content.decode())

    return _wrapper
