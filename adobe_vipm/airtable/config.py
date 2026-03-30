import json
import os
from dataclasses import dataclass
from functools import lru_cache
from typing import Any


@dataclass(frozen=True)
class Config:
    """Airtable config."""

    @property
    def api_key(self) -> str:
        """Airtable API key."""
        return os.getenv("EXT_AIRTABLE_API_TOKEN", "")

    @property
    def bases(self) -> dict[str, Any]:
        """Base IDs for each product."""
        return json.loads(os.getenv("EXT_AIRTABLE_BASES", ""))

    @property
    def pricing_bases(self) -> dict[str, Any]:
        """Pricing base IDs for each product."""
        return json.loads(os.getenv("EXT_AIRTABLE_PRICING_BASES", "{}"))

    @property
    def sku_mapping_base(self) -> str:
        """Base ID for the SKU mapping table."""
        return os.getenv("EXT_AIRTABLE_SKU_MAPPING_BASE", "")

    def get_base_id(self, product_id: str) -> str:
        """Base ID for a product."""
        return self.bases[product_id]

    def get_pricing_base_id(self, product_id: str) -> str:
        """Pricing base ID for a product."""
        return self.pricing_bases[product_id]


@lru_cache
def get_config() -> Config:
    """Airtable config."""
    return Config()
