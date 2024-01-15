from typing import Any, Callable, Mapping, Sequence, TypeVar

from typing_extensions import Annotated, Doc

from .dataclasses import Event

EventsRegistryType = TypeVar("EventsRegistryType", bound="EventsRegistry")
EventListener = TypeVar("EventListener", bound=Callable[[Any, Event], None])


class EventsRegistry:
    def __init__(
        self: EventsRegistryType,
    ) -> None:
        self.listeners: Mapping[str, EventListener] = {}

    def listener(
        self: EventsRegistryType,
        event_type: Annotated[
            str,
            Doc("Unique identifier of the event type."),
        ],
        /,
    ) -> EventListener:
        """
        Unique identifier of the event type.

        ## Example

        ```python
        from swo.mpt.extensions.core import Extension

        ext = Extension()


        @ext.events.listener("orders")
        def process_order(client, event):
            ...
        ```
        """

        def decorator(func: EventListener) -> None:
            self.listeners[event_type] = func
            return func

        return decorator

    def get_listener(
        self: EventsRegistryType,
        event_type: Annotated[
            str,
            Doc("Unique identifier of the event type."),
        ],
    ) -> EventListener:
        return self.listeners.get(event_type)

    def get_registered_types(self: EventsRegistryType) -> Sequence[str]:
        return list(self.listeners.keys())

    def is_event_supported(
        self: EventsRegistryType,
        event_type: Annotated[
            str,
            Doc("Unique identifier of the event type."),
        ],
    ) -> bool:
        return event_type in self.listeners
