from django.core.wsgi import get_wsgi_application
from mpt_extension_sdk.runtime.workers import (
    ExtensionWebApplication,
)


def test_extension_web_application(mock_gunicorn_logging_config):
    gunicorn_options = {
        "bind": "localhost:8080",
        "logconfig_dict": mock_gunicorn_logging_config,
    }
    wsgi_app = get_wsgi_application()
    ext_web_app = ExtensionWebApplication(wsgi_app, gunicorn_options)
    assert ext_web_app.application == wsgi_app
    assert ext_web_app.options == gunicorn_options


def test_extension_web_application_load_config(mock_gunicorn_logging_config):
    gunicorn_options = {
        "bind": "localhost:8080",
        "logconfig_dict": mock_gunicorn_logging_config,
    }
    wsgi_app = get_wsgi_application()
    ext_web_app = ExtensionWebApplication(wsgi_app, gunicorn_options)
    ext_web_app.load_config()
    assert ext_web_app.application == wsgi_app
    assert ext_web_app.options == gunicorn_options
