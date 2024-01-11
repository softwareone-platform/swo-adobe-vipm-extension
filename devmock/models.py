from pydantic import BaseModel, Field


class Order(BaseModel):
    external_ids: dict | None = Field(default=None, alias="externalIDs")
    parameters: dict | None = None


class Subscription(BaseModel):
    name: str | None = None
    parameters: dict | None = None
    items: list | None = None
    start_date: str | None = Field(default=None, alias="startDate")
