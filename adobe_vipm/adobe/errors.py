from functools import wraps
from typing import Callable, ParamSpec, TypeVar

from requests import HTTPError

Param = ParamSpec("Param")
RetType = TypeVar("RetType")


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


class AdobeAPIError(AdobeError):
    def __init__(self, payload: dict) -> None:
        self.payload: dict = payload
        self.code: str = payload["code"]
        self.message: str = payload["message"]
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
            if e.response.headers.get("Content-Type") == "application/json":
                raise AdobeAPIError(e.response.json())
            raise AdobeError(f"{e.response.status_code} - {e.response.content.decode()}")

    return _wrapper
