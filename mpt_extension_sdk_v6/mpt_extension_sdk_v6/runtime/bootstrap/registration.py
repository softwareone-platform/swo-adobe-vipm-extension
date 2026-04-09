import logging
from dataclasses import dataclass
from typing import Any

from mpt_extension_sdk_v6.runtime.bootstrap.client import register_extension_instance
from mpt_extension_sdk_v6.runtime.bootstrap.identity import load_identity, save_identity
from mpt_extension_sdk_v6.settings.runtime import RuntimeSettings

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class RegistrationResult:
    """Registration result payload."""

    instance: dict[str, Any]


def register_instance(settings: RuntimeSettings) -> RegistrationResult:
    """Register an extension instance and persist identity if provided."""
    payload: dict[str, Any] = {
        "externalId": settings.external_id,
        "version": settings.meta_config.version,
        "meta": settings.meta_config.model_dump(by_alias=True),
    }

    logger.info(
        "Registering extension instance extension_id=%s external_id=%s events=%s",
        settings.extension_id,
        settings.external_id,
        len(payload["meta"].get("events", [])),
    )
    logger.info("Events registered: %s", payload["meta"]["events"])

    existing_identity = load_identity(settings.identity_file_path)
    identity_extension = str(existing_identity.get("mrok", {}).get("extension", ""))
    if not existing_identity or identity_extension.lower() != settings.extension_id.lower():
        payload["channel"] = {}

    instance_payload = register_extension_instance(
        settings.base_url, settings.extension_id, settings.ext_api_key, payload
    )

    identity = instance_payload.get("channel", {}).get("identity")
    if isinstance(identity, dict) and identity:
        save_identity(settings.identity_file_path, identity)

    logger.info("Extension registration completed extension_id=%s", settings.extension_id)
    return RegistrationResult(instance=instance_payload)
