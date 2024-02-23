from functools import wraps
from typing import Callable, ParamSpec, TypeVar

from requests import HTTPError

Param = ParamSpec("Param")
RetType = TypeVar("RetType")


class AdobeError(Exception):
    pass


class AdobeProductNotFoundError(AdobeError):
    pass


class DistributorNotFoundError(AdobeError):
    pass


class ResellerNotFoundError(AdobeError):
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
            raise AdobeAPIError(e.response.json())

    return _wrapper
