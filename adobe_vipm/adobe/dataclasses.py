from dataclasses import dataclass
from datetime import datetime
from typing import List, Optional


@dataclass(frozen=True)
class Authorization:
    authorization_uk: str
    authorization_id: Optional[str]
    name: str
    client_id: str
    client_secret: str
    currency: str
    distributor_id: str


@dataclass(frozen=True)
class Reseller:
    id: str
    seller_uk: str
    authorization: Authorization
    seller_id: Optional[str]


@dataclass(frozen=True)
class APIToken:
    token: str
    expires: datetime

    def is_expired(self):
        return self.expires < datetime.now()


@dataclass(frozen=True)
class AdobeProduct:
    sku: str
    name: str
    type: str


@dataclass(frozen=True)
class Country:
    code: str
    name: str
    states_or_provinces: List[str]
    currencies: List[str]
    pricelist_region: str
    postal_code_format_regex: str
