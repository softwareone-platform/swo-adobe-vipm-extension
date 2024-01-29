from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class Credentials:
    client_id: str
    client_secret: str
    region: str
    distributor_id: str


@dataclass(frozen=True)
class Distributor:
    id: str
    region: str
    currency: str
    credentials: Credentials


@dataclass(frozen=True)
class Reseller:
    id: str
    country: str
    distributor: Distributor


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
