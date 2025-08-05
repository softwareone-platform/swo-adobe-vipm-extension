import json
from importlib.resources import files
from pathlib import Path
from typing import List, MutableMapping, Tuple

from django.conf import settings
from mpt_extension_sdk.mpt_http.utils import find_first

from adobe_vipm.adobe.dataclasses import (
    Authorization,
    Country,
    Reseller,
)
from adobe_vipm.adobe.errors import (
    AuthorizationNotFoundError,
    CountryNotFoundError,
    ResellerNotFoundError,
)
from adobe_vipm.utils import map_by

REQUIRED_API_SCOPES = ("openid", "AdobeID", "read_organizations")


class Config:
    """Adobe Configuration."""

    def __init__(self) -> None:
        self.language_codes: List[str] = []
        self.resellers: MutableMapping[Tuple[Authorization, str], Reseller] = {}
        self.authorizations: MutableMapping[str, Authorization] = {}
        self.countries: MutableMapping[str, Country] = {}
        self._setup()

    @property
    def auth_endpoint_url(self) -> str:
        """
        Adobe auth endpoint URL.

        Returns:
            The endpoint url
        """
        return settings.EXTENSION_CONFIG["ADOBE_AUTH_ENDPOINT_URL"]

    @property
    def api_base_url(self) -> str:
        """
        Adobe API base URL.

        Returns:
            The base url
        """
        return settings.EXTENSION_CONFIG["ADOBE_API_BASE_URL"]

    @property
    def api_scopes(self) -> str:
        """
        Adobe API scopes.

        Returns:
            The scopes joined by ','
        """
        return ",".join(REQUIRED_API_SCOPES)

    @property
    def country_codes(self) -> List[str]:
        """
        Adobe country codes.

        Returns:
            Country codes supported by Adobe
        """
        return list(self.countries.keys())

    def get_authorization(self, auth_id: str) -> Authorization:
        """
        Returns an Authorization based on its identifier.

        Args:
            auth_id: the identifier of the Authorization.

        Raises:
            AuthorizationNotFoundError: if there is no Authorization
                with such id.

        Returns:
            Authorization object identified by the provided id.
        """
        try:
            return self.authorizations[auth_id]
        except KeyError:
            raise AuthorizationNotFoundError(
                f"Authorization with uk/id {auth_id} not found.",
            )

    def get_reseller(self, authorization: Authorization, auth_id: str) -> Reseller:
        """
        Returns a Reseller object given an Authorization and the Reseller identifier.

        Args:
            authorization: The Authorization for looking up the
            reseller.
            auth_id: Identifier of the Reseller to retrieve.

        Raises:
            ResellerNotFoundError: if there is no Reseller with such
            lookup keys.

        Returns:
            The Reseller object.
        """
        try:
            return self.resellers[authorization, auth_id]
        except KeyError:
            raise ResellerNotFoundError(
                f"Reseller not found for authorization {authorization.authorization_uk} "
                f"and uk/id {auth_id}.",
            )

    def reseller_exists(self, authorization: Authorization, auth_id: str) -> bool:
        """
        Returns True if a Reseller with a given Authorization and identifier exists, else otherwise.

        Args:
            authorization: The Authorization object used
                to search for the Reseller.
            auth_id: The id of the Reseller to search for.

        Returns:
            True if it exists False otherwise.
        """
        return (authorization, auth_id) in self.resellers

    def get_country(self, code: str) -> Country:
        """
        Returns a Country object identified by the Country code.

        Args:
            code: The Country code to retrieve the Country
                object.

        Raises:
            CountryNotFoundError: If there is no Country object
                identified by the given Country code.

        Returns:
            The Country object.
        """
        try:
            return self.countries[code]
        except KeyError:
            raise CountryNotFoundError(
                f"Country with code {code} not found.",
            )

    def get_preferred_language(self, country: str) -> str:
        """
        Returns the preferred language code for communications based on the country code.

        Args:
            country: The country code for which search
            for the preferred language code.

        Returns:
           The preferred language code or the English United States if not found.
        """
        return find_first(
            lambda code: code.endswith(f"-{country}"),
            self.language_codes,
            "en-US",
        )

    @classmethod
    def _load_credentials(cls):
        path = Path(settings.EXTENSION_CONFIG["ADOBE_CREDENTIALS_FILE"])
        with path.open(encoding="utf-8") as cred_file:
            return json.load(cred_file)

    @classmethod
    def _load_authorizations(cls):
        path = Path(settings.EXTENSION_CONFIG["ADOBE_AUTHORIZATIONS_FILE"])
        with path.open(encoding="utf-8") as auth_file:
            return json.load(auth_file)

    @classmethod
    def _load_config(cls):
        config_files = files("adobe_vipm").joinpath("adobe_config.json")
        with config_files.open("r", encoding="utf-8") as config_file:
            return json.load(config_file)

    def _setup(self):
        authorizations_data = self._load_authorizations()
        credentials_map = map_by("authorization_uk", self._load_credentials())

        for authorization_data in authorizations_data["authorizations"]:
            authorization = self._create_authorization(authorization_data, credentials_map)
            self.authorizations[authorization_data["authorization_uk"]] = authorization

            if authorization.authorization_id:  # pragma: no branch
                self.authorizations[authorization.authorization_id] = authorization

            self._setup_resellers(authorization, authorization_data)

        self._setup_countries(self._load_config())

    def _setup_resellers(self, authorization: Authorization, authorization_data: dict):
        for reseller_data in authorization_data["resellers"]:
            seller_uk = reseller_data["seller_uk"]
            seller_id = reseller_data.get("seller_id")
            reseller = Reseller(
                id=reseller_data["id"],
                seller_uk=seller_uk,
                authorization=authorization,
                seller_id=seller_id,
            )
            self.resellers[authorization, seller_uk] = reseller

            if seller_id:  # pragma: no branch
                self.resellers[authorization, seller_id] = reseller

    def _setup_countries(self, config: dict):
        self.language_codes = config["language_codes"]
        for country in config["countries"]:
            self.countries[country["code"]] = Country(**country)

    def _create_authorization(
        self, authorization_data: dict, credentials_map: dict
    ) -> Authorization:
        auth_uk = authorization_data["authorization_uk"]
        return Authorization(
            authorization_uk=auth_uk,
            authorization_id=authorization_data.get("authorization_id"),
            name=credentials_map[auth_uk]["name"],
            client_id=credentials_map[auth_uk]["client_id"],
            client_secret=credentials_map[auth_uk]["client_secret"],
            currency=authorization_data["currency"],
            distributor_id=authorization_data["distributor_id"],
        )


_CONFIG = None


def get_config() -> Config:
    """Returns global Adobe configuration."""
    global _CONFIG  # noqa: PLW0603 WPS420
    if not _CONFIG:
        _CONFIG = Config()
    return _CONFIG
