from ninja import Schema


class Error(Schema):
    id: str
    message: str
