import datetime as dt
from dataclasses import FrozenInstanceError

import pytest

from adobe_vipm.adobe.dataclasses import APIToken, Authorization, Reseller


def test_authorization():
    auth = Authorization(
        authorization_uk="auth_uk",
        authorization_id="auth_id",
        name="test",
        client_id="client_id",
        client_secret="client_secret",  # noqa: S106
        currency="EUR",
        distributor_id="distributor_id",
    )
    with pytest.raises(FrozenInstanceError):
        auth.client_id = "new id"
    assert hash(auth) is not None


def test_authorization_repr():
    auth = Authorization(
        authorization_uk="auth_uk",
        authorization_id="auth_id",
        name="test",
        client_id="client_id",
        client_secret="client_secret",  # noqa: S106
        currency="EUR",
        distributor_id="distributor_id",
    )
    assert repr(auth) == (
        "Authorization(authorization_uk='auth_uk', authorization_id='auth_id', name='test', "
        "client_id='clie******t_id', client_secret='clie******cret', currency='EUR', "
        "distributor_id='distributor_id')"
    )


def test_reseller():
    auth = Authorization(
        authorization_uk="auth_uk",
        authorization_id="auth_id",
        name="test",
        client_id="client_id",
        client_secret="client_secret",  # noqa: S106
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
    token = APIToken("token", dt.datetime.now(tz=dt.UTC))
    with pytest.raises(FrozenInstanceError):
        token.token = "new id"
    assert hash(token) is not None


def test_api_token_is_expired():
    token_expire_date = dt.datetime.now(tz=dt.UTC) - dt.timedelta(seconds=1)
    assert APIToken("token", token_expire_date).is_expired() is True


def test_api_token_is_no_expired():
    token_expire_date = dt.datetime.now(tz=dt.UTC) + dt.timedelta(seconds=1)
    assert APIToken("token", token_expire_date).is_expired() is False
