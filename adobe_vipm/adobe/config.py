import json
from typing import MutableMapping

from django.conf import settings

from adobe_vipm.adobe.dataclasses import (
    AdobeProduct,
    Credentials,
    Distributor,
    Reseller,
)
from adobe_vipm.adobe.errors import (
    AdobeProductNotFoundError,
    DistributorNotFoundError,
    ResellerNotFoundError,
)


class Config:
    def __init__(self) -> None:
        self.config = self._load_config()
        self.resellers: MutableMapping[str, Reseller] = {}
        self.skus_mapping: MutableMapping[str, AdobeProduct] = {}
        self.distributors: MutableMapping[str, Distributor] = {}
        self._parse_config()

    @property
    def auth_endpoint_url(self) -> str:
        return self.config["authentication_endpoint_url"]

    @property
    def api_base_url(self) -> str:
        return self.config["api_base_url"]

    @property
    def api_scopes(self) -> str:
        return ",".join(self.config["scopes"])

    def get_reseller(self, country: str) -> Reseller:
        try:
            return self.resellers[country]
        except KeyError:
            raise ResellerNotFoundError(
                f"Reseller not found for country {country}.",
            )

    def get_distributor(self, region: str) -> Distributor:
        try:
            return self.distributors[region]
        except KeyError:
            raise DistributorNotFoundError(
                f"Distributor not found for region {region}.",
            )

    def get_adobe_product(self, product_item_id: str) -> AdobeProduct:
        try:
            return self.skus_mapping[product_item_id]
        except KeyError:
            raise AdobeProductNotFoundError(f"AdobeProduct with id {product_item_id} not found.")

    def _load_config(self):
        with open(settings.EXTENSION_CONFIG["ADOBE_CONFIG_FILE"], "r") as f:
            return json.load(f)

    def _parse_config(self):
        for account in self.config["accounts"]:
            credentials = Credentials(
                client_id=account["client_id"],
                client_secret=account["client_secret"],
                region=account["region"],
                distributor_id=account["distributor_id"],
            )
            distributor = Distributor(
                id=account["distributor_id"],
                region=account["region"],
                currency=account["currency"],
                credentials=credentials,
            )
            self.distributors[account["region"]] = distributor
            for reseller in account["resellers"]:
                country = reseller["country"]
                self.resellers[country] = Reseller(
                    id=reseller["id"],
                    country=country,
                    distributor=distributor,
                )
        for product in self.config["skus_mapping"]:
            self.skus_mapping[product["product_item_id"]] = AdobeProduct(
                sku=product["sku"],
                name=product["name"],
                type=product["type"],
            )
