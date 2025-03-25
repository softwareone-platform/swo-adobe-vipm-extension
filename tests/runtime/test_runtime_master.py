from django.test import override_settings
from swo.mpt.extensions.runtime.master import Master


@override_settings(
    MPT_PRODUCTS_IDS="PRD-1111-1111", LOGGING={"loggers": {"swo.mpt.ext": {}}}
)
def test_master_start_signals_handler(mock_runtime_master_options):
    mock_runtime_master = Master(mock_runtime_master_options)
    mock_runtime_master.setup_signals_handler()
    mock_runtime_master.start()
    is_started = mock_runtime_master.monitor_thread.is_alive()
    mock_runtime_master.stop()
    assert is_started


@override_settings(
    MPT_PRODUCTS_IDS="PRD-1111-1111", LOGGING={"loggers": {"swo.mpt": {}}}
)
def test_master_restart_signals_handler(mock_runtime_master_options):
    mock_runtime_master = Master(mock_runtime_master_options)
    mock_runtime_master.setup_signals_handler()
    mock_runtime_master.start()
    mock_runtime_master.restart()
    is_restarted = mock_runtime_master.monitor_thread.is_alive()
    mock_runtime_master.stop()
    assert is_restarted


@override_settings(
    MPT_PRODUCTS_IDS="PRD-1111-1111", LOGGING={"loggers": {"swo.mpt": {}}}
)
def test_master_stop_signals_handler(mock_runtime_master_options):
    mock_runtime_master = Master(mock_runtime_master_options)
    mock_runtime_master.setup_signals_handler()
    mock_runtime_master.start()
    mock_runtime_master.restart()
    mock_runtime_master.stop()
    is_stopped = not mock_runtime_master.monitor_thread.is_alive()
    assert is_stopped
