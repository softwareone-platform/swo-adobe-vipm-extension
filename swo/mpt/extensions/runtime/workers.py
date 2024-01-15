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


def start_event_consumer():
    initialize()
    call_command("consume_events")


def start_gunicorn():
    initialize()
    options = {
        "bind": "0.0.0.0:8080",
    }
    app = ExtensionWebApplication(get_wsgi_application(), options=options).run()
