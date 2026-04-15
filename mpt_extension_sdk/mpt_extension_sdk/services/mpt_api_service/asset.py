from typing import Any

from mpt_extension_sdk.models import Asset
from mpt_extension_sdk.services.mpt_api_service.base import BaseService


class AssetService(BaseService[Asset]):
    """Asset service."""

    async def create(self, asset: Any) -> Asset:
        """Create an asset."""
        return Asset.from_payload(await self._client.commerce.assets.create(asset.to_dict()))

    async def create_order_asset(self, order_id: str, **kwargs: dict[str, Any]) -> Asset:
        """Create an asset inside an order."""
        return Asset.from_payload(
            await self._client.commerce.orders.assets(order_id).create(kwargs)
        )

    async def get_by_id(self, asset_id: str) -> Asset:
        """Fetch an asset by ID."""
        return Asset.from_payload(await self._client.commerce.assets.get(asset_id))

    async def update(self, asset_id: str, **kwargs: dict[str, Any]) -> Asset:
        """Update an asset."""
        return Asset.from_payload(await self._client.commerce.assets.update(asset_id, kwargs))
