import logging
from typing import Any

from mpt_extension_sdk_v6.models import Agreement
from mpt_extension_sdk_v6.services.mpt_api_service.base import BaseService

logger = logging.getLogger(__name__)


class AgreementService(BaseService[Agreement]):
    """Agreements service."""

    async def get_by_id(self, agreement_id: str) -> Agreement:
        """Fetch an agreement."""
        agreement = await self._client.commerce.agreements.get(
            agreement_id,
            select=[
                "client",
                "seller",
                "buyer",
                "listing",
                "product",
                "subscriptions",
                "assets",
                "lines",
                "parameters",
            ],
        )
        logger.debug("Fetched agreement %s: %s", agreement_id, agreement.to_dict())
        return Agreement.from_payload(agreement)

    async def update(self, agreement_id: str, **kwargs: Any) -> None:
        """Update an agreement."""
        await self._client.commerce.agreements.update(agreement_id, kwargs)
