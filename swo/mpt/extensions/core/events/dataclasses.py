from dataclasses import dataclass
from typing import Mapping, Sequence

from typing_extensions import Annotated, Doc


@dataclass
class Event:
    id: Annotated[str, Doc("Unique identifier of the event.")]
    type: Annotated[str, Doc("Unique identifier of the event type.")]
    data: Annotated[Mapping | Sequence, Doc("Event data.")]
