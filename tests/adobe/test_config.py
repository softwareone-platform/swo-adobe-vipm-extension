import json

import pytest

from adobe_vipm.adobe.config import Config
from adobe_vipm.adobe.dataclasses import AdobeProduct, Credentials, Reseller
from adobe_vipm.adobe.errors import (
    AdobeProductNotFoundError,
    CredentialsNotFoundError,
    ResellerNotFoundError,
)


def test_properties(mock_adobe_config, adobe_config_file):
    """
    Check the Config properties map to the right value.
    """
    c = Config()
    assert c.api_base_url == adobe_config_file["api_base_url"]
    assert c.auth_endpoint_url == adobe_config_file["authentication_endpoint_url"]
    assert c.api_scopes == ",".join(adobe_config_file["scopes"])


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
    Check that the lookup of the reseller raises `ResellerNotFoundError`
    if there is no reseller for a given country.
    """
    c = Config()
    with pytest.raises(ResellerNotFoundError) as cv:
        assert c.get_reseller("IT")

    assert str(cv.value) == "Reseller not found for country IT."


def test_get_credentials(mock_adobe_config, adobe_config_file):
    """
    Test the lookup the Credentials object by region.
    """
    credentials_region = adobe_config_file["accounts"][0]["region"]
    client_id = adobe_config_file["accounts"][0]["client_id"]
    client_secret = adobe_config_file["accounts"][0]["client_secret"]
    distributor_id = adobe_config_file["accounts"][0]["distributor_id"]

    c = Config()
    credentials = c.get_credentials(credentials_region)

    assert isinstance(credentials, Credentials)
    assert credentials.client_id == client_id
    assert credentials.client_secret == client_secret
    assert credentials.region == credentials_region
    assert credentials.distributor_id == distributor_id


def test_get_credentials_not_found(mock_adobe_config):
    """
    Check that the lookup of the credentials raises `CredentialsNotFound`
    if there is no credentials for a given region.
    """
    c = Config()
    with pytest.raises(CredentialsNotFoundError) as cv:
        assert c.get_credentials("MX")

    assert str(cv.value) == "Credentials not found for region MX."


def test_get_adobe_product(mock_adobe_config, adobe_config_file):
    """
    Test the lookup the Product object by product item identifier.
    """
    product_item_id = adobe_config_file["skus_mapping"][0]["product_item_id"]
    name = adobe_config_file["skus_mapping"][0]["name"]
    sku = adobe_config_file["skus_mapping"][0]["sku"]
    type = adobe_config_file["skus_mapping"][0]["type"]

    c = Config()
    product = c.get_adobe_product(product_item_id)
    assert isinstance(product, AdobeProduct)
    assert product.sku == sku
    assert product.name == name
    assert product.type == type


def test_get_adobe_product_not_found(mock_adobe_config):
    """
    Check that the lookup of the product raises `ProductNotFound`
    if there is no product for a given product item id.
    """
    c = Config()
    with pytest.raises(AdobeProductNotFoundError) as cv:
        assert c.get_adobe_product("not-found")

    assert str(cv.value) == "AdobeProduct with id not-found not found."


def test_load_config(mocker, adobe_config_file, settings):
    settings.EXTENSION_CONFIG["ADOBE_CONFIG_FILE"] = "a-file.json"
    mocker.patch("builtins.open", mocker.mock_open(read_data=json.dumps(adobe_config_file)))
    c = Config()
    assert c.config == adobe_config_file
