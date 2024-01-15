from importlib.metadata import entry_points

from django.apps import apps


def get_extension_app_config_name():
    eps = entry_points()
    (app_config_ep,) = eps.select(group="swo.mpt.ext", name="app_config")
    app_config = app_config_ep.load()
    return f"{app_config.__module__}.{app_config.__name__}"


def get_extension_appconfig():
    app_config_name = get_extension_app_config_name()
    return next(
        filter(
            lambda app: app_config_name
            == f"{app.__class__.__module__}.{app.__class__.__name__}",
            apps.app_configs.values(),
        ),
        None,
    )


def get_extension():
    return get_extension_appconfig().extension


def get_events_registry():
    return get_extension().events
