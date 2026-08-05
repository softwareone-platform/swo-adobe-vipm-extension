import json
import logging
from collections.abc import Callable
from functools import wraps
from typing import NoReturn, ParamSpec, TypeVar

from requests import HTTPError, JSONDecodeError, PreparedRequest
from requests.exceptions import ConnectionError as RequestsConnectionError
from requests.exceptions import RequestException, Timeout

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


class AdobeTransportError(Exception):
    """
    An Adobe call that failed before any HTTP response was received.

    Covers dropped connections and timeouts, where Adobe returned no status code and no
    payload, so there is nothing for `AdobeAPIError` to describe.

    Deliberately outside the `AdobeError` hierarchy: flows catch `AdobeError` to fail an
    order on a business rejection from Adobe, and a transient network fault must not take
    that path. Keeping it separate preserves the pre-existing behaviour, where a transport
    failure propagates for retry instead of failing the order.
    """

    def __init__(self, request_description: str, reason: str) -> None:
        self.request_description = request_description
        self.reason = reason
        super().__init__(f"Adobe transport failure on {request_description}: {reason}")


def _describe_failed_request(error: RequestException) -> str:
    """
    Describe the request behind a transport failure.

    Args:
        error: The requests exception raised for the failed call.

    Returns:
        str: The method, URL, and correlation id of the failed request.
    """
    request: PreparedRequest | None = error.request
    if request is None:
        return "an Adobe request"

    correlation_id = request.headers.get("x-correlation-id", "unknown")
    return f"{request.method} {request.url} (correlation id: {correlation_id})"


def _raise_adobe_response_error(error: HTTPError) -> NoReturn:
    """
    Convert an error response into the matching Adobe error.

    Args:
        error: The HTTP error raised for the error response.

    Raises:
        AdobeAPIError: When the response body is the documented Adobe error JSON.
        AdobeHttpError: When the response body is not JSON.
    """
    logger.error(error)
    try:  # noqa: WPS328, WPS505
        raise AdobeAPIError(error.response.status_code, error.response.json())
    except JSONDecodeError:
        raise AdobeHttpError(error.response.status_code, error.response.content.decode())


def wrap_http_error(func: Callable[Param, RetType]) -> Callable[Param, RetType]:  # ruff:ignore[non-pep695-generic-function]
    """
    Wrap HTTP and transport errors into Adobe errors.

    An HTTP response with an error status becomes an `AdobeAPIError` or `AdobeHttpError`. A
    failure with no response at all becomes an `AdobeTransportError` naming the request, so
    the caller and any alert identify the endpoint that failed.

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
            _raise_adobe_response_error(error)
        except (RequestsConnectionError, Timeout) as error:
            request_description = _describe_failed_request(error)
            logger.warning("Adobe transport failure on %s: %s", request_description, error)
            raise AdobeTransportError(request_description, str(error)) from error

    return _wrapper
