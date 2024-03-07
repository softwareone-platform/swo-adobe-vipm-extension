from django.core.management import call_command
from django.core.wsgi import get_wsgi_application
from gunicorn.app.base import BaseApplication
from swo.mpt.extensions.runtime.initializer import initialize


class ExtensionWebApplication(BaseApplication):
    def __init__(self, app, options=None):
        self.options = options or {}
        self.application = app
        super().__init__()

    def load_config(self):
        config = {
            key: value
            for key, value in self.options.items()
            if key in self.cfg.settings and value is not None
        }
        for key, value in config.items():
            self.cfg.set(key.lower(), value)

    def load(self):
        return self.application


def start_event_consumer(options):
    initialize(options)
    call_command("consume_events")


def start_gunicorn(options):
    initialize(options)

    logging_config = {
        "version": 1,
        "disable_existing_loggers": False,
        "formatters": {
            "verbose": {
                "format": "{asctime} {name} {levelname} (pid: {process}) {message}",
                "style": "{",
            },
            "rich": {
                "format": "%(message)s",
            },
        },
        "handlers": {
            "console": {
                "class": "logging.StreamHandler",
                "formatter": "verbose",
            },
            "rich": {
                "class": "rich.logging.RichHandler",
                "formatter": "rich",
                "log_time_format": lambda x: x.strftime("%Y-%m-%d %H:%M:%S.%f")[:-3],
                "rich_tracebacks": True,
            },
        },
        "root": {
            "handlers": ["rich" if options.get("color") else "console"],
            "level": "INFO",
        },
        "loggers": {
            "gunicorn.access": {
                "handlers": ["rich" if options.get("color") else "console"],
                "level": "INFO",
                "propagate": False,
            },
            "gunicorn.error": {
                "handlers": ["rich" if options.get("color") else "console"],
                "level": "INFO",
                "propagate": False,
            },
        },
    }

    guni_options = {
        "bind": options.get("bind", "0.0.0.0:8080"),
        "logconfig_dict": logging_config,
    }
    ExtensionWebApplication(get_wsgi_application(), options=guni_options).run()
