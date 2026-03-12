import importlib
from abc import ABC
from dataclasses import dataclass
from functools import lru_cache

from mpt_extension_sdk_v6.errors.runtime import ConfigError
from mpt_extension_sdk_v6.settings.base import BaseSettings
from mpt_extension_sdk_v6.settings.runtime import get_runtime_settings


@dataclass(frozen=True)
class BaseExtensionSettings(BaseSettings, ABC):
    """Base class for extension-scoped settings discovered by the SDK."""


def _get_root_package(handler_modules: tuple[str, ...]) -> str:
    # REVIEW: provide the root and the handler can be auto-discovered in the api folder
    root_packages = {module_name.split(".", maxsplit=1)[0] for module_name in handler_modules}
    if not root_packages:
        raise ConfigError("At least one handlers module is required to discover extension settings")
    if len(root_packages) != 1:
        raise ConfigError(
            "All handler modules must belong to the same root package to discover settings.py"
        )
    return root_packages.pop()


def _get_extension_settings_class(handler_modules: tuple[str, ...]) -> type[BaseExtensionSettings]:
    root_package = _get_root_package(handler_modules)
    config_module_name = f"{root_package}.settings"

    try:
        config_module = importlib.import_module(config_module_name)
    except ModuleNotFoundError as error:
        if error.name == config_module_name:
            raise ConfigError(
                f"Extension config module '{config_module_name}' is required but was not found"
            ) from error
        raise

    settings_class = getattr(config_module, "ExtensionSettings", None)
    if settings_class is None:
        raise ConfigError(
            f"Extension config module '{config_module_name}' must define ExtensionSettings"
        )
    if not isinstance(settings_class, type) or not issubclass(
        settings_class, BaseExtensionSettings
    ):
        raise ConfigError(
            f"Extension config class '{config_module_name}.Settings' must inherit "
            "from ExtensionSettings"
        )
    return settings_class


@lru_cache
def load_extension_settings(handler_modules: tuple[str, ...]) -> BaseExtensionSettings:
    """Discover and instantiate the extension settings for the active extension."""
    settings_class = _get_extension_settings_class(handler_modules)
    return settings_class.load()


def get_extension_settings() -> BaseExtensionSettings:
    """Return the cached extension settings singleton for the current process."""
    runtime_settings = get_runtime_settings()
    return load_extension_settings(tuple(runtime_settings.handlers_modules))
