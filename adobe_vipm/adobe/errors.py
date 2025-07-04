import json
import logging
from functools import wraps
from typing import Callable, ParamSpec, TypeVar

from requests import HTTPError, JSONDecodeError

Param = ParamSpec("Param")
RetType = TypeVar("RetType")

logger = logging.getLogger(__name__)


class AdobeError(Exception):
    pass


class AdobeProductNotFoundError(AdobeError):
    pass


class AuthorizationNotFoundError(AdobeError):
    pass


class ResellerNotFoundError(AdobeError):
    pass


class CountryNotFoundError(AdobeError):
    pass


class CustomerDiscountsNotFoundError(AdobeError):
    pass


class SubscriptionNotFoundError(AdobeError):
    pass


class SubscriptionUpdateError(AdobeError):
    pass


class AdobeHttpError(AdobeError):
    def __init__(self, status_code: int, content: str):
        self.status_code = status_code
        self.content = content
        super().__init__(f"{self.status_code} - {self.content}")


class AdobeAPIError(AdobeHttpError):
    def __init__(self, status_code: int, payload: dict) -> None:
        super().__init__(status_code, json.dumps(payload))
        self.payload: dict = payload
        # 504 error response doesn't follow the expected format -
        # it uses "error_code" field instead of "code"
        self.code: str = payload.get("code") or payload.get("error_code") or payload.get("error")
        self.message: str = (
            payload.get("message") or payload.get("error_description") or str(payload)
        )
        self.details: list = payload.get("additionalDetails", [])

    def __str__(self) -> str:
        message = f"{self.code} - {self.message}"
        if self.details:
            message = f"{message}: {', '.join(self.details)}"
        return message

    def __repr__(self) -> str:
        return str(self.payload)


def wrap_http_error(func: Callable[Param, RetType]) -> Callable[Param, RetType]:
    @wraps(func)
    def _wrapper(*args: Param.args, **kwargs: Param.kwargs) -> RetType:
        try:
            return func(*args, **kwargs)
        except HTTPError as e:
            logger.error(e)
            try:
                raise AdobeAPIError(e.response.status_code, e.response.json())
            except JSONDecodeError:
                raise AdobeHttpError(e.response.status_code, e.response.content.decode())

    return _wrapper
