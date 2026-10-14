import datetime as dt
from dataclasses import dataclass, field


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


@dataclass
class FlexDiscountCascade:
    """
    Ranked flexible discount codes a PREVIEW order cascades through, per Adobe line number.

    ``candidates`` holds, per ``extLineItemNumber``, the codes still to try
    (head = the code currently proposed); ``selection`` the code each line
    carried when the preview accepted it; ``rejections`` the codes Adobe
    rejected per line, in order. Lines absent from ``candidates`` carry no
    proposal.
    """

    candidates: dict[int, list[str]] = field(default_factory=dict)
    selection: dict[int, str] = field(default_factory=dict)
    rejections: dict[int, list[str]] = field(default_factory=dict)

    @property
    def remaining_codes(self) -> int:
        """Number of codes still to try across every line."""
        return sum(len(codes) for codes in self.candidates.values())

    def current_code(self, line_number: int) -> str | None:
        """Return the code currently proposed for the line, None when none is left."""
        codes = self.candidates.get(line_number) or []
        return codes[0] if codes else None

    def reject(self, line_number: int, code: str) -> str | None:
        """Record the rejection of the line's proposed code and return the next one, if any."""
        self.rejections.setdefault(line_number, []).append(code)
        codes = self.candidates.get(line_number) or []
        if codes and codes[0] == code:
            codes.pop(0)
        return self.current_code(line_number)


def _wrap_secret(secret: str) -> str:
    first_symbols, last_symbols = secret[:4], secret[-4:]
    return f"{first_symbols}******{last_symbols}"
