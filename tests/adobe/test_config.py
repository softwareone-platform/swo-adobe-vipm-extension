import json

import pytest

from adobe_vipm.adobe.config import Config
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


def test_properties(mock_adobe_config, adobe_config_file, settings):
    """
    Check the Config properties map to the right value.
    """
    c = Config()
    assert c.api_base_url == settings.EXTENSION_CONFIG["ADOBE_API_BASE_URL"]
    assert c.auth_endpoint_url == settings.EXTENSION_CONFIG["ADOBE_AUTH_ENDPOINT_URL"]
    assert c.api_scopes == ",".join(Config.REQUIRED_API_SCOPES)
    assert c.language_codes == ["en-US"]


def test_get_reseller(mock_adobe_config, adobe_credentials_file, adobe_authorizations_file):
    """
    Test the lookup the Reseller object by Authorization and id.
    """
    authorization_uk = adobe_authorizations_file["authorizations"][0]["authorization_uk"]
    seller_uk = adobe_authorizations_file["authorizations"][0]["resellers"][0]["seller_uk"]
    seller_id = adobe_authorizations_file["authorizations"][0]["resellers"][0]["seller_id"]
    reseller_id = adobe_authorizations_file["authorizations"][0]["resellers"][0]["id"]

    c = Config()
    authorization = c.get_authorization(authorization_uk)
    reseller = c.get_reseller(authorization, seller_uk)
    assert isinstance(reseller, Reseller)
    assert reseller.id == reseller_id
    assert reseller.seller_id == seller_id
    assert reseller.authorization == authorization
    assert c.get_reseller(authorization, seller_id) == reseller


def test_get_reseller_not_found(mock_adobe_config, adobe_authorizations_file):
    """
    Check that the lookup of the reseller raises `ResellerNotFoundError`
    if there is no reseller for a given an authorization and reseller uk/id.
    """
    c = Config()
    authorization_uk = adobe_authorizations_file["authorizations"][0]["authorization_uk"]
    auth = c.get_authorization(authorization_uk)
    with pytest.raises(ResellerNotFoundError) as cv:
        assert c.get_reseller(auth, "SEL-unknown")

    assert str(cv.value) == (
        "Reseller not found for authorization uk-auth-adobe-us-01 and uk/id SEL-unknown."
    )


def test_get_authorization(mock_adobe_config, adobe_credentials_file, adobe_authorizations_file):
    """
    Test the lookup the Authorization object by uk/id.
    """
    authorization_uk = adobe_authorizations_file["authorizations"][0]["authorization_uk"]
    authorization_id = adobe_authorizations_file["authorizations"][0]["authorization_id"]
    client_id = adobe_credentials_file[0]["client_id"]
    client_secret = adobe_credentials_file[0]["client_secret"]
    distributor_id = adobe_authorizations_file["authorizations"][0]["distributor_id"]
    currency = adobe_authorizations_file["authorizations"][0]["currency"]

    c = Config()
    authorization = c.get_authorization(authorization_uk)

    assert isinstance(authorization, Authorization)
    assert authorization.authorization_uk == authorization_uk
    assert authorization.authorization_id == authorization_id
    assert authorization.distributor_id == distributor_id
    assert authorization.currency == currency
    assert authorization.client_id == client_id
    assert authorization.client_secret == client_secret
    assert c.get_authorization(authorization_id) == authorization


def test_get_authorization_not_found(mock_adobe_config):
    """
    Check that the lookup of the Authorization raises `AuthorizationNotFoundError`
    if there is no Authorization for a given uk/id.
    """
    c = Config()
    with pytest.raises(AuthorizationNotFoundError) as cv:
        assert c.get_authorization("does-not-exist")

    assert str(cv.value) == "Authorization with uk/id does-not-exist not found."


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


def test_load_data(
    mocker,
    adobe_credentials_file,
    adobe_authorizations_file,
    adobe_config_file,
    settings,
):
    def multi_mock_open(*file_contents):
        mock_files = [mocker.mock_open(read_data=content).return_value for content in file_contents]
        mock_opener = mocker.mock_open()
        mock_opener.side_effect = mock_files
        return mock_opener

    settings.EXTENSION_CONFIG = {
        "ADOBE_CREDENTIALS_FILE": "a-credentials-file.json",
        "ADOBE_AUTHORIZATIONS_FILE": "an-authorization-file.json",
    }

    m_join = mocker.MagicMock()
    m_join.open = mocker.mock_open(read_data=json.dumps(adobe_config_file))
    m_files = mocker.MagicMock()
    m_files.joinpath.return_value = m_join
    mocked_files = mocker.patch("adobe_vipm.adobe.config.files", return_value=m_files)
    mocker.patch(
        "builtins.open",
        multi_mock_open(
            json.dumps(adobe_credentials_file),
            json.dumps(adobe_authorizations_file),
        ),
    )
    c = Config()
    mocked_files.assert_called_once_with("adobe_vipm")
    m_files.joinpath.assert_called_once_with("adobe_config.json")
    assert c.authorizations != {}
    assert c.resellers != {}
