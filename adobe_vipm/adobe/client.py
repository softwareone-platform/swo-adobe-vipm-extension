import datetime as dt
import logging
from collections.abc import MutableMapping
from uuid import uuid4

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from adobe_vipm.adobe.config import Config, get_config
from adobe_vipm.adobe.dataclasses import APIToken, Authorization
from adobe_vipm.adobe.mixins.customer import CustomerClientMixin
from adobe_vipm.adobe.mixins.deployment import DeploymentClientMixin
from adobe_vipm.adobe.mixins.order import OrderClientMixin
from adobe_vipm.adobe.mixins.reseller import ResellerClientMixin
from adobe_vipm.adobe.mixins.subscription import SubscriptionClientMixin
from adobe_vipm.adobe.mixins.transfer import TransferClientMixin

logger = logging.getLogger(__name__)

# setup cache cleanup in number of seconds before actual Adobe token expire
# just to be sure to refresh token in time
EXPIRES_IN_DELAY_SECONDS = 180

# Retry policy for transient Adobe API responses. Adobe documents the status
# set 200/201/202/400/401/403/404/429/500, so 429 and 500 are the only
# transient/retryable codes; the 4xx are client errors. Retries are scoped to
# idempotent GET requests, so non-idempotent POST/PATCH calls are never retried.
ADOBE_RETRY_TOTAL = 3
ADOBE_RETRY_BACKOFF_FACTOR = 1
ADOBE_RETRY_STATUS_FORCELIST = (429, 500)
ADOBE_RETRY_ALLOWED_METHODS = frozenset(("GET",))


def _build_retrying_session() -> requests.Session:
    """Build a requests Session that retries transient Adobe responses.

    Retries are limited to idempotent GET requests for HTTP 429 and 500, the
    only transient statuses the Adobe API raises. Non-idempotent POST and PATCH
    requests are never retried.

    Returns:
        requests.Session: Session with a retrying HTTP adapter mounted.
    """
    retry = Retry(
        total=ADOBE_RETRY_TOTAL,
        backoff_factor=ADOBE_RETRY_BACKOFF_FACTOR,
        status_forcelist=ADOBE_RETRY_STATUS_FORCELIST,
        allowed_methods=ADOBE_RETRY_ALLOWED_METHODS,
        # Retry on matching HTTP statuses only. connect/read/other default to
        # None (bounded only by total), which would also retry transport errors;
        # pin them to 0 so the policy stays status-only as documented above.
        connect=0,
        read=0,
        other=0,
        # Return the final response once retries are exhausted instead of raising
        # urllib3's MaxRetryError, so raise_for_status/wrap_http_error still turn
        # a persistent failure into an AdobeAPIError.
        raise_on_status=False,
    )
    adapter = HTTPAdapter(max_retries=retry)
    session = requests.Session()
    # The Adobe API and auth endpoints are always HTTPS; the retry adapter is
    # only mounted on https:// so no clear-text scheme is used.
    session.mount("https://", adapter)
    return session


class AdobeClient(
    CustomerClientMixin,
    ResellerClientMixin,
    SubscriptionClientMixin,
    TransferClientMixin,
    DeploymentClientMixin,
    OrderClientMixin,
):
    """Adobe API Client."""

    def __init__(self) -> None:
        # TODO: client should be refactored cause of several things
        # 1. Probably worth to use httpx instead of requests
        # 2. Mixins are using methods from parent (like _get_headers)
        # 3. Agreed to use composition instead of inheritance
        self._config: Config = get_config()
        self._token_cache: MutableMapping[Authorization, APIToken] = {}
        self._logger = logger
        self._TIMEOUT = 60
        self._session = _build_retrying_session()

    def _get_headers(self, authorization: Authorization, correlation_id=None):
        token = self._get_auth_token(authorization).token
        return {
            "X-Api-Key": authorization.client_id,
            "Authorization": f"Bearer {token}",
            "Accept": "application/json",
            "Content-Type": "application/json",
            "X-Request-Id": str(uuid4()),
            "x-correlation-id": correlation_id or str(uuid4()),
        }

    def _refresh_auth_token(self, authorization: Authorization):
        """Request an authentication token for the Adobe VIPM API.

        Using the credentials associated to a given the reseller.
        """
        response = self._session.post(
            url=self._config.auth_endpoint_url,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            data={
                "grant_type": "client_credentials",
                "client_id": authorization.client_id,
                "client_secret": authorization.client_secret,
                "scope": self._config.api_scopes,
            },
            timeout=self._TIMEOUT,
        )
        response.raise_for_status()

        token_info = response.json()
        expires_in = dt.timedelta(seconds=token_info["expires_in"] - EXPIRES_IN_DELAY_SECONDS)
        self._token_cache[authorization] = APIToken(
            token=token_info["access_token"],
            expires=dt.datetime.now(tz=dt.UTC) + expires_in,
        )

    def _get_auth_token(self, authorization: Authorization):
        token: APIToken | None = self._token_cache.get(authorization)
        if not token or token.is_expired():
            self._refresh_auth_token(authorization)
        return self._token_cache[authorization]


_ADOBE_CLIENT = None


def get_adobe_client() -> AdobeClient:
    """
    Returns an instance of the `AdobeClient`.

    Returns:
        AdobeClient: An instance of the `AdobeClient`.
    """
    global _ADOBE_CLIENT  # noqa: PLW0603 WPS420
    if not _ADOBE_CLIENT:
        _ADOBE_CLIENT = AdobeClient()
    return _ADOBE_CLIENT
