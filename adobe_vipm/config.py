import json
import os
from dataclasses import dataclass, field


@dataclass(frozen=True)
class Settings:
    """Temporary class to handle Django settings."""

    EXTENSION_CONFIG: dict = field(
        default_factory=lambda: {
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
    MPT_PRODUCTS_IDS: list = field(
        default_factory=lambda: os.getenv("MPT_PRODUCTS_IDS", "").split(",")
    )
    MPT_TOOL_STORAGE_TYPE: str = os.getenv("MPT_TOOL_STORAGE_TYPE")
    MPT_TOOL_STORAGE_AIRTABLE_API_KEY: str = os.getenv("MPT_TOOL_STORAGE_AIRTABLE_API_KEY")
    MPT_TOOL_STORAGE_AIRTABLE_TABLE_NAME: str = os.getenv("MPT_TOOL_STORAGE_AIRTABLE_TABLE_NAME")
    MPT_TOOL_STORAGE_AIRTABLE_BASE_ID: str = os.getenv("MPT_TOOL_STORAGE_AIRTABLE_BASE_ID")
