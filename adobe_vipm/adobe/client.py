import datetime as dt
import logging
from collections.abc import MutableMapping
from uuid import uuid4

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from adobe_vipm.adobe.config import Config, get_config
from adobe_vipm.adobe.dataclasses import APIToken, Authorization
from adobe_vipm.adobe.errors import wrap_http_error
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

# Retry policy for transient Adobe API failures. Adobe documents the status
# set 200/201/202/400/401/403/404/429/500, so 429 and 500 are the only
# transient/retryable codes; the 4xx are client errors. Status and read retries
# are scoped to idempotent GET requests, so a non-idempotent POST/PATCH that
# already reached Adobe is never resent.
ADOBE_RETRY_TOTAL = 3
ADOBE_RETRY_BACKOFF_FACTOR = 1
ADOBE_RETRY_STATUS_FORCELIST = (429, 500)
ADOBE_RETRY_ALLOWED_METHODS = frozenset(("GET",))
# The auth endpoint only mints a bearer token, so resending its POST has no
# effect on customer or order data and is safe to retry.
ADOBE_AUTH_RETRY_ALLOWED_METHODS = frozenset(("GET", "POST"))


def _build_retry(allowed_methods: frozenset[str]) -> Retry:
    """Build the retry policy for transient Adobe failures.

    Args:
        allowed_methods: HTTP methods eligible for status and read retries.

    Returns:
        Retry: urllib3 retry policy.
    """
    return Retry(
        total=ADOBE_RETRY_TOTAL,
        backoff_factor=ADOBE_RETRY_BACKOFF_FACTOR,
        status_forcelist=ADOBE_RETRY_STATUS_FORCELIST,
        allowed_methods=allowed_methods,
        # A connect error means Adobe never received the request, so urllib3
        # retries it for any method without gating on allowed_methods.
        connect=ADOBE_RETRY_TOTAL,
        # A keep-alive connection closed by Adobe while idle in the pool
        # surfaces as a read error. urllib3 gates read retries on
        # allowed_methods, so only the methods above are resent.
        read=ADOBE_RETRY_TOTAL,
        # Transport errors urllib3 cannot classify stay unretried.
        other=0,
        # Return the final response once retries are exhausted instead of raising
        # urllib3's MaxRetryError, so raise_for_status/wrap_http_error still turn
        # a persistent failure into an AdobeAPIError.
        raise_on_status=False,
    )


def _build_retrying_session(auth_endpoint_url: str) -> requests.Session:
    """Build a requests Session that retries transient Adobe failures.

    The API adapter retries idempotent GET requests only. The auth endpoint gets
    its own adapter that also retries its token POST, which carries no
    side effect on customer or order data.

    Args:
        auth_endpoint_url: Adobe authentication endpoint URL, mounted with its
            own retry adapter.

    Returns:
        requests.Session: Session with the retrying HTTP adapters mounted.
    """
    session = requests.Session()
    # The Adobe API and auth endpoints are always HTTPS; the retry adapters are
    # only mounted on https:// so no clear-text scheme is used.
    session.mount("https://", HTTPAdapter(max_retries=_build_retry(ADOBE_RETRY_ALLOWED_METHODS)))
    session.mount(
        auth_endpoint_url,
        HTTPAdapter(max_retries=_build_retry(ADOBE_AUTH_RETRY_ALLOWED_METHODS)),
    )
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
        self._session = _build_retrying_session(self._config.auth_endpoint_url)

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

    @wrap_http_error
    def _refresh_auth_token(self, authorization: Authorization):
        """Request an authentication token for the Adobe VIPM API.

        Using the credentials associated to a given the reseller. Wrapped so a failure of the
        auth endpoint is reported against the token request instead of being caught by the
        calling method's wrapper and attributed to the Adobe API call that triggered it.
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
