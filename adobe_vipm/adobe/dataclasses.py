from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class Credentials:
    client_id: str
    client_secret: str
    region: str


@dataclass(frozen=True)
class Reseller:
    id: str
    country: str
    credentials: Credentials


@dataclass(frozen=True)
class APIToken:
    token: str
    expires: datetime

    def is_expired(self):
        return self.expires < datetime.now()
