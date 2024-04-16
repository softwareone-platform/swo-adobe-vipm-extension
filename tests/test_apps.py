import pytest
from django.apps import apps
from django.core.exceptions import ImproperlyConfigured
from swo.mpt.extensions.core.extension import Extension

from adobe_vipm.apps import ExtensionConfig


def test_app_config():
    assert isinstance(ExtensionConfig.extension, Extension)


def test_products_empty(settings):
    settings.MPT_PRODUCTS_IDS = ""

    app = apps.get_app_config("adobe_vipm")
    with pytest.raises(ImproperlyConfigured) as e:
        app.ready()

    assert "MPT_PRODUCTS_IDS is missing or empty" in str(e.value)


def test_products_not_defined(settings):
    delattr(settings, "MPT_PRODUCTS_IDS")

    app = apps.get_app_config("adobe_vipm")
    with pytest.raises(ImproperlyConfigured) as e:
        app.ready()

    assert "MPT_PRODUCTS_IDS is missing or empty" in str(e.value)


def test_querying_template_not_defined(settings):
    settings.MPT_PRODUCTS_IDS = ["PRD-1111-1111"]
    settings.EXTENSION_CONFIG = {}

    app = apps.get_app_config("adobe_vipm")
    with pytest.raises(ImproperlyConfigured) as e:
        app.ready()

    assert "Please, specify EXT_QUERYING_TEMPLATE_ID_PRD_1111_1111" in str(e.value)


def test_completed_template_not_defined(settings):
    settings.MPT_PRODUCTS_IDS = ["PRD-1111-1111"]
    settings.EXTENSION_CONFIG = {
        "EXT_QUERYING_TEMPLATE_ID_PRD_1111_1111": "TPL-123-123-123"
    }

    app = apps.get_app_config("adobe_vipm")
    with pytest.raises(ImproperlyConfigured) as e:
        app.ready()

    assert "Please, specify EXT_COMPLETED_TEMPLATE_ID_PRD_1111_1111" in str(e.value)


def test_webhook_secret_not_defined(settings):
    settings.MPT_PRODUCTS_IDS = ["PRD-1111-1111"]
    settings.EXTENSION_CONFIG = {
        "EXT_QUERYING_TEMPLATE_ID_PRD_1111_1111": "TPL-123-123-123",
        "EXT_COMPLETED_TEMPLATE_ID_PRD_1111_1111": "TPL-321-321-321",
    }

    app = apps.get_app_config("adobe_vipm")
    with pytest.raises(ImproperlyConfigured) as e:
        app.ready()

    assert (
        "Please, specify EXT_WEBHOOK_SECRET_PRD_1111_1111 environment variable."
        in str(e.value)
    )
