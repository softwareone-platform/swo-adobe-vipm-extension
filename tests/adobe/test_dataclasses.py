from dataclasses import FrozenInstanceError
from datetime import datetime, timedelta

import pytest

from adobe_vipm.adobe.dataclasses import APIToken, Credentials, Reseller


def test_credentials():
    """
    Check the Credentials dataclass is unmutable and hasheable.
    """
    credentials = Credentials("client_id", "client_secret", "region")
    with pytest.raises(FrozenInstanceError):
        credentials.client_id = "new id"
    assert hash(credentials) is not None


def test_reseller():
    """
    Check the Reseller dataclass is unmutable and hasheable.
    """
    credentials = Credentials("client_id", "client_secret", "region")
    r = Reseller("id", "country", credentials)
    with pytest.raises(FrozenInstanceError):
        r.id = "new id"
    assert hash(r) is not None


def test_apitoken():
    """
    Check the APIToken dataclass is unmutable and hasheable.
    """
    token = APIToken("token", datetime.now())
    with pytest.raises(FrozenInstanceError):
        token.token = "new id"
    assert hash(token) is not None


def test_api_token_is_expired():
    """
    Test the is_expired method checks the token expires
    against the current date.
    """
    assert (
        APIToken("token", datetime.now() + timedelta(seconds=1)).is_expired() is False
    )

    assert APIToken("token", datetime.now() - timedelta(seconds=1)).is_expired() is True
