import pytest
from click.testing import CliRunner
from django.apps import apps
from django.core.exceptions import ImproperlyConfigured
from mpt_extension_sdk.core.extension import Extension
from mpt_extension_sdk.runtime.swoext import cli

from adobe_vipm.apps import ExtensionConfig


def test_app_config():
    result = isinstance(ExtensionConfig.extension, Extension)

    assert result is True


def test_cli():
    app_config_name = "adobe_vipm"
    app_config = apps.get_app_config(app_config_name)
    app_config.ready()
    runner = CliRunner()

    result = runner.invoke(cli, ["django", "--help"])

    assert result.return_value is None


def test_products_empty(settings):
    settings.MPT_PRODUCTS_IDS = ""
    app = apps.get_app_config("adobe_vipm")

    with pytest.raises(ImproperlyConfigured) as error:
        app.ready()

    assert "MPT_PRODUCTS_IDS is missing or empty" in str(error.value)


def test_products_not_defined(settings):
    delattr(settings, "MPT_PRODUCTS_IDS")
    app = apps.get_app_config("adobe_vipm")

    with pytest.raises(ImproperlyConfigured) as error:
        app.ready()

    assert "MPT_PRODUCTS_IDS is missing or empty" in str(error.value)


def test_webhook_secret_not_defined(settings):
    settings.MPT_PRODUCTS_IDS = ["PRD-1111-1111"]
    settings.EXTENSION_CONFIG = {}
    app = apps.get_app_config("adobe_vipm")

    with pytest.raises(ImproperlyConfigured) as error:
        app.ready()

    assert "Please, specify it in EXT_WEBHOOKS_SECRETS environment variable." in str(error.value)
