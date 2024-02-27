from swo.mpt.extensions.core.events import Event

from adobe_vipm.extension import ext, process_order


def test_listener_registered():
    assert ext.events.get_listener("orders") == process_order


def test_process_order(mocker):
    mocked_fulfill_order = mocker.patch(
        "adobe_vipm.extension.fulfill_order",
    )

    client = mocker.MagicMock()
    event = Event("evt-id", "orders", {"id": "ORD-0792-5000-2253-4210"})

    process_order(client, event)

    mocked_fulfill_order.assert_called_once_with(client, event.data)
