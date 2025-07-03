import logging
from collections.abc import MutableMapping
from datetime import datetime, timedelta
from uuid import uuid4

import requests

from adobe_vipm.adobe.config import Config, get_config
from adobe_vipm.adobe.dataclasses import APIToken, Authorization
from adobe_vipm.adobe.mixins.customer import CustomerClientMixin
from adobe_vipm.adobe.mixins.deployment import DeploymentClientMixin
from adobe_vipm.adobe.mixins.order import OrderClientMixin
from adobe_vipm.adobe.mixins.reseller import ResellerClientMixin
from adobe_vipm.adobe.mixins.subscription import SubscriptionClientMixin
from adobe_vipm.adobe.mixins.transfer import TransferClientMixin

logger = logging.getLogger(__name__)


class AdobeClient(
    CustomerClientMixin,
    ResellerClientMixin,
    SubscriptionClientMixin,
    TransferClientMixin,
    DeploymentClientMixin,
    OrderClientMixin,
):
    def __init__(self) -> None:
        self._config: Config = get_config()
        self._token_cache: MutableMapping[Authorization, APIToken] = {}
        self._logger = logger


    def _get_headers(self, authorization: Authorization, correlation_id=None):
        return {
            "X-Api-Key": authorization.client_id,
            "Authorization": f"Bearer {self._get_auth_token(authorization).token}",
            "Accept": "application/json",
            "Content-Type": "application/json",
            "X-Request-Id": str(uuid4()),
            "x-correlation-id": correlation_id or str(uuid4()),
        }

    def _refresh_auth_token(self, authorization: Authorization):
        """
        Request an authentication token for the Adobe VIPM API
        using the credentials associated to a given the reseller.
        """

        data = {
            "grant_type": "client_credentials",
            "client_id": authorization.client_id,
            "client_secret": authorization.client_secret,
            "scope": self._config.api_scopes,
        }
        response = requests.post(
            url=self._config.auth_endpoint_url,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            data=data,
        )
        if response.status_code == 200:
            token_info = response.json()
            self._token_cache[authorization] = APIToken(
                token=token_info["access_token"],
                expires=(
                    datetime.now() + timedelta(seconds=token_info["expires_in"] - 180)
                ),
            )
        response.raise_for_status()

    def _get_auth_token(self, authorization: Authorization):
        token: APIToken | None = self._token_cache.get(authorization)
        if not token or token.is_expired():
            self._refresh_auth_token(authorization)
        token = self._token_cache[authorization]
        return token


_ADOBE_CLIENT = None


def get_adobe_client() -> AdobeClient:
    """
    Returns an instance of the `AdobeClient`.

    Returns:
        AdobeClient: An instance of the `AdobeClient`.
    """
    global _ADOBE_CLIENT
    if not _ADOBE_CLIENT:
        _ADOBE_CLIENT = AdobeClient()
    return _ADOBE_CLIENT
