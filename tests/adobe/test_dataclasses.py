import datetime as dt
from dataclasses import FrozenInstanceError

import pytest

from adobe_vipm.adobe.dataclasses import APIToken, Authorization, Reseller


def test_authorization():  # noqa: AAA02
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

    result = hash(auth)

    assert result is not None


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

    result = repr(auth)

    assert result == (
        "Authorization(authorization_uk='auth_uk', authorization_id='auth_id', name='test', "
        "client_id='clie******t_id', client_secret='clie******cret', currency='EUR', "
        "distributor_id='distributor_id')"
    )


# FIX: it has multiple act blocks
def test_reseller():  # noqa: AAA02
    auth = Authorization(
        authorization_uk="auth_uk",
        authorization_id="auth_id",
        name="test",
        client_id="client_id",
        client_secret="client_secret",  # noqa: S106
        currency="EUR",
        distributor_id="distributor_id",
    )
    reseller = Reseller(
        seller_uk="seller_uk",
        seller_id="seller_id",
        id="P123456",
        authorization=auth,
    )
    with pytest.raises(FrozenInstanceError):
        reseller.id = "new id"

    result = hash(reseller)

    assert result is not None


# FIX: it has multiple act blocks
def test_api_token():  # noqa: AAA02
    token = APIToken("token", dt.datetime.now(tz=dt.UTC))
    with pytest.raises(FrozenInstanceError):
        token.token = "new id"

    result = hash(token)

    assert result is not None


def test_api_token_is_expired():
    token_expire_date = dt.datetime.now(tz=dt.UTC) - dt.timedelta(seconds=1)

    result = APIToken("token", token_expire_date).is_expired()

    assert result is True


def test_api_token_is_no_expired():
    token_expire_date = dt.datetime.now(tz=dt.UTC) + dt.timedelta(seconds=1)

    result = APIToken("token", token_expire_date).is_expired()

    assert result is False
