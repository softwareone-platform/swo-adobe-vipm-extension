from swo.mpt.extensions.core.extension import Extension

from adobe_vipm.apps import ExtensionConfig


def test_app_config():
    assert isinstance(ExtensionConfig.extension, Extension)
