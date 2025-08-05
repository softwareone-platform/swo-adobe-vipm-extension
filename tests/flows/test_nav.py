import json

from freezegun import freeze_time
from responses import matchers

from adobe_vipm.flows.nav import get_token, terminate_contract


@freeze_time("2024-04-04 12:30:00")
def test_get_token(mocker, requests_mocker, settings):
    mocker.patch(
        "adobe_vipm.flows.nav.Path.is_file",
        return_value=False,
    )

    mocked_open = mocker.patch("adobe_vipm.flows.nav.Path.open", mocker.mock_open())

    settings.EXTENSION_CONFIG = {
        "NAV_AUTH_ENDPOINT_URL": "https://authenticate.nav",
        "NAV_AUTH_CLIENT_ID": "client-id",
        "NAV_AUTH_CLIENT_SECRET": "client-secret",
        "NAV_AUTH_AUDIENCE": "audience",
    }

    requests_mocker.post(
        "https://authenticate.nav",
        status=200,
        json={
            "access_token": "a-token",
            "expires_in": 86400,
        },
        match=[
            matchers.urlencoded_params_matcher(
                {
                    "client_id": "client-id",
                    "client_secret": "client-secret",
                    "audience": "audience",
                    "grant_type": "client_credentials",
                },
            ),
        ],
    )

    assert get_token() == (True, "a-token")
    mocked_open().write.assert_called_once_with(
        '{"access_token": "a-token", "expires_in": 86400, '
        '"expires_at": "2024-04-05T12:25:00+00:00"}',
    )


@freeze_time("2024-04-04 12:30:00")
def test_get_token_from_cache(mocker):
    mocker.patch("adobe_vipm.flows.nav.Path.is_file", return_value=True)
    mocker.patch(
        "adobe_vipm.flows.nav.Path.open",
        mocker.mock_open(
            read_data=(
                '{"access_token": "a-token", "expires_in": 86400, '
                '"expires_at": "2024-04-05T12:25:00+00:00"}'
            )
        ),
    )

    assert get_token() == (True, "a-token")


@freeze_time("2024-04-04 12:30:00")
def test_get_token_from_cache_expired(mocker, requests_mocker, settings):
    mocker.patch("adobe_vipm.flows.nav.Path.is_file", return_value=True)
    mocker.patch(
        "adobe_vipm.flows.nav.Path.open",
        mocker.mock_open(
            read_data=(
                '{"access_token": "a-token", "expires_in": 86400, '
                '"expires_at": "2024-03-05T12:25:00+00:00"}'
            )
        ),
    )
    mocked_save_token = mocker.patch("adobe_vipm.flows.nav.save_token_to_disk")

    settings.EXTENSION_CONFIG = {
        "NAV_AUTH_ENDPOINT_URL": "https://authenticate.nav",
        "NAV_AUTH_CLIENT_ID": "client-id",
        "NAV_AUTH_CLIENT_SECRET": "client-secret",
        "NAV_AUTH_AUDIENCE": "audience",
    }

    requests_mocker.post(
        "https://authenticate.nav",
        status=200,
        json={
            "access_token": "a-token",
            "expires_in": 86400,
        },
        match=[
            matchers.urlencoded_params_matcher(
                {
                    "client_id": "client-id",
                    "client_secret": "client-secret",
                    "audience": "audience",
                    "grant_type": "client_credentials",
                },
            ),
        ],
    )

    assert get_token() == (True, "a-token")
    mocked_save_token.assert_called_once_with({
        "access_token": "a-token",
        "expires_in": 86400,
    })


def test_get_token_error(mocker, requests_mocker, settings):
    mocker.patch(
        "adobe_vipm.flows.nav.get_token_from_disk",
        return_value=None,
    )
    settings.EXTENSION_CONFIG = {
        "NAV_AUTH_ENDPOINT_URL": "https://authenticate.nav",
        "NAV_AUTH_CLIENT_ID": "client-id",
        "NAV_AUTH_CLIENT_SECRET": "client-secret",
        "NAV_AUTH_AUDIENCE": "audience",
    }

    requests_mocker.post("https://authenticate.nav", status=400, body="bad request")
    assert get_token() == (False, "400 - bad request")


def test_terminate_contract(mocker, requests_mocker, settings):
    settings.EXTENSION_CONFIG = {
        "NAV_API_BASE_URL": "https://api.nav",
    }

    mocker.patch("adobe_vipm.flows.nav.get_token", return_value=(True, "a-token"))
    requests_mocker.post(
        "https://api.nav/v1.0/contracts/terminateNow/my-cco",
        status=200,
        json={"contractInsert": {"contractNumber": "whatever", "isPreferred": False}},
        match=[
            matchers.header_matcher(
                {
                    "Authorization": "Bearer a-token",
                },
            ),
        ],
    )

    with freeze_time("2024-01-01 12:00:00"):
        ok, _ = terminate_contract("my-cco")
        assert ok is True


def test_terminate_contract_token_error(mocker):
    mocker.patch(
        "adobe_vipm.flows.nav.get_token",
        return_value=(False, "200 - Internal Server Error"),
    )

    ok, resp = terminate_contract("my-cco")
    assert ok is False
    assert resp == "200 - Internal Server Error"


def test_terminate_contract_api_error(mocker, requests_mocker, settings):
    settings.EXTENSION_CONFIG = {
        "NAV_API_BASE_URL": "https://api.nav",
    }

    mocker.patch("adobe_vipm.flows.nav.get_token", return_value=(True, "a-token"))
    requests_mocker.post(
        "https://api.nav/v1.0/contracts/terminateNow/my-cco",
        status=400,
        body="Bad request",
    )

    with freeze_time("2024-01-01 12:00:00"):
        ok, response = terminate_contract("my-cco")
        assert ok is False
        assert response == "400 - Bad request"


def test_terminate_contract_json_decode_error(mocker, requests_mocker, settings):
    settings.EXTENSION_CONFIG = {
        "NAV_API_BASE_URL": "https://api.nav",
    }

    mocker.patch("adobe_vipm.flows.nav.get_token", return_value=(True, "a-token"))
    requests_mocker.post(
        "https://api.nav/v1.0/contracts/terminateNow/my-cco",
        status=200,
        body="This is not JSON",
    )

    with freeze_time("2024-01-01 12:00:00"):
        ok, response = terminate_contract("my-cco")
        assert ok is False
        assert response == "200 - This is not JSON"


def test_terminate_contract_unexpected_json(mocker, requests_mocker, settings):
    settings.EXTENSION_CONFIG = {
        "NAV_API_BASE_URL": "https://api.nav",
    }

    mocker.patch("adobe_vipm.flows.nav.get_token", return_value=(True, "a-token"))
    requests_mocker.post(
        "https://api.nav/v1.0/contracts/terminateNow/my-cco",
        status=200,
        json={"other": "JSON"},
    )

    with freeze_time("2024-01-01 12:00:00"):
        ok, response = terminate_contract("my-cco")
        assert ok is False
        assert response == '200 - {"other": "JSON"}'


def test_terminate_contract_non_terminated(mocker, requests_mocker, settings):
    settings.EXTENSION_CONFIG = {
        "NAV_API_BASE_URL": "https://api.nav",
    }
    resp_json = """{"contractInsert": {"contractNumber": "whatever", "isPreferred": true}}"""
    mocker.patch("adobe_vipm.flows.nav.get_token", return_value=(True, "a-token"))
    requests_mocker.post(
        "https://api.nav/v1.0/contracts/terminateNow/my-cco",
        status=200,
        json=json.loads(resp_json),
        match=[
            matchers.header_matcher(
                {
                    "Authorization": "Bearer a-token",
                },
            ),
        ],
    )

    with freeze_time("2024-01-01 12:00:00"):
        ok, resp = terminate_contract("my-cco")
        assert ok is False
        assert resp == f"200 - {resp_json}"
