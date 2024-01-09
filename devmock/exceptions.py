from secrets import token_hex


class DevmockException(Exception):
    def __init__(self, status_code, title, details):
        self.status_code = status_code
        self.title = title
        self.details = details

    def to_dict(self):
        return {
            "type": "https://tools.ietf.org/html/rfc9110#section-15.5.5",
            "title": self.title,
            "status": self.status_code,
            "detail": self.details,
            "traceId": f"00-{token_hex(16)}-{token_hex(8)}-00",
        }


class NotFoundException(DevmockException):
    def __init__(self, object_id):
        super().__init__(
            404,
            "Not Found",
            f"Entity for given id {object_id} not found",
        )
