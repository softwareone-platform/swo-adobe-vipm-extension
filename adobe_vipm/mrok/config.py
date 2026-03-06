import json
import os
from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class RuntimeSettings:
    """Runtime settings loaded from environment variables."""

    webhooks_secrets: dict[str, str]
    extension_id: str
    base_url: str
    api_key: str
    identity_file: Path


def load_runtime_settings() -> RuntimeSettings:
    """Load runtime settings from environment variables.

    Returns:
        Runtime settings instance.
    """
    base_url = os.getenv("MPT_API_BASE_URL", "http://localhost:8081")
    api_key = os.getenv("MPT_API_TOKEN", "")

    return RuntimeSettings(
        webhooks_secrets=_load_json(os.getenv("EXT_WEBHOOKS_SECRETS", ""), {}),
        extension_id=os.getenv("MPT_EXTENSION_ID", "EXT-7847-1229"),
        base_url=base_url,
        api_key=api_key,
        identity_file=Path(
            os.getenv("MPT_EXTENSION_IDENTITY_FILE", str(Path.cwd() / "identity.json")),
        ),
    )


def _load_json(obj_value: str, default: dict[str, str]) -> dict[str, str]:
    """Load JSON object from environment variable content.

    Args:
        obj_value: JSON encoded object value.
        default: Default dictionary used for empty values.

    Returns:
        Parsed dictionary value.
    """
    if not obj_value:
        return default
    loaded = json.loads(obj_value)
    if not isinstance(loaded, dict):
        return default
    return {str(key): str(element) for key, element in loaded.items()}


@dataclass(frozen=True)
class Settings:
    """Temporal class to handle django settings."""

    EXTENSION_CONFIG: dict = field(
        default_factory={
            "ADOBE_AUTHORIZATIONS_FILE": os.getenv("EXT_ADOBE_AUTHORIZATIONS_FILE"),
            "ADOBE_CREDENTIALS_FILE": os.getenv("EXT_ADOBE_CREDENTIALS_FILE"),
            "ADOBE_AUTH_ENDPOINT_URL": os.getenv("EXT_ADOBE_AUTH_ENDPOINT_URL"),
            "ADOBE_API_BASE_URL": os.getenv("EXT_ADOBE_API_BASE_URL"),
            "AIRTABLE_API_TOKEN": os.getenv("EXT_AIRTABLE_API_TOKEN"),
            "AIRTABLE_BASES": json.loads(os.getenv("EXT_AIRTABLE_BASES", "{}")),
            "AIRTABLE_PRICING_BASES": json.loads(os.getenv("EXT_AIRTABLE_PRICING_BASES", "{}")),
            "AIRTABLE_SKU_MAPPING_BASE": os.getenv("EXT_AIRTABLE_SKU_MAPPING_BASE"),
            "AWS_SES_CREDENTIALS": os.getenv("EXT_AWS_SES_CREDENTIALS"),
            "AWS_SES_REGION": os.getenv("EXT_AWS_SES_REGION"),
            "DUE_DATE_DAYS": 0,
            "EMAIL_NOTIFICATIONS_SENDER": os.getenv("EXT_EMAIL_NOTIFICATIONS_SENDER"),
            "EMAIL_NOTIFICATIONS_ENABLED": os.getenv("EXT_EMAIL_NOTIFICATIONS_ENABLED"),
            "NAV_API_BASE_URL": os.getenv("EXT_NAV_API_BASE_URL"),
            "NAV_AUTH_AUDIENCE": os.getenv("EXT_NAV_AUTH_AUDIENCE"),
            "NAV_AUTH_CLIENT_ID": os.getenv("EXT_NAV_AUTH_CLIENT_ID"),
            "NAV_AUTH_CLIENT_SECRET": os.getenv("EXT_NAV_AUTH_CLIENT_SECRET"),
            "NAV_AUTH_ENDPOINT_URL": os.getenv("EXT_NAV_AUTH_ENDPOINT_URL"),
            "MSTEAMS_WEBHOOK_URL": os.getenv("EXT_MSTEAMS_WEBHOOK_URL"),
            "PRODUCT_SEGMENT": json.loads(os.getenv("EXT_PRODUCT_SEGMENT", "{}")),
            "WEBHOOKS_SECRETS": json.loads(os.getenv("EXT_WEBHOOKS_SECRETS", "{}")),
        }
    )
    MPT_API_BASE_URL: str = os.getenv("MPT_API_BASE_URL")
    MPT_API_TOKEN: str = os.getenv("MPT_API_TOKEN")
    MPT_API_TOKEN_OPERATIONS: str = os.getenv("MPT_API_TOKEN_OPERATIONS")
    MPT_PORTAL_BASE_URL: str = os.getenv("MPT_PORTAL_BASE_URL")
    MPT_PRODUCTS_IDS: list = field(default_factory=os.getenv("MPT_PRODUCTS_IDS", "").split(","))
    MPT_TOOL_STORAGE_TYPE: str = os.getenv("MPT_TOOL_STORAGE_TYPE")
    MPT_TOOL_STORAGE_AIRTABLE_API_KEY: str = os.getenv("MPT_TOOL_STORAGE_AIRTABLE_API_KEY")
    MPT_TOOL_STORAGE_AIRTABLE_TABLE_NAME: str = os.getenv("MPT_TOOL_STORAGE_AIRTABLE_TABLE_NAME")
    MPT_TOOL_STORAGE_AIRTABLE_BASE_ID: str = os.getenv("MPT_TOOL_STORAGE_AIRTABLE_BASE_ID")
    OTEL_SERVICE_NAME: str = os.getenv("OTEL_SERVICE_NAME")


settings = Settings()
