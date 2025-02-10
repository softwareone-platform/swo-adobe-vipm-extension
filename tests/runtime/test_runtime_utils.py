from ninja import NinjaAPI
from swo.mpt.extensions.core.events.registry import EventsRegistry
from swo.mpt.extensions.runtime.utils import (
    get_events_registry,
    get_extension,
    get_extension_app_config_name,
    get_extension_appconfig,
)


def test_get_extension_app_config_name():
    app_config_name = get_extension_app_config_name()
    assert app_config_name == "adobe_vipm.apps.ExtensionConfig"


def test_get_extension_appconfig():
    appconfig = get_extension_appconfig()
    assert appconfig.name == "adobe_vipm"
    assert appconfig.label == "adobe_vipm"


def test_get_extension():
    extension = get_extension()
    assert extension is not None
    assert isinstance(extension.api, NinjaAPI)
    assert isinstance(extension.events, EventsRegistry)


def test_get_events_registry():
    events_registry = get_events_registry()
    assert events_registry.listeners is not None
    assert isinstance(events_registry.listeners, dict)
