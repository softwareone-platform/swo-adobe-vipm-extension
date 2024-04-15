import json
from importlib.resources import files
from typing import List, MutableMapping, Tuple

from django.conf import settings

from adobe_vipm.adobe.dataclasses import (
    AdobeProduct,
    Authorization,
    Country,
    Reseller,
)
from adobe_vipm.adobe.errors import (
    AdobeProductNotFoundError,
    AuthorizationNotFoundError,
    CountryNotFoundError,
    ResellerNotFoundError,
)


class Config:
    REQUIRED_API_SCOPES = ["openid", "AdobeID", "read_organizations"]

    def __init__(self) -> None:
        self.language_codes: List[str] = []
        self.resellers: MutableMapping[Tuple[Authorization, str], Reseller] = {}
        self.authorizations: MutableMapping[str, Authorization] = {}
        self.skus_mapping: MutableMapping[str, AdobeProduct] = {}
        self.countries: MutableMapping[str, Country] = {}
        self._setup()

    @property
    def auth_endpoint_url(self) -> str:
        return settings.EXTENSION_CONFIG["ADOBE_AUTH_ENDPOINT_URL"]

    @property
    def api_base_url(self) -> str:
        return settings.EXTENSION_CONFIG["ADOBE_API_BASE_URL"]

    @property
    def api_scopes(self) -> str:
        return ",".join(self.REQUIRED_API_SCOPES)

    @property
    def country_codes(self) -> List[str]:
        return list(self.countries.keys())

    def get_authorization(self, id: str) -> Authorization:
        """
        _summary_

        Args:
            id (str): _description_

        Raises:
            AuthorizationNotFoundError: _description_

        Returns:
            Authorization: _description_
        """
        try:
            return self.authorizations[id]
        except KeyError:
            raise AuthorizationNotFoundError(
                f"Authorization with uk/id {id} not found.",
            )

    def get_reseller(self, authorization: Authorization, id: str) -> Reseller:
        """
        _summary_

        Args:
            authorization (Authorization): _description_
            id (str): _description_

        Raises:
            ResellerNotFoundError: _description_

        Returns:
            Reseller: _description_
        """
        try:
            return self.resellers[(authorization, id)]
        except KeyError:
            raise ResellerNotFoundError(
                f"Reseller not found for authorization {authorization.authorization_uk} "
                f"and uk/id {id}.",
            )

    def reseller_exists(self, authorization: Authorization, id: str) -> bool:
        """
        _summary_

        Args:
            authorization (Authorization): _description_
            id (str): _description_

        Returns:
            bool: _description_
        """
        return (authorization, id) in self.resellers

    def get_adobe_product(self, vendor_external_id: str) -> AdobeProduct:
        """
        _summary_

        Args:
            vendor_external_id (str): _description_

        Raises:
            AdobeProductNotFoundError: _description_

        Returns:
            AdobeProduct: _description_
        """
        try:
            return self.skus_mapping[vendor_external_id]
        except KeyError:
            raise AdobeProductNotFoundError(
                f"AdobeProduct with id {vendor_external_id} not found."
            )

    def get_country(self, code: str) -> Country:
        """
        _summary_

        Args:
            code (str): _description_

        Raises:
            CountryNotFoundError: _description_

        Returns:
            Country: _description_
        """
        try:
            return self.countries[code]
        except KeyError:
            raise CountryNotFoundError(
                f"Country with code {code} not found.",
            )

    @classmethod
    def _load_credentials(cls):
        with open(settings.EXTENSION_CONFIG["ADOBE_CREDENTIALS_FILE"]) as f:
            return json.load(f)

    @classmethod
    def _load_authorizations(cls):
        with open(settings.EXTENSION_CONFIG["ADOBE_AUTHORIZATIONS_FILE"]) as f:
            return json.load(f)

    @classmethod
    def _load_config(cls):
        with files("adobe_vipm").joinpath("adobe_config.json").open(
            "r", encoding="utf-8"
        ) as f:
            return json.load(f)

    def _setup(self):
        config_data = self._load_config()
        credentials_data = self._load_credentials()
        authorizations_data = self._load_authorizations()

        credentials_map = {cred["authorization_uk"]: cred for cred in credentials_data}
        for authorization_data in authorizations_data["authorizations"]:
            auth_uk = authorization_data["authorization_uk"]
            authorization = Authorization(
                authorization_uk=auth_uk,
                authorization_id=authorization_data.get("authorization_id"),
                name=credentials_map[auth_uk]["name"],
                client_id=credentials_map[auth_uk]["client_id"],
                client_secret=credentials_map[auth_uk]["client_secret"],
                currency=authorization_data["currency"],
                distributor_id=authorization_data["distributor_id"],
            )
            self.authorizations[auth_uk] = authorization

            if authorization.authorization_id:
                self.authorizations[authorization.authorization_id] = authorization

            for reseller_data in authorization_data["resellers"]:
                seller_uk = reseller_data["seller_uk"]
                seller_id = reseller_data.get("seller_id")
                reseller = Reseller(
                    id=reseller_data["id"],
                    seller_uk=seller_uk,
                    authorization=authorization,
                    seller_id=seller_id,
                )
                self.resellers[(authorization, seller_uk)] = reseller

            if seller_id:
                self.resellers[(authorization, seller_id)] = reseller

        for product in config_data["skus_mapping"]:
            self.skus_mapping[product["vendor_external_id"]] = AdobeProduct(
                sku=product["sku"],
                name=product["name"],
                type=product["type"],
            )
        self.language_codes = config_data["language_codes"]
        for country in config_data["countries"]:
            self.countries[country["code"]] = Country(**country)


_CONFIG = None


def get_config():
    global _CONFIG
    if not _CONFIG:
        _CONFIG = Config()
    return _CONFIG
