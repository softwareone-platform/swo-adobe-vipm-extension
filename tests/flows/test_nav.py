from freezegun import freeze_time
from responses import matchers

from adobe_vipm.flows.nav import get_token, terminate_contract


def test_get_token(requests_mocker, settings):
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


def test_get_token_error(requests_mocker, settings):
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
    requests_mocker.patch(
        "https://api.nav/v1/contracts/terminate/my-cco",
        status=200,
        json={"id": "whatever"},
        match=[
            matchers.json_params_matcher(
                {
                    "terminationDate": "2024-01-01T12:00:00+00:00",
                },
            ),
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
    requests_mocker.patch(
        "https://api.nav/v1/contracts/terminate/my-cco", status=400, body="Bad request"
    )

    with freeze_time("2024-01-01 12:00:00"):
        ok, response = terminate_contract("my-cco")
        assert ok is False
        assert response == "400 - Bad request"
