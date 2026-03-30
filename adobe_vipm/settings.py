import json
import os
from dataclasses import dataclass
from typing import Any, Self, override

from mpt_extension_sdk.errors.runtime import ConfigError
from mpt_extension_sdk.settings.extension import BaseExtensionSettings


@dataclass(frozen=True)
class ExtensionSettings(BaseExtensionSettings):
    """Extension settings."""

    adobe_authorizations_file: str
    adobe_credentials_file: str
    adobe_auth_endpoint_url: str
    adobe_api_base_url: str
    airtable_api_token: str
    airtable_bases: dict
    airtable_pricing_bases: dict
    airtable_sku_mapping_base: str
    aws_ses_credentials: str
    aws_ses_region: str
    due_date_days: int
    email_notifications_enabled: str
    email_notifications_sender: str
    nav_api_base_url: str
    nav_auth_audience: str
    nav_auth_client_id: str
    nav_auth_client_secret: str
    nav_auth_endpoint_url: str
    msteams_webhook_url: str
    order_creation_window_hours: int
    product_ids: str
    product_segment: dict[str, str]
    webhooks_secrets: dict

    @override
    @property
    def required_env_vars(self) -> list[tuple[str, ...]]:
        return [
            (self.product_ids, "Product ids is required (MPT_PRODUCTS_IDS)"),
            (
                self.adobe_authorizations_file,
                "Adobe authorization file is required (EXT_ADOBE_AUTHORIZATIONS_FILE)",
            ),
            (
                self.adobe_credentials_file,
                "Adobe credentials files is required (EXT_ADOBE_CREDENTIALS_FILE)",
            ),
        ]

    @override
    @classmethod
    def load(cls) -> Self:
        return cls(
            adobe_authorizations_file=os.getenv("EXT_ADOBE_AUTHORIZATIONS_FILE", ""),
            adobe_credentials_file=os.getenv("EXT_ADOBE_CREDENTIALS_FILE", ""),
            adobe_auth_endpoint_url=os.getenv("EXT_ADOBE_AUTH_ENDPOINT_URL", ""),
            adobe_api_base_url=os.getenv("EXT_ADOBE_API_BASE_URL", ""),
            airtable_api_token=os.getenv("EXT_AIRTABLE_API_TOKEN", ""),
            airtable_bases=cls._json_load("EXT_AIRTABLE_BASES"),
            airtable_pricing_bases=cls._json_load("EXT_AIRTABLE_PRICING_BASES"),
            airtable_sku_mapping_base=os.getenv("EXT_AIRTABLE_SKU_MAPPING_BASE", ""),
            aws_ses_credentials=os.getenv("EXT_AWS_SES_CREDENTIALS", ""),
            aws_ses_region=os.getenv("EXT_AWS_SES_REGION", ""),
            due_date_days=int(os.getenv("EXT_DUE_DATE_DAYS", "120")),
            email_notifications_sender=os.getenv("EXT_EMAIL_NOTIFICATIONS_SENDER", ""),
            email_notifications_enabled=os.getenv("EXT_EMAIL_NOTIFICATIONS_ENABLED", ""),
            nav_api_base_url=os.getenv("EXT_NAV_API_BASE_URL", ""),
            nav_auth_audience=os.getenv("EXT_NAV_AUTH_AUDIENCE", ""),
            nav_auth_client_id=os.getenv("EXT_NAV_AUTH_CLIENT_ID", ""),
            nav_auth_client_secret=os.getenv("EXT_NAV_AUTH_CLIENT_SECRET", ""),
            nav_auth_endpoint_url=os.getenv("EXT_NAV_AUTH_ENDPOINT_URL", ""),
            msteams_webhook_url=os.getenv("EXT_MSTEAMS_WEBHOOK_URL", ""),
            order_creation_window_hours=int(os.getenv("EXT_ORDER_CREATION_WINDOW_HOURS", "24")),
            product_ids=os.getenv("MPT_PRODUCTS_IDS", ""),
            product_segment=cls._json_load("EXT_PRODUCT_SEGMENT"),
            webhooks_secrets=cls._json_load("EXT_WEBHOOKS_SECRETS"),
        )

    @classmethod
    def _json_load(cls, env_key: str) -> dict[str, Any]:
        raw_value = os.getenv(env_key, "").strip()
        if not raw_value:
            return {}

        try:
            return json.loads(raw_value)
        except json.JSONDecodeError as error:
            raise ConfigError(f"Invalid JSON in {env_key}: {error}") from None
