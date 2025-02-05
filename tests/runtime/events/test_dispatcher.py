import threading
from collections import deque
from concurrent.futures import ThreadPoolExecutor

from swo.mpt.client.base import MPTClient
from swo.mpt.extensions.core.events.dataclasses import Event
from swo.mpt.extensions.runtime.events.dispatcher import Dispatcher


def test_dispatcher():
    dispatcher = Dispatcher()
    assert dispatcher is not None
    assert isinstance(dispatcher.client, MPTClient)
    assert isinstance(dispatcher.executor, ThreadPoolExecutor)
    assert isinstance(dispatcher.queue, deque)
    assert dispatcher.futures == {}
    assert isinstance(dispatcher.running_event, threading.Event)
    assert isinstance(dispatcher.processor, threading.Thread)


def test_dispatcher_running():
    is_success = True
    try:
        dispatcher = Dispatcher()
        dispatcher.start()
        is_running = dispatcher.running
        assert is_running is True
        dispatcher.stop()
        is_running = dispatcher.running
        dispatcher.executor.shutdown()
        assert is_running is False
    except Exception:
        is_success = False
    assert is_success


def test_dispatcher_dispatch_event():
    is_success = True
    try:
        test_event = Event("evt-id", "orders", {"id": "ORD-1111-1111-1111"})
        dispatcher = Dispatcher()
        dispatcher.start()
        is_running = dispatcher.running
        assert is_running is True
        dispatcher.dispatch_event(test_event)
        dispatcher.stop()
        is_running = dispatcher.running
        assert is_running is False
        dispatcher.executor.shutdown()
    except Exception:
        is_success = False
    assert is_success


def test_dispatcher_process_events(mocker):
    is_success = True
    try:
        mocker.patch("adobe_vipm.extension.fulfill_order")
        # mocked_fulfill_order = mocker.patch("adobe_vipm.extension.fulfill_order")
        test_event = Event("evt-id", "orders", {"id": "ORD-1111-1111-1111"})
        dispatcher = Dispatcher()
        dispatcher.start()
        dispatcher.queue.clear()
        dispatcher.dispatch_event(test_event)
        # dispatcher.process_events()
        dispatcher.stop()
        dispatcher.executor.shutdown()
        # mocked_fulfill_order.assert_called_once()
    except Exception:
        is_success = False
    assert is_success
