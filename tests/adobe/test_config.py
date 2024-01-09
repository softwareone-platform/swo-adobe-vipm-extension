import json

from adobe_vipm.adobe.config import Config
from adobe_vipm.adobe.dataclasses import Reseller


def test_properties(mock_adobe_config, adobe_config_file):
    """
    Check the Config properties map to the right value.
    """
    c = Config()
    assert c.api_base_url == adobe_config_file["api_base_url"]
    assert c.auth_endpoint_url == adobe_config_file["authentication_endpoint_url"]
    assert c.api_scopes == ",".join(adobe_config_file["scopes"])


def test_get_default_sku(mock_adobe_config, adobe_config_file):
    """
    Check the lookup of the default SKU based on the order item partial SKU.
    """
    default_sku = adobe_config_file["skus_mapping"][0]["default_sku"]
    c = Config()
    assert c.get_default_sku(default_sku[:9]) == default_sku


def test_get_default_sku_not_found(mock_adobe_config):
    """
    Check that the lookup of the default SKU return None if the item partial
    SKU is not mapped to a default one.
    """
    c = Config()
    assert c.get_default_sku("not-found") is None


def test_get_reseller(mock_adobe_config, adobe_config_file):
    """
    Test the lookup the Reseller object by country.
    """
    reseller_country = adobe_config_file["accounts"][0]["resellers"][0]["country"]
    reseller_id = adobe_config_file["accounts"][0]["resellers"][0]["id"]
    client_id = adobe_config_file["accounts"][0]["client_id"]
    client_secret = adobe_config_file["accounts"][0]["client_secret"]

    c = Config()
    reseller = c.get_reseller(reseller_country)
    assert isinstance(reseller, Reseller)
    assert reseller.id == reseller_id
    assert reseller.credentials.client_id == client_id
    assert reseller.credentials.client_secret == client_secret


def test_get_reseller_not_found(mock_adobe_config):
    """
    Check that the lookup of the reseller returns None if there is
    no reseller for a given country.
    """
    c = Config()
    assert c.get_reseller("IT") is None


def test_load_config(mocker, adobe_config_file, settings):
    settings.EXTENSION_CONFIG["ADOBE_CONFIG_FILE"] = "a-file.json"
    mocker.patch(
        "builtins.open", mocker.mock_open(read_data=json.dumps(adobe_config_file))
    )
    c = Config()
    assert c.config == adobe_config_file
