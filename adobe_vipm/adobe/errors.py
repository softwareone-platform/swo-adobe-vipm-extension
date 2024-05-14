import json
from functools import wraps
from typing import Callable, ParamSpec, TypeVar

from requests import HTTPError, JSONDecodeError

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


class AdobeHttpError(AdobeError):
    def __init__(self, status_code: int, content: str):
        self.status_code = status_code
        self.content = content
        super().__init__(f"{self.status_code} - {self.content}")

class AdobeAPIError(AdobeHttpError):
    def __init__(self, status_code: int, payload: dict) -> None:
        super().__init__(status_code, json.dumps(payload))
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
            try:
                raise AdobeAPIError(e.response.status_code, e.response.json())
            except JSONDecodeError:
                raise AdobeHttpError(e.response.status_code, e.response.content.decode())

    return _wrapper
