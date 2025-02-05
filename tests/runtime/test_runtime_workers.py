from django.conf import settings
from django.core.wsgi import get_wsgi_application
from swo.mpt.extensions.runtime.workers import (
    ExtensionWebApplication,
)


def test_extension_web_application(mock_gunicorn_logging_config):
    is_success = True
    try:
        settings.LOGGING["loggers"]["swo.mpt"] = {}
        gunicorn_options = {
            "bind": "localhost:8080",
            "logconfig_dict": mock_gunicorn_logging_config,
        }
        wsgi_app = get_wsgi_application()
        ext_web_app = ExtensionWebApplication(wsgi_app, gunicorn_options)
        del settings.LOGGING["loggers"]["swo.mpt"]
        assert ext_web_app.application == wsgi_app
        assert ext_web_app.options == gunicorn_options
    except Exception:
        is_success = False
    assert is_success


def test_extension_web_application_load_config(mock_gunicorn_logging_config):
    is_success = True
    try:
        settings.LOGGING["loggers"]["swo.mpt"] = {}
        gunicorn_options = {
            "bind": "localhost:8080",
            "logconfig_dict": mock_gunicorn_logging_config,
        }
        wsgi_app = get_wsgi_application()
        ext_web_app = ExtensionWebApplication(wsgi_app, gunicorn_options)
        ext_web_app.load_config()
        del settings.LOGGING["loggers"]["swo.mpt"]
        assert ext_web_app.application == wsgi_app
        assert ext_web_app.options == gunicorn_options
    except Exception:
        is_success = False
    assert is_success
