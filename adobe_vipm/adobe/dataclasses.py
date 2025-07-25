import datetime as dt
from dataclasses import dataclass


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


def _wrap_secret(secret: str) -> str:
    first_symbols, last_symbols = secret[:4], secret[-4:]
    return f"{first_symbols}******{last_symbols}"
