from pydantic import BaseModel, Field


class Order(BaseModel):
    external_ids: dict | None = Field(default=None, alias="externalIds")
    parameters: dict | None = None
    items: dict | None = None
    reason: str | None = None
    template: dict | None = None


class Subscription(BaseModel):
    name: str | None = None
    parameters: dict | None = None
    price: dict | None = None
    lines: list | None = None
    external_ids: dict | None = Field(default=None, alias="externalIds")
    start_date: str | None = Field(default=None, alias="startDate")
