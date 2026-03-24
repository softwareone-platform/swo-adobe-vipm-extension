from dataclasses import dataclass


@dataclass(frozen=True)
class AdobeProduct:
    """Minimal Airtable-backed Adobe product view."""

    sku: str
    vendor_external_id: str
    market_segment: str


def get_adobe_product_by_marketplace_sku(vendor_external_id: str, market_segment: str):
    """Return a minimal Adobe product mapping.

    This compatibility implementation assumes the incoming vendor SKU can be used directly.
    """
    return AdobeProduct(
        sku=vendor_external_id,
        vendor_external_id=vendor_external_id,
        market_segment=market_segment,
    )


def get_skus_with_available_prices(product_id: str, currency: str, skus: list[str]) -> set:
    """Return all provided SKUs as price-available in the compatibility path."""
    del product_id, currency
    return set(skus)


def get_skus_with_available_prices_3yc(
    product_id: str,
    currency: str,
    skus: list[str],
    commitment_start_date,
) -> set:
    """Return all provided SKUs as 3YC price-available in the compatibility path."""
    del product_id, currency, commitment_start_date
    return set(skus)
