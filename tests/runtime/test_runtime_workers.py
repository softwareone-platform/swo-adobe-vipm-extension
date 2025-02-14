from django.core.wsgi import get_wsgi_application
from swo.mpt.extensions.runtime.workers import (
    ExtensionWebApplication,
    start_event_consumer,
    start_gunicorn,
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


def test_start_event_consumer(
    mocker,
    mock_gunicorn_logging_config,
    mock_worker_initialize,
    mock_worker_call_command,
):
    gunicorn_options = {
        "bind": "localhost:8080",
        "logconfig_dict": mock_gunicorn_logging_config,
    }
    mock_initialize = mock_worker_initialize
    mock_call_command = mock_worker_call_command
    start_event_consumer(gunicorn_options)
    mock_initialize.assert_called_once()
    mock_call_command.assert_called_once()


def test_start_gunicorn(
    mocker,
    mock_gunicorn_logging_config,
    mock_worker_initialize,
):
    mock_initialize = mock_worker_initialize
    mock_run = mocker.patch.object(ExtensionWebApplication, "run", return_value=None)
    gunicorn_options = {
        "bind": "localhost:8080",
        "logconfig_dict": mock_gunicorn_logging_config,
    }
    start_gunicorn(gunicorn_options)
    mock_initialize.assert_called_once()
    mock_run.assert_called_once()
