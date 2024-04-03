import os

import rich
from rich.theme import Theme
from swo.mpt.extensions.runtime.djapp.conf import extract_product_ids
from swo.mpt.extensions.runtime.events.utils import instrument_logging
from swo.mpt.extensions.runtime.utils import get_extension_app_config_name


def get_extension_variables():
    variables = {}
    for var in filter(lambda x: x[0].startswith("EXT_"), os.environ.items()):
        variables[var[0][4:]] = var[1]
    return variables


def initialize(options):
    rich.reconfigure(theme=Theme({"repr.mpt_id": "bold light_salmon3"}))

    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "swo.mpt.extensions.runtime.djapp.conf.default")
    import django
    from django.conf import settings

    logging_handler = "rich" if options.get("color") else "console"
    logging_level = "DEBUG" if options.get("debug") else "INFO"

    app_config_name = get_extension_app_config_name()
    app_root_module, _ = app_config_name.split(".", 1)
    settings.DEBUG = options.get("debug", False)
    settings.INSTALLED_APPS.append(app_config_name)
    settings.LOGGING["root"]["handlers"] = [logging_handler]
    settings.LOGGING["loggers"]["swo.mpt"]["handlers"] = [logging_handler]
    settings.LOGGING["loggers"]["swo.mpt"]["level"] = logging_level
    settings.LOGGING["loggers"][app_root_module] = {
        "handlers": [logging_handler],
        "level": logging_level,
        "propagate": False,
    }
    settings.EXTENSION_CONFIG.update(get_extension_variables())
    settings.MPT_PRODUCTS_IDS = extract_product_ids(settings.MPT_PRODUCTS_IDS)

    if settings.USE_APPLICATIONINSIGHTS:
        instrument_logging()

    django.setup()
