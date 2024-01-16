from functools import wraps
from typing import Callable, TypeVar

from requests import HTTPError

T = TypeVar("T")


class AdobeError(Exception):
    pass


class AdobeProductNotFoundError(AdobeError):
    pass


class CredentialsNotFoundError(AdobeError):
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


def wrap_http_error(func: Callable[..., T]):
    @wraps(func)
    def _wrapper(*args, **kwargs) -> T:
        try:
            return func(*args, **kwargs)
        except HTTPError as e:
            raise AdobeAPIError(e.response.json())

    return _wrapper
