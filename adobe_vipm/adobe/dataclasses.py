from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class Authorization:
    authorization_uk: str
    authorization_id: str | None
    name: str
    client_id: str
    client_secret: str
    currency: str
    distributor_id: str

    def __repr__(self) -> str:
        return (
            f"Authorization(authorization_uk='{self.authorization_uk}', "
            f"authorization_id='{self.authorization_id}', "
            f"name='{self.name}', "
            f"client_id='{self.client_id[0:4]}******{self.client_id[-4:]}', "
            f"client_secret='{self.client_secret[0:4]}******{self.client_secret[-4:]}', "
            f"currency='{self.currency}', "
            f"distributor_id='{self.distributor_id}')"
        )


@dataclass(frozen=True)
class Reseller:
    id: str
    seller_uk: str
    authorization: Authorization
    seller_id: str | None


@dataclass(frozen=True)
class APIToken:
    token: str
    expires: datetime

    def is_expired(self):
        return self.expires < datetime.now()


@dataclass(frozen=True)
class Country:
    code: str
    name: str
    states_or_provinces: list[str]
    currencies: list[str]
    pricelist_region: str
    postal_code_format_regex: str
    provinces_to_code: dict | None = None


@dataclass(frozen=True)
class ReturnableOrderInfo:
    order: dict
    line: dict
    quantity: int
