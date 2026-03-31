import datetime as dt
from enum import StrEnum
from typing import Annotated, Self

from mpt_extension_sdk_v6.api.schemas.base import APIBaseSchema
from pydantic import Field


class ResponseEnum(StrEnum):
    """Valid outcome values for event response."""

    CANCEL = "Cancel"
    DEFER = "Defer"
    OK = "OK"


class EventDetails(APIBaseSchema):
    """Delivery metadata for extension events."""

    event_type: Annotated[str, Field(alias="eventType")]
    enqueue_time: Annotated[dt.datetime, Field(alias="enqueueTime")]
    delivery_time: Annotated[dt.datetime, Field(alias="deliveryTime")]


class EventObject(APIBaseSchema):
    """Business object information from event payload."""

    id: str
    name: str
    object_type: Annotated[str, Field(alias="objectType")]


class EventTask(APIBaseSchema):
    """Task metadata for task-based events."""

    id: str


class Event(APIBaseSchema):
    """Base event payload."""

    id: str
    object: EventObject
    details: EventDetails


class TaskEvent(Event):
    """Task event payload."""

    task: EventTask


class EventResponse(APIBaseSchema):
    """Event response schema for extension callbacks."""

    response: Annotated[ResponseEnum, Field(description="Task action")]
    defer_delay: Annotated[str | None, Field(alias="deferDelay")] = None
    cancel_reason: Annotated[str | None, Field(alias="cancelReason")] = None

    @classmethod
    def cancel(cls, reason: str) -> Self:
        """Return a canceled task response.

        Args:
            reason: Human-readable cancellation reason.

        Returns:
            An EventResponse instructing the platform to cancel the event.
        """
        return cls(response=ResponseEnum.CANCEL, cancel_reason=reason)

    @classmethod
    def ok(cls) -> Self:
        """Return a successful response."""
        return cls(response=ResponseEnum.OK)

    @classmethod
    def reschedule(cls, seconds: int = 300) -> Self:
        """Return a deferred response.

        Args:
            seconds: Number of seconds to wait before retrying.

        Returns:
            An EventResponse instructing the platform to retry later.
        """
        return cls(response=ResponseEnum.DEFER, defer_delay=f"PT{seconds}S")
