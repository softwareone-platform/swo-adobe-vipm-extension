import datetime as dt
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field


class BaseSchema(BaseModel):
    """Base schema."""

    model_config = ConfigDict(from_attributes=True, extra="forbid", populate_by_name=True)


class EventDetails(BaseSchema):
    """Delivery metadata for extension event."""

    event_type: Annotated[
        str,
        Field(
            alias="eventType",
            description=(
                "The type of the event. Maps to the “routing.event” property of the EventMessage."
            ),
        ),
    ]
    enqueue_time: Annotated[
        dt.datetime,
        Field(
            alias="enqueueTime",
            description=(
                "The date/time the platform became aware of this event. "
                "Maps to the “timestamp” property of EventMessage."
            ),
        ),
    ]
    delivery_time: Annotated[
        dt.datetime,
        Field(
            alias="deliveryTime",
            description=(
                "The date/time the platform is delivering this event to the extension. "
                "Defaults to current date/time on the server."
            ),
        ),
    ]


class EventObject(BaseSchema):
    """Business object information from event payload."""

    id: Annotated[
        str, Field(description="Unique object ID, maps to the platform object ID property.")
    ]
    name: Annotated[
        str, Field(description="Object name, maps to the platform object name property.")
    ]
    object_type: Annotated[
        str,
        Field(
            alias="objectType",
            description="The object's type, maps to the “routing.entity” property "
            "of the EventMessage.",
        ),
    ]


class EventTask(BaseSchema):
    """Task context for task-based event delivery."""

    id: Annotated[str, Field(description="Task identifier.")]


class Event(BaseSchema):
    """Event schema."""

    id: Annotated[
        str,
        Field(
            description="Unique message ID, can be used to correlate with platform logs.",
        ),
    ]
    object: Annotated[
        EventObject,
        Field(
            description=(
                "Information about the event's related object. Maps to the first object "
                "of category “CurrentEntity” in the “objects” property of the EventMessage."
            ),
        ),
    ]
    details: Annotated[
        EventDetails,
        Field(
            description=(
                "Information about this event. Maps to the “routing” property of the EventMessage."
            ),
        ),
    ]
    task: Annotated[
        EventTask | None,
        Field(
            description=(
                "Information about the event's related task. "
                "Maps to the task created by Task Orchestrator."
            ),
        ),
    ] = None


class EventResponse(BaseSchema):
    """Task response schema for extension event callbacks."""

    response: Annotated[Literal["OK", "Defer", "Cancel"], Field(description="Task action.")]
    defer_delay: Annotated[
        str | None,
        Field(alias="deferDelay", description="Optional defer delay in ISO 8601 format."),
    ] = None
    cancel_reason: Annotated[
        str | None,
        Field(alias="cancelReason", description="Optional cancellation reason."),
    ] = None
