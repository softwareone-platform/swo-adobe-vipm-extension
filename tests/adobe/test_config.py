import json

import pytest

from adobe_vipm.adobe.config import REQUIRED_API_SCOPES, Config
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
    result = Config()

    assert result.api_base_url == settings.EXTENSION_CONFIG["ADOBE_API_BASE_URL"]
    assert result.auth_endpoint_url == settings.EXTENSION_CONFIG["ADOBE_AUTH_ENDPOINT_URL"]
    assert result.api_scopes == ",".join(REQUIRED_API_SCOPES)
    assert result.language_codes == ["en-US"]


def test_get_reseller(mock_adobe_config, adobe_credentials_file, adobe_authorizations_file):
    authorization_uk = adobe_authorizations_file["authorizations"][0]["authorization_uk"]
    seller_uk = adobe_authorizations_file["authorizations"][0]["resellers"][0]["seller_uk"]
    seller_id = adobe_authorizations_file["authorizations"][0]["resellers"][0]["seller_id"]
    reseller_id = adobe_authorizations_file["authorizations"][0]["resellers"][0]["id"]

    result = Config()

    authorization = result.get_authorization(authorization_uk)
    reseller = result.get_reseller(authorization, seller_uk)
    assert isinstance(reseller, Reseller)
    assert reseller.id == reseller_id
    assert reseller.seller_id == seller_id
    assert reseller.authorization == authorization
    assert result.get_reseller(authorization, seller_id) == reseller


def test_get_reseller_not_found(mock_adobe_config, adobe_authorizations_file):
    config = Config()
    authorization_uk = adobe_authorizations_file["authorizations"][0]["authorization_uk"]
    auth = config.get_authorization(authorization_uk)

    with pytest.raises(ResellerNotFoundError) as cv:
        config.get_reseller(auth, "SEL-unknown")

    assert str(cv.value) == (
        "Reseller not found for authorization uk-auth-adobe-us-01 and uk/id SEL-unknown."
    )


def test_get_authorization(mock_adobe_config, adobe_credentials_file, adobe_authorizations_file):
    authorization_uk = adobe_authorizations_file["authorizations"][0]["authorization_uk"]
    authorization_id = adobe_authorizations_file["authorizations"][0]["authorization_id"]
    client_id = adobe_credentials_file[0]["client_id"]
    client_secret = adobe_credentials_file[0]["client_secret"]
    distributor_id = adobe_authorizations_file["authorizations"][0]["distributor_id"]
    currency = adobe_authorizations_file["authorizations"][0]["currency"]
    config = Config()

    result = config.get_authorization(authorization_uk)

    assert isinstance(result, Authorization)
    assert result.authorization_uk == authorization_uk
    assert result.authorization_id == authorization_id
    assert result.distributor_id == distributor_id
    assert result.currency == currency
    assert result.client_id == client_id
    assert result.client_secret == client_secret
    assert config.get_authorization(authorization_id) == result


def test_get_authorization_not_found(mock_adobe_config):
    config = Config()

    with pytest.raises(AuthorizationNotFoundError) as cv:
        assert config.get_authorization("does-not-exist")

    assert str(cv.value) == "Authorization with uk/id does-not-exist not found."


def test_get_country(mock_adobe_config, adobe_config_file):
    config = Config()

    result = config.get_country("US")

    assert isinstance(result, Country)
    assert result.code == "US"
    assert result.currencies == ["USD"]
    assert result.name == "United States"
    assert len(result.states_or_provinces) == 55
    assert result.pricelist_region == "NA"
    assert result.postal_code_format_regex == "^[\\d]{5}(?:-[\\d]{4})?$"


def test_get_country_not_found(mock_adobe_config):
    config = Config()

    with pytest.raises(CountryNotFoundError) as cv:
        config.get_country("not-found")

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

    # BL
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
        "adobe_vipm.adobe.config.Path.open",
        multi_mock_open(
            json.dumps(adobe_authorizations_file),
            json.dumps(adobe_credentials_file),
        ),
    )

    result = Config()

    mocked_files.assert_called_once_with("adobe_vipm")
    m_files.joinpath.assert_called_once_with("adobe_config.json")
    assert result.authorizations != {}
    assert result.resellers != {}
