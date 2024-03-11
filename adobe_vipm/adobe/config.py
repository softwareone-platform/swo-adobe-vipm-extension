import json
from importlib.resources import files
from typing import List, MutableMapping

from django.conf import settings

from adobe_vipm.adobe.dataclasses import (
    AdobeProduct,
    Country,
    Credentials,
    Distributor,
    Reseller,
)
from adobe_vipm.adobe.errors import (
    AdobeProductNotFoundError,
    CountryNotFoundError,
    DistributorNotFoundError,
    ResellerNotFoundError,
)


class Config:
    REQUIRED_API_SCOPES = ["openid", "AdobeID", "read_organizations"]

    def __init__(self) -> None:
        self.credentials = self._load_credentials()
        self.config = self._load_config()
        self.resellers: MutableMapping[str, Reseller] = {}
        self.skus_mapping: MutableMapping[str, AdobeProduct] = {}
        self.distributors: MutableMapping[str, Distributor] = {}
        self.countries: MutableMapping[str, Country] = {}
        self._parse_config()

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
    def language_codes(self) -> List[str]:
        return self.config["language_codes"]

    @property
    def country_codes(self) -> List[str]:
        return list(self.countries.keys())

    def get_reseller(self, country: str) -> Reseller:
        try:
            return self.resellers[country]
        except KeyError:
            raise ResellerNotFoundError(
                f"Reseller not found for country {country}.",
            )

    def get_distributor(self, country: str) -> Distributor:
        try:
            return self.distributors[country]
        except KeyError:
            raise DistributorNotFoundError(
                f"Distributor not found for country {country}.",
            )

    def get_adobe_product(self, vendor_external_id: str) -> AdobeProduct:
        try:
            return self.skus_mapping[vendor_external_id]
        except KeyError:
            raise AdobeProductNotFoundError(f"AdobeProduct with id {vendor_external_id} not found.")

    def get_country(self, code: str) -> Country:
        try:
            return self.countries[code]
        except KeyError:
            raise CountryNotFoundError(
                f"Country with code {code} not found.",
            )

    @classmethod
    def _load_credentials(self):
        with open(settings.EXTENSION_CONFIG["ADOBE_CREDENTIALS_FILE"]) as f:
            return json.load(f)

    @classmethod
    def _load_config(self):
        with files("adobe_vipm").joinpath("adobe_config.json").open("r", encoding="utf-8") as f:
            return json.load(f)

    def _parse_config(self):
        credentials_map = {cred["country"]: cred for cred in self.credentials}
        for account in self.config["accounts"]:
            country = account["country"]
            credentials = Credentials(
                client_id=credentials_map[country]["client_id"],
                client_secret=credentials_map[country]["client_secret"],
                country=country,
                distributor_id=account["distributor_id"],
            )
            distributor = Distributor(
                id=account["distributor_id"],
                country=country,
                pricelist_region=account["pricelist_region"],
                currency=account["currency"],
                credentials=credentials,
            )
            self.distributors[country] = distributor
            for reseller in account["resellers"]:
                country = reseller["country"]
                self.resellers[country] = Reseller(
                    id=reseller["id"],
                    country=country,
                    distributor=distributor,
                )
        for product in self.config["skus_mapping"]:
            self.skus_mapping[product["vendor_external_id"]] = AdobeProduct(
                sku=product["sku"],
                name=product["name"],
                type=product["type"],
            )
        for country in self.config["countries"]:
            self.countries[country["code"]] = Country(**country)


_CONFIG = None


def get_config():
    global _CONFIG
    if not _CONFIG:
        _CONFIG = Config()
    return _CONFIG
