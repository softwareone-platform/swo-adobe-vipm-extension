from adobe_vipm.apps import ExtensionConfig
from swo.mpt.extensions.core.extension import Extension


def test_app_config():
    assert isinstance(ExtensionConfig.extension, Extension)
