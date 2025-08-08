import json
import logging
from collections.abc import Callable
from functools import wraps
from typing import ParamSpec, TypeVar

from requests import HTTPError, JSONDecodeError

Param = ParamSpec("Param")  # noqa: WPS110
RetType = TypeVar("RetType")

logger = logging.getLogger(__name__)


class AdobeError(Exception):
    """Basic Adobe Client Error."""


class AdobeProductNotFoundError(AdobeError):
    """Product not found in the configuration."""


class AuthorizationNotFoundError(AdobeError):
    """Authorization not found in configuration."""


class ResellerNotFoundError(AdobeError):
    """Reseller not found."""


class CountryNotFoundError(AdobeError):
    """Country is not found."""


class CustomerDiscountsNotFoundError(AdobeError):
    """Customer benefits are not found for the customer."""


class SubscriptionNotFoundError(AdobeError):
    """Subscription not found."""


class SubscriptionUpdateError(AdobeError):
    """Can't update subscription on Adobe side."""


class AdobeHttpError(AdobeError):
    """Basic Adobe API HTTP error."""

    def __init__(self, status_code: int, response_content: str):
        self.status_code = status_code
        self.response_content = response_content
        super().__init__(f"{self.status_code} - {self.response_content}")


class AdobeAPIError(AdobeHttpError):
    """Adobe API error."""

    def __init__(self, status_code: int, payload: dict) -> None:
        super().__init__(status_code, json.dumps(payload))
        self.payload: dict = payload
        # 504 error response doesn't follow the expected format -
        # it uses "error_code" field instead of "code"
        self.code: str | None = payload.get("code")
        if not self.code:
            self.code = payload.get("error_code")
        if not self.code:
            self.code = payload.get("error")

        self.message: str = (
            payload.get("message") or payload.get("error_description") or str(payload)
        )
        self.details: list = payload.get("additionalDetails", [])

    def __str__(self) -> str:
        """Stringify Adobe API error."""
        message = f"{self.code} - {self.message}"
        if self.details:
            details_str = ", ".join(self.details)
            message = f"{message}: {details_str}"
        return message

    def __repr__(self) -> str:
        """Repr Adobe API error."""
        return str(self.payload)


def wrap_http_error(func: Callable[Param, RetType]) -> Callable[Param, RetType]:  # noqa: UP047
    """
    Wrap HTTP error to Adobe API Error.

    Args:
        func: function to wrap and handle exceptions

    Returns:
        callable: wrapped function
    """

    @wraps(func)
    def _wrapper(*args: Param.args, **kwargs: Param.kwargs) -> RetType:  # noqa: WPS430
        try:
            return func(*args, **kwargs)
        except HTTPError as error:
            logger.error(error)  # noqa: TRY400
            try:  # noqa: WPS328, WPS505
                raise AdobeAPIError(error.response.status_code, error.response.json())
            except JSONDecodeError:
                raise AdobeHttpError(error.response.status_code, error.response.content.decode())

    return _wrapper
