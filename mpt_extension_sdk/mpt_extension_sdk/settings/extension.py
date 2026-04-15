from abc import ABC
from dataclasses import dataclass
from functools import lru_cache
from importlib import import_module

from mpt_extension_sdk.errors.runtime import ConfigError
from mpt_extension_sdk.settings.base import BaseSettings
from mpt_extension_sdk.settings.runtime import get_runtime_settings


@dataclass(frozen=True)
class BaseExtensionSettings(BaseSettings, ABC):
    """Base class for extension-scoped settings discovered by the SDK."""


@lru_cache
def load_extension_settings(settings_module_name: str) -> BaseExtensionSettings:
    """Discover and instantiate the extension settings for the active extension."""
    if not settings_module_name:
        raise ConfigError("Extension settings module name cannot be empty")

    try:
        config_module = import_module(settings_module_name)
    except ModuleNotFoundError as error:
        if error.name == settings_module_name:
            raise ConfigError(
                f"Extension config module '{settings_module_name}' is required but was not found"
            ) from error
        raise

    settings_class = getattr(config_module, "ExtensionSettings", None)
    if settings_class is None:
        raise ConfigError(
            f"Extension config module '{settings_module_name}' must define ExtensionSettings"
        )
    if not isinstance(settings_class, type) or not issubclass(
        settings_class, BaseExtensionSettings
    ):
        raise ConfigError(
            f"Extension config class '{settings_module_name}.ExtensionSettings' must inherit "
            "from BaseExtensionSettings"
        )
    return settings_class.load()


def get_extension_settings() -> BaseExtensionSettings:
    """Return the cached extension settings singleton for the current process."""
    runtime_settings = get_runtime_settings()
    return load_extension_settings(runtime_settings.settings_module)
