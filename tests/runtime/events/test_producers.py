from urllib.parse import urljoin

from django.conf import settings
from swo.mpt.extensions.runtime.events.dispatcher import Dispatcher
from swo.mpt.extensions.runtime.events.producers import (
    OrderEventProducer,
)


def test_event_producer_produce_events(mock_wrap_event):
    is_success = True
    try:
        dispatcher = Dispatcher()
        dispatcher.start()
        dispatcher.dispatch_event(mock_wrap_event)
        # OrderEventProducer(dispatcher).produce_events()
        dispatcher.stop()
        dispatcher.executor.shutdown()
    except Exception:
        is_success = False
    assert is_success


def test_event_producer_get_processing_orders(
    mpt_client,
    mock_wrap_event,
    requests_mocker,
    order_factory,
):
    order = order_factory()

    products = ",".join(settings.MPT_PRODUCTS_IDS)
    rql_query = f"and(in(agreement.product.id,({products})),eq(status,processing))"
    url = (
        f"/commerce/orders?{rql_query}"
        "&select=audit,parameters,lines,subscriptions,subscriptions.lines&order=audit.created.at"
    )
    limit = 10
    offset = 0
    data = {
        "data": [order],
        "$meta": {
            "pagination": {
                "offset": 0,
                "limit": 10,
                "total": 1,
            },
        },
    }
    requests_mocker.get(
        urljoin(mpt_client.base_url, f"/v1{url}&limit={limit}&offset={offset}"),
        json=data,
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


def test_event_producer_start_stop():
    is_success = True
    try:
        dispatcher = Dispatcher()
        dispatcher.start()
        order_event_producer = OrderEventProducer(dispatcher)
        order_event_producer.start()
        assert order_event_producer.running
        order_event_producer.sleep(1, 0.5)
        order_event_producer.stop()
        assert not order_event_producer.running
        dispatcher.stop()
        dispatcher.executor.shutdown()
    except Exception:
        is_success = False
    assert is_success
