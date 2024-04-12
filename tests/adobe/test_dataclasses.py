from dataclasses import FrozenInstanceError
from datetime import datetime, timedelta

import pytest

from adobe_vipm.adobe.dataclasses import APIToken, Authorization, Reseller


def test_authorization():
    """
    Check the Authorization dataclass is unmutable and hasheable.
    """
    auth = Authorization(
        authorization_uk="auth_uk",
        authorization_id="auth_id",
        name="test",
        client_id="client_id",
        client_secret="client_secret",
        currency="EUR",
        distributor_id="distributor_id",
    )
    with pytest.raises(FrozenInstanceError):
        auth.client_id = "new id"
    assert hash(auth) is not None


def test_reseller():
    """
    Check the Reseller dataclass is unmutable and hasheable.
    """
    auth = Authorization(
        authorization_uk="auth_uk",
        authorization_id="auth_id",
        name="test",
        client_id="client_id",
        client_secret="client_secret",
        currency="EUR",
        distributor_id="distributor_id",
    )
    r = Reseller(
        seller_uk="seller_uk",
        seller_id="seller_id",
        id="P123456",
        authorization=auth,
    )
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
