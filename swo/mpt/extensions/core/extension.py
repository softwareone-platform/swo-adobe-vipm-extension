from ninja import NinjaAPI

from .events import EventsRegistry


class Extension:
    def __init__(
        self,
        /,
    ) -> None:
        self.events: EventsRegistry = EventsRegistry()
        self.api: NinjaAPI = NinjaAPI()
