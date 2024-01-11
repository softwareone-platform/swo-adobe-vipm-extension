from functools import wraps

from requests import HTTPError


class MPTError(Exception):
    def __init__(self, payload):
        self.payload = payload
        self.status = payload["status"]
        self.title = payload["title"]
        self.details = payload["details"]

    def __str__(self):
        return f"{self.status} {self.title}: {self.details}"

    def __repr__(self):
        return str(self.payload)


def wrap_http_error(func):
    @wraps(func)
    def _wrapper(*args, **kwargs):
        try:
            return func(*args, **kwargs)
        except HTTPError as e:
            raise MPTError(e.response.json())

    return _wrapper
