from urllib.parse import urljoin

from swo.mpt.extensions.runtime.events.dispatcher import Dispatcher
from swo.mpt.extensions.runtime.events.producers import (
    OrderEventProducer,
)


def test_event_producer_produce_events(
    mocker,
    order_factory,
):
    order_to_process = order_factory()

    dispatcher = Dispatcher()
    order_event_producer = OrderEventProducer(dispatcher)

    def mock_dispatch_event_func(event, order):
        mock_dispatch_event_func.is_called = True
        order_event_producer.stop()

    mock_dispatch_event_func.is_called = False

    mocker.patch.object(
        Dispatcher,
        "dispatch_event",
        mock_dispatch_event_func,
    )

    mock_get_processing_orders = mocker.patch.object(
        OrderEventProducer, "get_processing_orders", return_value=[order_to_process]
    )

    order_event_producer.start()
    order_event_producer.produce_events()

    mock_get_processing_orders.assert_called()
    assert mock_dispatch_event_func.is_called


def test_event_producer_get_processing_orders(
    mpt_client,
    mock_wrap_event,
    requests_mocker,
    mock_settings_product_ids,
    mock_get_order_for_producer,
):
    limit = 10
    offset = 0
    rql_query = f"and(in(agreement.product.id,({mock_settings_product_ids})),eq(status,processing))"
    url = (
        f"/v1/commerce/orders?{rql_query}"
        "&select=audit,parameters,lines,subscriptions,subscriptions.lines&order=audit.created.at"
        f"&limit={limit}&offset={offset}"
    )
    requests_mocker.get(
        urljoin(mpt_client.base_url, url),
        json=mock_get_order_for_producer,
    )

    dispatcher = Dispatcher()
    dispatcher.start()
    dispatcher.dispatch_event(mock_wrap_event)

    orders = OrderEventProducer(dispatcher).get_processing_orders()
    dispatcher.stop()

    dispatcher.executor.shutdown()

    assert len(orders) == 1


def test_event_producers_has_more_pages(
    mock_wrap_event, mock_meta_with_pagination_has_more_pages
):
    dispatcher = Dispatcher()
    dispatcher.start()
    dispatcher.dispatch_event(mock_wrap_event)

    has_more_pages = OrderEventProducer(dispatcher).has_more_pages(
        mock_meta_with_pagination_has_more_pages
    )
    dispatcher.stop()
    dispatcher.executor.shutdown()
    assert has_more_pages is True


def test_event_producers_has_no_more_pages(
    mock_wrap_event, mock_meta_with_pagination_has_no_more_pages
):
    dispatcher = Dispatcher()
    dispatcher.start()
    dispatcher.dispatch_event(mock_wrap_event)

    has_more_pages = OrderEventProducer(dispatcher).has_more_pages(
        mock_meta_with_pagination_has_no_more_pages
    )
    dispatcher.stop()
    dispatcher.executor.shutdown()
    assert has_more_pages is False


def test_event_producer_start():
    dispatcher = Dispatcher()
    dispatcher.start()
    order_event_producer = OrderEventProducer(dispatcher)
    order_event_producer.start()
    is_running = order_event_producer.running
    order_event_producer.stop()
    dispatcher.stop()
    dispatcher.executor.shutdown()
    assert is_running


def test_event_producer_stop():
    dispatcher = Dispatcher()
    dispatcher.start()
    order_event_producer = OrderEventProducer(dispatcher)
    order_event_producer.start()
    order_event_producer.stop()
    is_running = order_event_producer.running
    dispatcher.stop()
    dispatcher.executor.shutdown()
    assert not is_running


def test_event_producer_sleep():
    dispatcher = Dispatcher()
    dispatcher.start()
    order_event_producer = OrderEventProducer(dispatcher)
    order_event_producer.start()
    order_event_producer.sleep(1, 0.5)
    is_running = order_event_producer.running
    order_event_producer.stop()
    dispatcher.stop()
    dispatcher.executor.shutdown()
    assert is_running
