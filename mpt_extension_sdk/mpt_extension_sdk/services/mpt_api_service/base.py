from typing import Any

from mpt_api_client import AsyncMPTClient


class BaseService[Model]:
    """Base service class for all services."""

    _batch_size = 100

    def __init__(self, client: AsyncMPTClient) -> None:
        """Initialize service with an MPT client."""
        self._client = client

    async def _iterate_all(
        self, collection: Any, model: type[Model], batch_size: int = 100
    ) -> list[Model]:
        """Collect all resources from an iterable collection query."""
        return [
            model.from_payload(element)
            async for element in collection.iterate(batch_size=batch_size)
        ]
