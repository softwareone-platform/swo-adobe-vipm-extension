from datetime import UTC, datetime, timedelta

from adobe_vipm.adobe.constants import (
    ORDER_TYPE_NEW,
    ORDER_TYPE_RETURN,
    STATUS_PENDING,
    STATUS_PROCESSED,
)
from adobe_vipm.flows.constants import (
    CANCELLATION_WINDOW_DAYS,
    MPT_ORDER_STATUS_COMPLETED,
    MPT_ORDER_STATUS_PROCESSING,
    ORDER_TYPE_TERMINATION,
    TEMPLATE_NAME_TERMINATION,
)
from adobe_vipm.flows.fulfillment import fulfill_order


def test_termination(
    mocker,
    agreement,
    order_factory,
    lines_factory,
    fulfillment_parameters_factory,
    subscriptions_factory,
    adobe_order_factory,
):
    """
    Tests the processing of a termination order:
        * search adobe orders by sku that must be referenced in return orders
        * adobe return order creation
        * order completion
    """
    mocked_get_template = mocker.patch(
        "adobe_vipm.flows.fulfillment.shared.get_product_template_or_default",
        side_effect=[{"id": "TPL-0000"}, {"id": "TPL-1111"}],
    )
    mocker.patch("adobe_vipm.flows.helpers.get_agreement", return_value=agreement)

    order_to_return = adobe_order_factory(
        ORDER_TYPE_NEW,
        status=STATUS_PROCESSED,
        order_id="P0000000",
    )
    adobe_return_order = adobe_order_factory(
        ORDER_TYPE_RETURN,
        status=STATUS_PROCESSED,
    )

    mocked_adobe_client = mocker.MagicMock()
    mocked_adobe_client.search_new_and_returned_orders_by_sku_line_number.return_value = [
        (order_to_return, order_to_return["lineItems"][0], None),
    ]
    mocked_adobe_client.create_return_order.return_value = adobe_return_order
    mocker.patch(
        "adobe_vipm.flows.fulfillment.termination.get_adobe_client",
        return_value=mocked_adobe_client,
    )

    processing_order = order_factory(
        order_type=ORDER_TYPE_TERMINATION,
        lines=lines_factory(
            old_quantity=20,
            quantity=10,
        ),
        subscriptions=subscriptions_factory(lines=lines_factory(quantity=10)),
        fulfillment_parameters=fulfillment_parameters_factory(
            customer_id="a-client-id",
        ),
        order_parameters=[],
    )

    mocked_mpt_client = mocker.MagicMock()

    mocker.patch(
        "adobe_vipm.flows.fulfillment.shared.update_order",
        return_value=processing_order,
    )
    mocked_process_order = mocker.patch(
        "adobe_vipm.flows.fulfillment.shared.set_processing_template",
    )
    mocked_complete_order = mocker.patch(
        "adobe_vipm.flows.fulfillment.shared.complete_order",
    )

    fulfill_order(mocked_mpt_client, processing_order)

    authorization_id = processing_order["authorization"]["id"]

    mocked_adobe_client.create_return_order.assert_called_once_with(
        authorization_id,
        "a-client-id",
        order_to_return,
        order_to_return["lineItems"][0],
    )
    mocked_process_order.assert_called_once_with(
        mocked_mpt_client,
        processing_order["id"],
        {"id": "TPL-0000"},
    )
    mocked_complete_order.assert_called_once_with(
        mocked_mpt_client,
        processing_order["id"],
        {"id": "TPL-1111"},
    )
    mocked_adobe_client.search_new_and_returned_orders_by_sku_line_number.assert_called_once_with(
        authorization_id,
        "a-client-id",
        processing_order["lines"][0]["item"]["externalIds"]["vendor"],
        processing_order["lines"][0]["id"],
    )
    assert mocked_get_template.mock_calls[0].args == (
        mocked_mpt_client,
        processing_order["agreement"]["product"]["id"],
        MPT_ORDER_STATUS_PROCESSING,
        TEMPLATE_NAME_TERMINATION,
    )

    assert mocked_get_template.mock_calls[1].args == (
        mocked_mpt_client,
        processing_order["agreement"]["product"]["id"],
        MPT_ORDER_STATUS_COMPLETED,
        TEMPLATE_NAME_TERMINATION,
    )


def test_termination_return_order_pending(
    mocker,
    agreement,
    order_factory,
    lines_factory,
    subscriptions_factory,
    fulfillment_parameters_factory,
    adobe_order_factory,
):
    """
    Tests the processing of a termination order:
        * search adobe orders by sku that must be referenced in return orders
        * adobe return order creation
        * order completion
    """
    mocker.patch("adobe_vipm.flows.helpers.get_agreement", return_value=agreement)

    order_to_return = adobe_order_factory(
        ORDER_TYPE_NEW,
        status=STATUS_PROCESSED,
        order_id="P0000000",
    )
    adobe_return_order = adobe_order_factory(
        ORDER_TYPE_RETURN,
        status=STATUS_PENDING,
    )

    mocked_adobe_client = mocker.MagicMock()
    mocked_adobe_client.search_new_and_returned_orders_by_sku_line_number.return_value = [
        (order_to_return, order_to_return["lineItems"][0], None),
    ]
    mocked_adobe_client.create_return_order.return_value = adobe_return_order
    mocker.patch(
        "adobe_vipm.flows.fulfillment.termination.get_adobe_client",
        return_value=mocked_adobe_client,
    )

    processing_order = order_factory(
        order_type=ORDER_TYPE_TERMINATION,
        lines=lines_factory(
            old_quantity=20,
            quantity=10,
        ),
        subscriptions=subscriptions_factory(lines=lines_factory(quantity=10)),
        fulfillment_parameters=fulfillment_parameters_factory(
            customer_id="a-client-id",
        ),
        order_parameters=[],
    )

    mocked_mpt_client = mocker.MagicMock()

    mocker.patch(
        "adobe_vipm.flows.fulfillment.shared.update_order",
        return_value=processing_order,
    )

    mocked_complete_order = mocker.patch(
        "adobe_vipm.flows.fulfillment.shared.complete_order",
    )

    fulfill_order(mocked_mpt_client, processing_order)

    authorization_id = processing_order["authorization"]["id"]

    mocked_adobe_client.create_return_order.assert_called_once_with(
        authorization_id,
        "a-client-id",
        order_to_return,
        order_to_return["lineItems"][0],
    )

    mocked_complete_order.assert_not_called()


def test_termination_out_window(
    mocker,
    agreement,
    order_factory,
    lines_factory,
    fulfillment_parameters_factory,
    subscriptions_factory,
    adobe_subscription_factory,
):
    """
    Tests the processing of a termination order outside the cancellation window:
        * update subscription auto renewal
        * order completion
    """
    mocker.patch(
        "adobe_vipm.flows.fulfillment.shared.get_product_template_or_default",
        return_value={"id": "TPL-1111"},
    )

    mocker.patch("adobe_vipm.flows.helpers.get_agreement", return_value=agreement)

    adobe_subscription = adobe_subscription_factory()

    mocked_adobe_client = mocker.MagicMock()
    mocked_adobe_client.get_subscription.return_value = adobe_subscription
    mocker.patch(
        "adobe_vipm.flows.fulfillment.termination.get_adobe_client",
        return_value=mocked_adobe_client,
    )

    processing_order = order_factory(
        order_type=ORDER_TYPE_TERMINATION,
        lines=lines_factory(
            old_quantity=20,
            quantity=10,
        ),
        subscriptions=subscriptions_factory(
            lines=lines_factory(),
            start_date=datetime.now(UTC) - timedelta(days=CANCELLATION_WINDOW_DAYS + 1),
        ),
        fulfillment_parameters=fulfillment_parameters_factory(
            customer_id="a-client-id",
        ),
        order_parameters=[],
    )

    mocked_mpt_client = mocker.MagicMock()

    mocker.patch(
        "adobe_vipm.flows.fulfillment.shared.update_order",
        return_value=processing_order,
    )

    mocked_complete_order = mocker.patch(
        "adobe_vipm.flows.fulfillment.shared.complete_order",
    )

    fulfill_order(mocked_mpt_client, processing_order)

    authorization_id = processing_order["authorization"]["id"]

    mocked_adobe_client.update_subscription.assert_called_once_with(
        authorization_id,
        "a-client-id",
        adobe_subscription["subscriptionId"],
        auto_renewal=False,
    )

    mocked_complete_order.assert_called_once_with(
        mocked_mpt_client,
        processing_order["id"],
        {"id": "TPL-1111"},
    )
