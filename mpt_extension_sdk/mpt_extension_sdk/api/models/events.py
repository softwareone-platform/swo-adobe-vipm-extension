import datetime as dt
from enum import StrEnum
from typing import Annotated, Self

from mpt_extension_sdk.api.models.base import APIBaseModel
from pydantic import Field


class ResponseEnum(StrEnum):
    """Valid outcome values for event response."""

    CANCEL = "Cancel"
    DEFER = "Defer"
    OK = "OK"


class EventDetails(APIBaseModel):
    """Delivery metadata for extension events."""

    enqueue_time: Annotated[dt.datetime, Field(alias="enqueueTime")]
    event_type: Annotated[str, Field(alias="eventType")]
    delivery_time: Annotated[dt.datetime, Field(alias="deliveryTime")]


class EventObject(APIBaseModel):
    """Business object information from event payload."""

    id: str
    object_type: Annotated[str, Field(alias="objectType")]
    name: str


class EventTask(APIBaseModel):
    """Task metadata for task-based events."""

    id: str


class Event(APIBaseModel):
    """Base event payload."""

    id: str
    details: EventDetails
    object: EventObject


class TaskEvent(Event):
    """Task event payload."""

    task: EventTask


class EventResponse(APIBaseModel):
    """Event response schema for extension callbacks."""

    # HACK: the response field should be the first on the dict since there is a bug
    # in the mpt service
    response: Annotated[ResponseEnum, Field(description="Task action")]
    cancel_reason: Annotated[str | None, Field(alias="cancelReason", exclude=True)] = None
    defer_delay: Annotated[str | None, Field(alias="deferDelay", exclude=True)] = None

    @classmethod
    def cancel(cls, reason: str) -> Self:
        """Return a canceled task response.

        Args:
            reason: Human-readable cancellation reason.

        Returns:
            An cancel EventResponse.
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
            An Defer EventResponse.
        """
        return cls(response=ResponseEnum.DEFER, defer_delay=f"PT{seconds}S")
