import datetime as dt
import logging
from collections.abc import MutableMapping
from functools import wraps
from urllib.parse import urlsplit
from uuid import uuid4

import httpx
from opentelemetry import trace
from opentelemetry.trace import SpanKind, Status, StatusCode

from adobe_vipm.adobe.config import Config, get_config
from adobe_vipm.adobe.dataclasses import APIToken, Authorization
from adobe_vipm.adobe.mixins.customer import CustomerClientMixin
from adobe_vipm.adobe.mixins.deployment import DeploymentClientMixin
from adobe_vipm.adobe.mixins.order import OrderClientMixin
from adobe_vipm.adobe.mixins.reseller import ResellerClientMixin
from adobe_vipm.adobe.mixins.subscription import SubscriptionClientMixin
from adobe_vipm.adobe.mixins.transfer import TransferClientMixin

logger = logging.getLogger(__name__)
tracer = trace.get_tracer(__name__)

# setup cache cleanup in number of seconds before actual Adobe token expire
# just to be sure to refresh token in time
EXPIRES_IN_DELAY_SECONDS = 180


def trace_adobe_request(func):
    """Wrap Adobe HTTP transport calls with dependency tracing and metadata-only logging."""

    @wraps(func)
    def wrapper(self, method: str, url: str, **kwargs) -> httpx.Response:
        method_upper = method.upper()
        parsed_url = urlsplit(url)
        span_name = f"{method_upper} {parsed_url.path or '/'}"
        with tracer.start_as_current_span(span_name, kind=SpanKind.CLIENT) as span:
            span.set_attribute("http.request.method", method_upper)
            span.set_attribute("url.full", url)
            span.set_attribute("server.address", parsed_url.hostname or "")
            self._logger.info("Adobe API request %s %s", method_upper, url)
            try:
                response = func(self, method_upper, url, **kwargs)
            except httpx.HTTPError as error:
                span.record_exception(error)
                span.set_status(Status(StatusCode.ERROR, str(error)))
                self._logger.exception("Adobe API request failed %s %s", method_upper, url)
                raise

            span.set_attribute("http.response.status_code", response.status_code)
            if response.status_code >= 400:
                span.set_status(Status(StatusCode.ERROR, str(response.status_code)))
            self._logger.info(
                "Adobe API response %s %s status=%s",
                method_upper,
                url,
                response.status_code,
            )
            return response

    return wrapper


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
        # 1. Mixins are using methods from parent (like _get_headers)
        # 2. Error handling still happens outside of a dedicated transport layer
        # 3. Mixins are using methods from parent (like _get_headers)
        # 4. Agreed to use composition instead of inheritance
        self._config: Config = get_config()
        self._token_cache: MutableMapping[Authorization, APIToken] = {}
        self._logger = logger
        self._TIMEOUT = 60
        self._http_client = httpx.Client(timeout=self._TIMEOUT)

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
        response = self._request(
            "POST",
            url=self._config.auth_endpoint_url,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            data={
                "grant_type": "client_credentials",
                "client_id": authorization.client_id,
                "client_secret": authorization.client_secret,
                "scope": self._config.api_scopes,
            },
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

    @trace_adobe_request
    def _request(self, method: str, url: str, **kwargs) -> httpx.Response:
        """Send an Adobe HTTP request."""
        return self._http_client.request(method=method, url=url, **kwargs)


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


class AdobeClientMixin:
    """Adobe Client Mixin."""

    adobe_client = get_adobe_client()
