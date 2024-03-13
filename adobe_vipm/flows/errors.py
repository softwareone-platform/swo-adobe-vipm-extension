from functools import wraps

from requests import HTTPError


class MPTError(Exception):
    def __init__(self, payload):
        self.payload = payload
        self.status = payload["status"]
        self.title = payload["title"]
        self.trace_id = payload["traceId"]
        self.errors = payload.get("errors")

    def __str__(self):
        return (
            f"{self.status} {self.title} trace: {self.trace_id} errors: {self.errors}"
        )

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


class ValidationError:
    def __init__(self, id, message):
        self.id = id
        self.message = message

    def to_dict(self, **kwargs):
        return {
            "id": self.id,
            "message": self.message.format(**kwargs),
        }
