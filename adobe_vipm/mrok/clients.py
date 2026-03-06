from functools import cache

from mpt_extension_sdk.mpt_http.base import MPTClient

from adobe_vipm.mrok.config import RuntimeSettings


def get_mpt_client(settings: RuntimeSettings) -> MPTClient:
    """Return shared MPT client instance.

    Args:
        settings: Runtime settings.

    Returns:
        Shared MPT API client.
    """
    return _build_mpt_client(f"{settings.base_url}/public/v1", settings.api_key)


@cache
def _build_mpt_client(base_url: str, api_token: str) -> MPTClient:
    """Build cached MPT client instance.

    Args:
        base_url: MPT API base URL.
        api_token: MPT API token.

    Returns:
        Shared MPT API client.
    """
    return MPTClient(base_url, api_token)
