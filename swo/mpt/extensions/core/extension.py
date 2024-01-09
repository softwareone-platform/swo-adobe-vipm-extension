from typing import TypeVar

from ninja import NinjaAPI

from .events import EventsRegistry

ExtensionType = TypeVar("ExtensionType", bound="Extension")


class Extension:
    def __init__(
        self: ExtensionType,
        /,
    ) -> None:
        self.events: EventsRegistry = EventsRegistry()
        self.api: NinjaAPI = NinjaAPI()
