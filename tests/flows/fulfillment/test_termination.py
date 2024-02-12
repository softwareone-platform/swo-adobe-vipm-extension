from adobe_vipm.adobe.constants import (
    ORDER_TYPE_NEW,
    ORDER_TYPE_RETURN,
    STATUS_PENDING,
    STATUS_PROCESSED,
)
from adobe_vipm.flows.constants import ORDER_TYPE_TERMINATION
from adobe_vipm.flows.fulfillment import fulfill_order


def test_termination(
    mocker,
    settings,
    agreement,
    seller,
    order_factory,
    items_factory,
    fulfillment_parameters_factory,
    adobe_order_factory,
):
    """
    Tests the processing of a termination order:
        * search adobe orders by sku that must be referenced in return orders
        * adobe return order creation
        * order completion
    """
    settings.EXTENSION_CONFIG["COMPLETED_TEMPLATE_ID"] = "TPL-1111"
    mocker.patch("adobe_vipm.flows.fulfillment.get_agreement", return_value=agreement)
    mocked_get_seller = mocker.patch(
        "adobe_vipm.flows.fulfillment.get_seller",
        return_value=seller,
    )

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
        "adobe_vipm.flows.fulfillment.get_adobe_client",
        return_value=mocked_adobe_client,
    )

    processing_order = order_factory(
        order_type=ORDER_TYPE_TERMINATION,
        items=items_factory(
            old_quantity=20,
            quantity=10,
        ),
        fulfillment_parameters=fulfillment_parameters_factory(
            customer_id="a-client-id",
        ),
        order_parameters=[],
    )

    mocked_mpt_client = mocker.MagicMock()

    mocker.patch(
        "adobe_vipm.flows.fulfillment.update_order",
        return_value=processing_order,
    )

    mocked_complete_order = mocker.patch(
        "adobe_vipm.flows.fulfillment.complete_order",
    )

    fulfill_order(mocked_mpt_client, processing_order)

    seller_country = seller["address"]["country"]

    mocked_get_seller.assert_called_once_with(mocked_mpt_client, seller["id"])
    mocked_adobe_client.create_return_order.assert_called_once_with(
        seller_country,
        "a-client-id",
        order_to_return,
        order_to_return["lineItems"][0],
    )

    mocked_complete_order.assert_called_once_with(
        mocked_mpt_client,
        processing_order["id"],
        "TPL-1111",
    )


def test_termination_return_order_pending(
    mocker,
    settings,
    agreement,
    seller,
    order_factory,
    items_factory,
    fulfillment_parameters_factory,
    adobe_order_factory,
):
    """
    Tests the processing of a termination order:
        * search adobe orders by sku that must be referenced in return orders
        * adobe return order creation
        * order completion
    """
    settings.EXTENSION_CONFIG["COMPLETED_TEMPLATE_ID"] = "TPL-1111"
    mocker.patch("adobe_vipm.flows.fulfillment.get_agreement", return_value=agreement)
    mocked_get_seller = mocker.patch(
        "adobe_vipm.flows.fulfillment.get_seller",
        return_value=seller,
    )

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
        "adobe_vipm.flows.fulfillment.get_adobe_client",
        return_value=mocked_adobe_client,
    )

    processing_order = order_factory(
        order_type=ORDER_TYPE_TERMINATION,
        items=items_factory(
            old_quantity=20,
            quantity=10,
        ),
        fulfillment_parameters=fulfillment_parameters_factory(
            customer_id="a-client-id",
        ),
        order_parameters=[],
    )

    mocked_mpt_client = mocker.MagicMock()

    mocker.patch(
        "adobe_vipm.flows.fulfillment.update_order",
        return_value=processing_order,
    )

    mocked_complete_order = mocker.patch(
        "adobe_vipm.flows.fulfillment.complete_order",
    )

    fulfill_order(mocked_mpt_client, processing_order)

    seller_country = seller["address"]["country"]

    mocked_get_seller.assert_called_once_with(mocked_mpt_client, seller["id"])
    mocked_adobe_client.create_return_order.assert_called_once_with(
        seller_country,
        "a-client-id",
        order_to_return,
        order_to_return["lineItems"][0],
    )

    mocked_complete_order.assert_not_called()
