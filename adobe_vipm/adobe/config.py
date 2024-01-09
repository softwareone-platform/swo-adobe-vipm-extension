import json

from django.conf import settings

from adobe_vipm.adobe.dataclasses import Credentials, Reseller


class Config:
    def __init__(self):
        self.config = self._load_config()
        self.resellers = self._load_resellers()
        self.skus_mapping = {
            sku_info["product_item_id"]: sku_info["default_sku"]
            for sku_info in self.config["skus_mapping"]
        }

    @property
    def auth_endpoint_url(self) -> str:
        return self.config["authentication_endpoint_url"]

    @property
    def api_base_url(self) -> str:
        return self.config["api_base_url"]

    @property
    def api_scopes(self) -> str:
        return ",".join(self.config["scopes"])

    def get_default_sku(self, product_item_id) -> str:
        return self.skus_mapping.get(product_item_id)

    def get_reseller(self, country) -> Reseller:
        return self.resellers.get(country)

    def _load_config(self):
        with open(settings.EXTENSION_CONFIG["ADOBE_CONFIG_FILE"], "r") as f:
            return json.load(f)

    def _load_resellers(self):
        resellers = {}
        for account in self.config["accounts"]:
            credentials = Credentials(
                client_id=account["client_id"],
                client_secret=account["client_secret"],
                region=account["region"],
            )
            for reseller in account["resellers"]:
                country = reseller["country"]
                resellers[country] = Reseller(
                    id=reseller["id"],
                    country=country,
                    credentials=credentials,
                )
        return resellers
