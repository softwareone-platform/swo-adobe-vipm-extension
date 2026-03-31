from typing import Any

import httpx


def register_extension_instance(
    base_url: str, extension_id: str, api_token: str, payload: dict[str, Any]
) -> dict[str, Any]:
    """Register an extension instance and return the platform payload."""
    response = httpx.post(
        f"{base_url}/public/v1/integration/extensions/{extension_id}/instances",
        json=payload,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_token}",
        },
        timeout=60,
    )
    response.raise_for_status()
    return response.json()
