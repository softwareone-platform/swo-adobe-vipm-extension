from functools import lru_cache

from mpt_extension_sdk.services.api_client_v2.mpt_api_client import AsyncMPTClient


@lru_cache
def build_mpt_client(base_url: str, api_token: str) -> AsyncMPTClient:
    """Build and cache MPT client instance."""
    return AsyncMPTClient.from_config(base_url=base_url, api_token=api_token)
