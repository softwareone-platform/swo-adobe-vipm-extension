from dataclasses import dataclass
from typing import Literal, Mapping, Sequence

from typing_extensions import Annotated, Doc

EventType = Annotated[Literal["orders"], Doc("Unique identifier of the event type.")]


@dataclass
class Event:
    id: Annotated[str, Doc("Unique identifier of the event.")]
    type: EventType
    data: Annotated[Mapping | Sequence, Doc("Event data.")]
