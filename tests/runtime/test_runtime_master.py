from django.conf import settings


def test_master_setup_signals_handler(mock_runtime_master):
    is_success = True
    try:
        settings.LOGGING["loggers"]["swo.mpt"] = {}
        product_ids = settings.MPT_PRODUCTS_IDS
        settings.MPT_PRODUCTS_IDS = "PRD-1111-1111"
        mock_runtime_master.setup_signals_handler()
        del settings.LOGGING["loggers"]["swo.mpt"]
        settings.MPT_PRODUCTS_IDS = product_ids
    except Exception:
        is_success = False
    assert is_success


def test_master_start_stop_signals_handler(mock_runtime_master):
    is_success = True
    try:
        settings.LOGGING["loggers"]["swo.mpt"] = {}
        product_ids = settings.MPT_PRODUCTS_IDS
        settings.MPT_PRODUCTS_IDS = "PRD-1111-1111"
        mock_runtime_master.setup_signals_handler()
        mock_runtime_master.start()
        mock_runtime_master.stop()
        mock_runtime_master.start()
        mock_runtime_master.restart()
        mock_runtime_master.stop()
        del settings.LOGGING["loggers"]["swo.mpt"]
        settings.MPT_PRODUCTS_IDS = product_ids
    except Exception:
        is_success = False
    assert is_success
