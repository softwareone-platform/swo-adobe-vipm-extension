from mpt_api_client.http import AsyncService
from mpt_api_client.http.mixins import AsyncGetMixin
from mpt_api_client.models import Model


class ExtensionsInstallations(Model):
    """Extensions installations model."""


class ExtensionsInstallationsServiceConfig:
    """Extensions installations service config."""

    _endpoint = "/public/v1/integration/extensions/{installation.id}/installations"
    _model_class = ExtensionsInstallations
    _collection_key = "data"


class AsyncExtensionsInstallationsService(
    AsyncGetMixin[ExtensionsInstallations],
    AsyncService[ExtensionsInstallations],
    ExtensionsInstallationsServiceConfig,
):
    """Extensions installations service."""
