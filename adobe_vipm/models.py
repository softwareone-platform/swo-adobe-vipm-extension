from ninja import Schema


class Error(Schema):
    """MPT Error message schema."""

    id: str
    message: str
