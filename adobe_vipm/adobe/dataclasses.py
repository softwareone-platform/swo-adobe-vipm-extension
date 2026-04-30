import datetime as dt
from dataclasses import dataclass

from adobe_vipm.adobe.constants import (
    PriceListCurrency,
    PriceListRegion,
    PriceListType,
)
from adobe_vipm.flows.constants import MarketSegment


@dataclass(frozen=True)
class Authorization:
    """Authorization representation."""

    authorization_uk: str
    authorization_id: str | None
    name: str
    client_id: str
    client_secret: str
    currency: str
    distributor_id: str

    def __repr__(self) -> str:
        """Repr of the authorization."""
        client_id = _wrap_secret(self.client_id)
        secret = _wrap_secret(self.client_secret)

        return (
            f"Authorization("
            f"authorization_uk='{self.authorization_uk}', "
            f"authorization_id='{self.authorization_id}', "
            f"name='{self.name}', "
            f"client_id='{client_id}', "
            f"client_secret='{secret}', "
            f"currency='{self.currency}', "
            f"distributor_id='{self.distributor_id}')"
        )


@dataclass(frozen=True)
class Reseller:
    """Adobe Reseller representation."""

    id: str
    seller_uk: str
    authorization: Authorization
    seller_id: str | None


@dataclass(frozen=True)
class APIToken:
    """Adobe Token representation."""

    token: str
    expires: dt.datetime

    def is_expired(self) -> bool:
        """Is token expired."""
        return self.expires < dt.datetime.now(tz=dt.UTC)


@dataclass(frozen=True)
class Country:
    """Adobe Country representation."""

    code: str
    name: str
    states_or_provinces: list[str]
    currencies: list[str]
    pricelist_region: str
    postal_code_format_regex: str
    provinces_to_code: dict | None = None


@dataclass(frozen=True)
class ReturnableOrderInfo:
    """Adobe Returnable Orders info."""

    order: dict
    line: dict
    quantity: int


@dataclass(frozen=True)
class PriceListFilters:
    """Optional filters for the Fetch Price List API."""

    offer_id: str | None = None
    product_family: str | None = None
    first_order_date: str | None = None
    last_order_date: str | None = None
    discount_code: str | None = None

    def to_dict(self) -> dict:
        """Serialize to the camelCase dict expected by the API, omitting None values."""
        raw = {
            "offerId": self.offer_id,
            "productFamily": self.product_family,
            "firstOrderDate": self.first_order_date,
            "lastOrderDate": self.last_order_date,
            "discountCode": self.discount_code,
        }
        return {key: attr for key, attr in raw.items() if attr is not None}


@dataclass(frozen=True)
class PriceListPayload:
    """Request body for the Fetch Price List API (POST /v3/pricelist)."""

    region: PriceListRegion
    market_segment: MarketSegment
    currency: PriceListCurrency
    price_list_month: str  # YYYYMM format
    price_list_type: PriceListType | None = None
    filters: PriceListFilters | None = None
    include_offer_attributes: list[str] | None = None

    def to_dict(self) -> dict:
        """Serialize to the camelCase dict expected by the API."""
        result = {
            "region": self.region,
            "marketSegment": self.market_segment,
            "currency": self.currency,
            "priceListMonth": self.price_list_month,
        }
        if self.price_list_type is not None:
            result["priceListType"] = self.price_list_type
        if self.filters is not None:
            result["filters"] = self.filters.to_dict()
        if self.include_offer_attributes is not None:
            result["includeOfferAttributes"] = self.include_offer_attributes
        return result


def _wrap_secret(secret: str) -> str:
    first_symbols, last_symbols = secret[:4], secret[-4:]
    return f"{first_symbols}******{last_symbols}"
