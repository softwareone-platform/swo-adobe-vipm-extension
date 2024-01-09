import logging

from adobe_vipm.extension import ext, process_order
from swo.mpt.extensions.core.events import Event


def test_listener_registered():
    assert ext.events.get_listener("orders") == process_order


def test_process_order(mocker):
    mocked_fulfill_order = mocker.patch(
        "adobe_vipm.extension.fulfill_order",
    )

    client = mocker.MagicMock()
    event = Event("evt-id", "orders", {"order": "data"})

    process_order(client, event)

    mocked_fulfill_order.assert_called_once_with(client, event.data)


def test_process_order_exception(mocker, caplog):
    mocker.patch(
        "adobe_vipm.extension.fulfill_order",
        side_effect=RuntimeError("An error"),
    )

    client = mocker.MagicMock()
    event = Event("evt-id", "orders", {"order": "data"})

    with caplog.at_level(logging.ERROR):
        process_order(client, event)

    assert "Unhandled exception!" in caplog.text
