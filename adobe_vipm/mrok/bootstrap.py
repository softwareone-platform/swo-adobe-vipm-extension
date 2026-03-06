import json
import logging
from pathlib import Path

import requests

from adobe_vipm.mrok.config import RuntimeSettings

logger = logging.getLogger(__name__)


def bootstrap_extension_instance(settings: RuntimeSettings) -> None:
    """Register extension instance in the new extension framework.

    Args:
        settings: Runtime settings.
    """
    if not settings.extension_id:
        raise RuntimeError("No Extension id has been provided")

    if not settings.base_url:
        raise RuntimeError("No base url has been provided")

    if not settings.api_key:
        raise RuntimeError("No API key has been provided")

    payload = {
        "externalId": "EXM-7847-1229",
        "version": "6.0.0",
        "meta": {
            "version": "6.0.0",
            "openapi": "/public/v2/openapi.json",
            "events": [
                {
                    "event": "platform.commerce.order",
                    "filter": "eq(status,Processing)",
                    "path": "/public/v2/orders",
                    "task": True,
                },
            ],
            "channel": {},
        },
    }

    # TODO: validate identity

    instance_data = _create_instance(settings, payload)
    identity = instance_data.get("channel", {}).get("identity")
    if identity:
        _save_identity(settings.identity_file, identity)

    logger.info("FastAPI extension bootstrap completed for extension %s", settings.extension_id)


def _create_instance(settings, payload) -> dict:
    bootstrap_url = (
        f"{settings.base_url}/public/v1/integration/extensions/{settings.extension_id}/instances"
    )
    response = requests.post(
        bootstrap_url,
        json=payload,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {settings.api_key}",
        },
        timeout=60,
    )
    response.raise_for_status()
    return response.json()


def _load_identity(path: Path) -> dict:
    """Load bootstrap identity from disk.

    Args:
        path: Identity file path.

    Returns:
        Identity payload or empty dictionary.
    """
    if not path.exists():
        return {}
    with path.open(encoding="utf-8") as identity_file:
        return json.load(identity_file)


def _save_identity(path: Path, identity: dict) -> None:
    """Persist bootstrap identity to disk.

    Args:
        path: Identity file path.
        identity: Identity payload.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as identity_file:
        json.dump(identity, identity_file)
