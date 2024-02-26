import json

import pytest

from adobe_vipm.adobe.config import Config
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


def test_properties(mock_adobe_config, adobe_config_file):
    """
    Check the Config properties map to the right value.
    """
    c = Config()
    assert c.api_base_url == adobe_config_file["api_base_url"]
    assert c.auth_endpoint_url == adobe_config_file["authentication_endpoint_url"]
    assert c.api_scopes == ",".join(adobe_config_file["scopes"])
    assert c.language_codes == ["en-US"]


def test_get_reseller(mock_adobe_config, adobe_config_file):
    """
    Test the lookup the Reseller object by country.
    """
    reseller_country = adobe_config_file["accounts"][0]["resellers"][0]["country"]
    reseller_id = adobe_config_file["accounts"][0]["resellers"][0]["id"]
    client_id = adobe_config_file["accounts"][0]["client_id"]
    client_secret = adobe_config_file["accounts"][0]["client_secret"]
    distributor_id = adobe_config_file["accounts"][0]["distributor_id"]
    currency = adobe_config_file["accounts"][0]["currency"]
    region = adobe_config_file["accounts"][0]["region"]

    c = Config()
    reseller = c.get_reseller(reseller_country)
    assert isinstance(reseller, Reseller)
    assert reseller.id == reseller_id
    assert isinstance(reseller.distributor, Distributor)
    assert reseller.distributor.id == distributor_id
    assert reseller.distributor.currency == currency
    assert reseller.distributor.region == region
    assert isinstance(reseller.distributor.credentials, Credentials)
    assert reseller.distributor.credentials.client_id == client_id
    assert reseller.distributor.credentials.client_secret == client_secret


def test_get_reseller_not_found(mock_adobe_config):
    """
    Check that the lookup of the reseller raises `ResellerNotFoundError`
    if there is no reseller for a given country.
    """
    c = Config()
    with pytest.raises(ResellerNotFoundError) as cv:
        assert c.get_reseller("IT")

    assert str(cv.value) == "Reseller not found for country IT."


def test_get_distributor(mock_adobe_config, adobe_config_file):
    """
    Test the lookup the Distributor object by region.
    """
    region = adobe_config_file["accounts"][0]["region"]
    client_id = adobe_config_file["accounts"][0]["client_id"]
    client_secret = adobe_config_file["accounts"][0]["client_secret"]
    distributor_id = adobe_config_file["accounts"][0]["distributor_id"]
    currency = adobe_config_file["accounts"][0]["currency"]

    c = Config()
    distributor = c.get_distributor(region)

    assert isinstance(distributor, Distributor)
    assert distributor.id == distributor_id
    assert distributor.region == region
    assert distributor.currency == currency
    assert isinstance(distributor.credentials, Credentials)
    assert distributor.credentials.client_id == client_id
    assert distributor.credentials.client_secret == client_secret


def test_get_distributor_not_found(mock_adobe_config):
    """
    Check that the lookup of the Distributor raises `DistributorNotFound`
    if there is no Distributor for a given region.
    """
    c = Config()
    with pytest.raises(DistributorNotFoundError) as cv:
        assert c.get_distributor("MX")

    assert str(cv.value) == "Distributor not found for pricelist region MX."


def test_get_adobe_product(mock_adobe_config, adobe_config_file):
    """
    Test the lookup the Product object by product item identifier.
    """
    vendor_external_id = adobe_config_file["skus_mapping"][0]["vendor_external_id"]
    name = adobe_config_file["skus_mapping"][0]["name"]
    sku = adobe_config_file["skus_mapping"][0]["sku"]
    type = adobe_config_file["skus_mapping"][0]["type"]

    c = Config()
    product = c.get_adobe_product(vendor_external_id)
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


def test_get_country(mock_adobe_config, adobe_config_file):
    """
    Test the lookup the Country object by country code (ISO 3166-2).
    """

    c = Config()
    country = c.get_country("US")
    assert isinstance(country, Country)
    assert country.code == "US"
    assert country.currencies == ["USD"]
    assert country.name == "United States"
    assert len(country.states_or_provinces) == 55
    assert country.pricelist_region == "NA"
    assert country.postal_code_format_regex == "^[\\d]{5}(?:-[\\d]{4})?$"


def test_get_country_not_found(mock_adobe_config):
    """
    Check that the lookup of the country raises `CountryNotFoundError`
    if there is no country for a given country code (ISO 3166-2).
    """
    c = Config()
    with pytest.raises(CountryNotFoundError) as cv:
        assert c.get_country("not-found")

    assert str(cv.value) == "Country with code not-found not found."


def test_load_config(mocker, adobe_config_file, settings):
    settings.EXTENSION_CONFIG["ADOBE_CONFIG_FILE"] = "a-file.json"
    mocker.patch("builtins.open", mocker.mock_open(read_data=json.dumps(adobe_config_file)))
    c = Config()
    assert c.config == adobe_config_file
