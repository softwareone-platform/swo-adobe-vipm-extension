from datetime import UTC, datetime, timedelta

from adobe_vipm.adobe.constants import (
    ORDER_TYPE_NEW,
    ORDER_TYPE_PREVIEW,
    ORDER_TYPE_RETURN,
    STATUS_PENDING,
    STATUS_PROCESSED,
)
from adobe_vipm.adobe.errors import AdobeError
from adobe_vipm.flows.constants import CANCELLATION_WINDOW_DAYS
from adobe_vipm.flows.fulfillment import fulfill_order


def test_upsizing(
    mocker,
    settings,
    agreement,
    seller,
    order_factory,
    lines_factory,
    fulfillment_parameters_factory,
    subscriptions_factory,
    adobe_order_factory,
    adobe_items_factory,
):
    """
    Tests a change order in case of upsizing.
    """
    settings.EXTENSION_CONFIG["COMPLETED_TEMPLATE_ID"] = "TPL-1111"
    mocker.patch("adobe_vipm.flows.helpers.get_agreement", return_value=agreement)

    adobe_preview_order = adobe_order_factory(ORDER_TYPE_PREVIEW)
    adobe_order = adobe_order_factory(
        ORDER_TYPE_NEW,
        status=STATUS_PROCESSED,
        items=adobe_items_factory(subscription_id="a-sub-id"),
    )

    mocked_adobe_client = mocker.MagicMock()
    mocked_adobe_client.create_preview_order.return_value = adobe_preview_order
    mocked_adobe_client.create_new_order.return_value = adobe_order
    mocked_adobe_client.get_order.return_value = adobe_order
    mocker.patch(
        "adobe_vipm.flows.fulfillment.change.get_adobe_client",
        return_value=mocked_adobe_client,
    )

    processing_change_order = order_factory(
        order_type="change",
        lines=lines_factory(
            old_quantity=10,
            quantity=20,
        ),
        fulfillment_parameters=fulfillment_parameters_factory(
            customer_id="a-client-id",
        ),
        order_parameters=[],
    )

    subscriptions = subscriptions_factory(lines=lines_factory(quantity=10))

    updated_change_order = order_factory(
        order_type="change",
        lines=lines_factory(
            old_quantity=10,
            quantity=20,
        ),
        subscriptions=subscriptions,
        fulfillment_parameters=fulfillment_parameters_factory(
            customer_id="a-client-id",
        ),
        order_parameters=[],
        external_ids={"vendor": adobe_order["orderId"]},
    )

    mocked_mpt_client = mocker.MagicMock()
    mocked_update_order = mocker.patch(
        "adobe_vipm.flows.fulfillment.shared.update_order",
        return_value=updated_change_order,
    )

    mocked_complete_order = mocker.patch(
        "adobe_vipm.flows.fulfillment.shared.complete_order",
    )
    fulfill_order(mocked_mpt_client, processing_change_order)

    seller_country = seller["address"]["country"]

    mocked_adobe_client.create_preview_order.assert_called_once_with(
        seller_country,
        "a-client-id",
        processing_change_order["id"],
        processing_change_order["lines"],
    )

    assert mocked_update_order.mock_calls[0].args == (
        mocked_mpt_client,
        processing_change_order["id"],
    )
    assert mocked_update_order.mock_calls[0].kwargs == {
        "externalIds": {
            "vendor": adobe_order["orderId"],
        },
    }
    assert mocked_update_order.mock_calls[1].args == (
        mocked_mpt_client,
        processing_change_order["id"],
    )
    assert mocked_update_order.mock_calls[1].kwargs == {
        "parameters": {
            "fulfillment": fulfillment_parameters_factory(
                customer_id="a-client-id",
                retry_count="0",
            ),
            "ordering": [],
        },
    }

    mocked_complete_order.assert_called_once_with(
        mocked_mpt_client,
        processing_change_order["id"],
        "TPL-1111",
    )


def test_upsizing_order_already_created_adobe_order_not_ready(
    mocker,
    agreement,
    order_factory,
    lines_factory,
    fulfillment_parameters_factory,
    adobe_order_factory,
):
    """
    Tests the processing of an change order (upsizing) that has been placed in the previous
    attemp and still pending.
    """
    mocker.patch("adobe_vipm.flows.helpers.get_agreement", return_value=agreement)
    mocked_update_order = mocker.patch(
        "adobe_vipm.flows.fulfillment.shared.update_order",
    )
    mocked_complete_order = mocker.patch(
        "adobe_vipm.flows.fulfillment.shared.complete_order",
    )

    adobe_order = adobe_order_factory(ORDER_TYPE_NEW, status=STATUS_PENDING)

    mocked_adobe_client = mocker.MagicMock()
    mocked_adobe_client.get_order.return_value = adobe_order
    mocker.patch(
        "adobe_vipm.flows.fulfillment.change.get_adobe_client",
        return_value=mocked_adobe_client,
    )
    mocked_mpt_client = mocker.MagicMock()

    order = order_factory(
        order_type="change",
        lines=lines_factory(
            old_quantity=10,
            quantity=20,
        ),
        fulfillment_parameters=fulfillment_parameters_factory(
            customer_id="a-client-id",
        ),
        order_parameters=[],
        external_ids={"vendor": adobe_order["orderId"]},
    )
    fulfill_order(mocked_mpt_client, order)

    mocked_adobe_client.get_subscription.assert_not_called()
    mocked_update_order.assert_called_once_with(
        mocked_mpt_client,
        order["id"],
        parameters={
            "fulfillment": fulfillment_parameters_factory(
                retry_count="1",
                customer_id="a-client-id",
            ),
            "ordering": [],
        },
    )
    mocked_complete_order.assert_not_called()


def test_upsizing_create_adobe_preview_order_error(
    mocker,
    agreement,
    order_factory,
    lines_factory,
    fulfillment_parameters_factory,
    adobe_api_error_factory,
):
    """
    Tests the processing of a change order (upsizing) when the Adobe preview order
    creation fails. The change order will be failed.
    """
    mocker.patch("adobe_vipm.flows.helpers.get_agreement", return_value=agreement)

    adobe_error = AdobeError(
        adobe_api_error_factory("9999", "Error while creating a preview order")
    )

    mocked_adobe_client = mocker.MagicMock()
    mocked_adobe_client.create_preview_order.side_effect = adobe_error
    mocker.patch(
        "adobe_vipm.flows.fulfillment.change.get_adobe_client",
        return_value=mocked_adobe_client,
    )

    mocked_fail_order = mocker.patch("adobe_vipm.flows.fulfillment.shared.fail_order")

    mocked_mpt_client = mocker.MagicMock()

    order = order_factory(
        order_type="change",
        lines=lines_factory(
            old_quantity=10,
            quantity=20,
        ),
        fulfillment_parameters=fulfillment_parameters_factory(
            customer_id="a-client-id",
        ),
        order_parameters=[],
    )
    fulfill_order(mocked_mpt_client, order)

    mocked_fail_order.assert_called_once_with(
        mocked_mpt_client,
        order["id"],
        str(adobe_error),
    )


def test_downsizing(
    mocker,
    settings,
    seller,
    agreement,
    order_factory,
    lines_factory,
    fulfillment_parameters_factory,
    subscriptions_factory,
    adobe_order_factory,
    adobe_items_factory,
):
    """
    Tests the processing of a change order (downsizing) including:
        * search adobe orders by sku that must be referenced in return orders
        * adobe return orders creation
        * adobe preview order creation
        * adobe new order creation
        * order completion
    """
    settings.EXTENSION_CONFIG["COMPLETED_TEMPLATE_ID"] = "TPL-1111"
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
    adobe_preview_order = adobe_order_factory(ORDER_TYPE_PREVIEW)
    adobe_order = adobe_order_factory(
        ORDER_TYPE_NEW,
        status=STATUS_PROCESSED,
        items=adobe_items_factory(subscription_id="a-sub-id"),
    )

    mocked_adobe_client = mocker.MagicMock()
    mocked_adobe_client.search_new_and_returned_orders_by_sku_line_number.return_value = [
        (order_to_return, order_to_return["lineItems"][0], None),
    ]
    mocked_adobe_client.create_return_order.return_value = adobe_return_order
    mocked_adobe_client.create_preview_order.return_value = adobe_preview_order
    mocked_adobe_client.create_new_order.return_value = adobe_order
    mocked_adobe_client.get_order.return_value = adobe_order
    mocker.patch(
        "adobe_vipm.flows.fulfillment.change.get_adobe_client",
        return_value=mocked_adobe_client,
    )

    subscriptions = subscriptions_factory(lines=lines_factory(quantity=20))

    updated_order = order_factory(
        order_type="Change",
        lines=lines_factory(
            old_quantity=20,
            quantity=10,
        ),
        subscriptions=subscriptions,
        fulfillment_parameters=fulfillment_parameters_factory(
            customer_id="a-client-id",
        ),
        order_parameters=[],
        external_ids={"vendor": adobe_order["orderId"]},
    )

    processing_order = order_factory(
        order_type="change",
        lines=lines_factory(
            old_quantity=20,
            quantity=10,
        ),
        subscriptions=subscriptions,
        fulfillment_parameters=fulfillment_parameters_factory(
            customer_id="a-client-id",
        ),
        order_parameters=[],
    )

    mocked_mpt_client = mocker.MagicMock()
    mocked_update_order = mocker.patch(
        "adobe_vipm.flows.fulfillment.shared.update_order",
        return_value=updated_order,
    )

    mocked_complete_order = mocker.patch(
        "adobe_vipm.flows.fulfillment.shared.complete_order",
    )
    fulfill_order(mocked_mpt_client, processing_order)

    seller_country = seller["address"]["country"]

    mocked_adobe_client.create_return_order.assert_called_once_with(
        seller_country,
        "a-client-id",
        order_to_return,
        order_to_return["lineItems"][0],
    )

    assert mocked_update_order.mock_calls[0].args == (
        mocked_mpt_client,
        processing_order["id"],
    )
    assert mocked_update_order.mock_calls[0].kwargs == {
        "parameters": processing_order["parameters"],
    }

    assert mocked_update_order.mock_calls[1].args == (
        mocked_mpt_client,
        processing_order["id"],
    )
    assert mocked_update_order.mock_calls[1].kwargs == {
        "externalIds": {
            "vendor": adobe_order["orderId"],
        },
    }

    mocked_complete_order.assert_called_once_with(
        mocked_mpt_client,
        processing_order["id"],
        "TPL-1111",
    )
    mocked_adobe_client.search_new_and_returned_orders_by_sku_line_number.assert_called_once_with(
        seller_country,
        "a-client-id",
        processing_order["lines"][0]["item"]["externalIds"]["vendor"],
        processing_order["lines"][0]["id"],
    )


def test_downsizing_return_order_exists(
    mocker,
    settings,
    agreement,
    order_factory,
    lines_factory,
    fulfillment_parameters_factory,
    subscriptions_factory,
    adobe_order_factory,
    adobe_items_factory,
    adobe_subscription_factory,
):
    """
    Tests the processing of a change order (downsizing) when the return order
    has already been created in Adobe.
    The return order will not be placed again.
    """
    settings.EXTENSION_CONFIG["COMPLETED_TEMPLATE_ID"] = "TPL-1111"
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
    adobe_preview_order = adobe_order_factory(ORDER_TYPE_PREVIEW)
    adobe_order = adobe_order_factory(
        ORDER_TYPE_NEW,
        status=STATUS_PROCESSED,
        items=adobe_items_factory(subscription_id="a-sub-id"),
    )
    adobe_subscription = adobe_subscription_factory()

    mocked_adobe_client = mocker.MagicMock()
    mocked_adobe_client.create_preview_order.return_value = adobe_preview_order
    mocked_adobe_client.search_new_and_returned_orders_by_sku_line_number.return_value = [
        (order_to_return, order_to_return["lineItems"][0], adobe_return_order),
    ]
    mocked_adobe_client.create_new_order.return_value = adobe_order
    mocked_adobe_client.get_order.return_value = adobe_order
    mocked_adobe_client.get_subscription.return_value = adobe_subscription

    mocker.patch(
        "adobe_vipm.flows.fulfillment.change.get_adobe_client",
        return_value=mocked_adobe_client,
    )

    subscriptions = subscriptions_factory(lines=lines_factory(quantity=20))

    processing_order = order_factory(
        order_type="change",
        lines=lines_factory(
            old_quantity=20,
            quantity=10,
        ),
        subscriptions=subscriptions,
        fulfillment_parameters=fulfillment_parameters_factory(
            customer_id="a-client-id",
        ),
        order_parameters=[],
    )

    updated_order = order_factory(
        order_type="change",
        lines=lines_factory(
            old_quantity=20,
            quantity=10,
        ),
        subscriptions=subscriptions,
        fulfillment_parameters=fulfillment_parameters_factory(
            customer_id="a-client-id",
        ),
        order_parameters=[],
        external_ids={"vendor": adobe_order["orderId"]},
    )

    mocked_mpt_client = mocker.MagicMock()
    mocked_update_order = mocker.patch(
        "adobe_vipm.flows.fulfillment.shared.update_order",
        return_value=updated_order,
    )
    mocked_complete_order = mocker.patch(
        "adobe_vipm.flows.fulfillment.shared.complete_order",
    )

    fulfill_order(mocked_mpt_client, processing_order)

    assert mocked_update_order.mock_calls[0].args == (
        mocked_mpt_client,
        processing_order["id"],
    )
    assert mocked_update_order.mock_calls[0].kwargs == {
        "parameters": processing_order["parameters"],
    }

    assert mocked_update_order.mock_calls[1].args == (
        mocked_mpt_client,
        processing_order["id"],
    )
    assert mocked_update_order.mock_calls[1].kwargs == {
        "externalIds": {
            "vendor": adobe_order["orderId"],
        },
    }

    mocked_complete_order.assert_called_once_with(
        mocked_mpt_client,
        processing_order["id"],
        "TPL-1111",
    )
    mocked_adobe_client.create_return_order.assert_not_called()


def test_downsizing_return_order_pending(
    mocker,
    agreement,
    order_factory,
    lines_factory,
    fulfillment_parameters_factory,
    subscriptions_factory,
    adobe_order_factory,
):
    """
    Tests the processing of a change order (downsizing) when the return order
    has already been created in Adobe but it is still pending.
    The return order will not be placed again.
    The new order will not be placed yet.
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
    adobe_preview_order = adobe_order_factory(ORDER_TYPE_PREVIEW)

    mocked_adobe_client = mocker.MagicMock()
    mocked_adobe_client.create_preview_order.return_value = adobe_preview_order
    mocked_adobe_client.search_new_and_returned_orders_by_sku_line_number.return_value = [
        (order_to_return, order_to_return["lineItems"][0], adobe_return_order),
    ]

    mocker.patch(
        "adobe_vipm.flows.fulfillment.change.get_adobe_client",
        return_value=mocked_adobe_client,
    )
    mocked_mpt_client = mocker.MagicMock()
    mocked_update_order = mocker.patch(
        "adobe_vipm.flows.fulfillment.shared.update_order",
    )
    mocked_complete_order = mocker.patch(
        "adobe_vipm.flows.fulfillment.shared.complete_order",
    )

    order = order_factory(
        order_type="change",
        lines=lines_factory(
            old_quantity=20,
            quantity=10,
        ),
        subscriptions=subscriptions_factory(lines=lines_factory(quantity=20)),
        fulfillment_parameters=fulfillment_parameters_factory(
            customer_id="a-client-id",
        ),
        order_parameters=[],
    )
    fulfill_order(mocked_mpt_client, order)

    mocked_update_order.assert_called_once_with(
        mocked_mpt_client,
        order["id"],
        parameters={
            "fulfillment": fulfillment_parameters_factory(
                retry_count="1",
                customer_id="a-client-id",
            ),
            "ordering": [],
        },
    )
    mocked_complete_order.assert_not_called()
    mocked_adobe_client.create_return_order.assert_not_called()


def test_downsizing_new_order_pending(
    mocker,
    seller,
    agreement,
    order_factory,
    lines_factory,
    fulfillment_parameters_factory,
    adobe_order_factory,
):
    """
    Tests the processing of a change order (downsizing) when the return order
    has already been created and processed by Adobe and the new order has been
    placed but is still pending.
    The return order will not be placed again.
    The RetryCount parameter will be set to 1.
    """
    mocker.patch("adobe_vipm.flows.helpers.get_agreement", return_value=agreement)

    adobe_order = adobe_order_factory(
        ORDER_TYPE_NEW,
        status=STATUS_PENDING,
    )

    mocked_adobe_client = mocker.MagicMock()
    mocked_adobe_client.get_order.return_value = adobe_order
    mocker.patch(
        "adobe_vipm.flows.fulfillment.change.get_adobe_client",
        return_value=mocked_adobe_client,
    )
    mocked_mpt_client = mocker.MagicMock()

    order = order_factory(
        order_type="change",
        lines=lines_factory(
            old_quantity=20,
            quantity=10,
        ),
        fulfillment_parameters=fulfillment_parameters_factory(
            customer_id="a-client-id",
        ),
        order_parameters=[],
        external_ids={"vendor": adobe_order["orderId"]},
    )

    mocked_update_order = mocker.patch(
        "adobe_vipm.flows.fulfillment.shared.update_order",
        return_value=order,
    )

    mocked_complete_order = mocker.patch(
        "adobe_vipm.flows.fulfillment.shared.complete_order",
    )
    fulfill_order(mocked_mpt_client, order)

    mocked_adobe_client.create_return_order.assert_not_called()
    mocked_complete_order.assert_not_called()
    mocked_update_order.assert_called_once_with(
        mocked_mpt_client,
        order["id"],
        parameters={
            "fulfillment": fulfillment_parameters_factory(
                retry_count="1",
                customer_id="a-client-id",
            ),
            "ordering": [],
        },
    )


def test_downsizing_create_new_order_error(
    mocker,
    settings,
    agreement,
    order_factory,
    lines_factory,
    fulfillment_parameters_factory,
    subscriptions_factory,
    adobe_order_factory,
    adobe_api_error_factory,
):
    """
    Tests the processing of a change order (downsizing) when the create new order
    returns an error.

    """
    settings.EXTENSION_CONFIG["COMPLETED_TEMPLATE_ID"] = "TPL-1111"
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
    adobe_preview_order = adobe_order_factory(ORDER_TYPE_PREVIEW)
    adobe_error = AdobeError(adobe_api_error_factory(code=400, message="an error"))

    mocked_adobe_client = mocker.MagicMock()
    mocked_adobe_client.create_preview_order.return_value = adobe_preview_order
    mocked_adobe_client.search_new_and_returned_orders_by_sku_line_number.return_value = [
        (order_to_return, order_to_return["lineItems"][0], None),
    ]
    mocked_adobe_client.create_return_order.return_value = adobe_return_order
    mocked_adobe_client.create_new_order.side_effect = adobe_error

    mocker.patch(
        "adobe_vipm.flows.fulfillment.change.get_adobe_client",
        return_value=mocked_adobe_client,
    )
    mocked_mpt_client = mocker.MagicMock()

    order = order_factory(
        order_type="change",
        lines=lines_factory(
            old_quantity=20,
            quantity=10,
        ),
        subscriptions=subscriptions_factory(lines=lines_factory(quantity=20)),
        fulfillment_parameters=fulfillment_parameters_factory(
            customer_id="a-client-id",
        ),
        order_parameters=[],
    )

    mocked_fail_order = mocker.patch("adobe_vipm.flows.fulfillment.shared.fail_order")

    mocked_mpt_client = mocker.MagicMock()

    fulfill_order(mocked_mpt_client, order)

    mocked_fail_order.assert_called_once_with(
        mocked_mpt_client,
        order["id"],
        str(adobe_error),
    )


def test_mixed(
    mocker,
    settings,
    seller,
    agreement,
    order_factory,
    lines_factory,
    fulfillment_parameters_factory,
    subscriptions_factory,
    adobe_order_factory,
    adobe_items_factory,
    adobe_subscription_factory,
):
    """
    Tests a change order in case of upsizing + downsizing + new item + downsizing out of window.
    It includes:
        * return order creation for downsized item
        * Adobe subscription update for downsizing out of window
        * order creation for the three items
        * subscription creation for new item
        * subscription actual sku update for existing upsized items
    """
    settings.EXTENSION_CONFIG["COMPLETED_TEMPLATE_ID"] = "TPL-1111"
    mocker.patch("adobe_vipm.flows.helpers.get_agreement", return_value=agreement)

    adobe_preview_order_items = (
        adobe_items_factory(
            line_number=1,
            offer_id="sku-downsized",
            quantity=8,
        )
        + adobe_items_factory(
            line_number=2,
            offer_id="sku-upsized",
            quantity=12,
        )
        + adobe_items_factory(
            line_number=3,
            offer_id="sku-new",
            quantity=5,
        )
    )

    adobe_order_items = (
        adobe_items_factory(
            line_number=1,
            offer_id="sku-downsized",
            quantity=8,
            subscription_id="sub-1",
        )
        + adobe_items_factory(
            line_number=2,
            offer_id="sku-upsized",
            quantity=12,
            subscription_id="sub-2",
        )
        + adobe_items_factory(
            line_number=3,
            offer_id="sku-new",
            quantity=5,
            subscription_id="sub-3",
        )
    )

    adobe_return_order_items = adobe_items_factory(
        line_number=1,
        offer_id="sku-downsized",
        quantity=10,
    )

    order_to_return = adobe_order_factory(
        ORDER_TYPE_NEW,
        status=STATUS_PROCESSED,
        order_id="P0000000",
    )
    adobe_return_order = adobe_order_factory(
        ORDER_TYPE_RETURN,
        status=STATUS_PROCESSED,
        items=adobe_return_order_items,
    )

    adobe_preview_order = adobe_order_factory(
        ORDER_TYPE_PREVIEW,
        items=adobe_preview_order_items,
    )
    adobe_order = adobe_order_factory(
        ORDER_TYPE_NEW,
        status=STATUS_PROCESSED,
        items=adobe_order_items,
    )

    adobe_sub_downsized_to_update = adobe_subscription_factory(
        subscription_id="sub-1",
        offer_id="sku-downsized",
    )

    adobe_sub_upsized_to_update = adobe_subscription_factory(
        subscription_id="sub-2",
        offer_id="sku-upsized",
    )

    adobe_new_sub = adobe_subscription_factory(
        subscription_id="sub-3",
        offer_id="sku-new",
    )

    adobe_sub_to_update = adobe_subscription_factory(
        subscription_id="sub-4",
        offer_id="sku-downsize-out",
    )

    mocked_adobe_client = mocker.MagicMock()
    mocked_adobe_client.search_new_and_returned_orders_by_sku_line_number.return_value = [
        (order_to_return, order_to_return["lineItems"][0], None),
    ]
    mocked_adobe_client.create_return_order.return_value = adobe_return_order
    mocked_adobe_client.create_preview_order.return_value = adobe_preview_order
    mocked_adobe_client.create_new_order.return_value = adobe_order
    mocked_adobe_client.get_order.return_value = adobe_order
    mocked_adobe_client.create_preview_renewal.return_value = {
        "lineItems": [
            {
                "subscriptionId": "sub-4",
                "offerId": "sku-downsize-out-full-sku",
            },
        ],
    }
    mocked_adobe_client.get_subscription.side_effect = [
        adobe_sub_to_update,
        adobe_sub_downsized_to_update,
        adobe_sub_upsized_to_update,
        adobe_new_sub,
    ]
    mocker.patch(
        "adobe_vipm.flows.fulfillment.change.get_adobe_client",
        return_value=mocked_adobe_client,
    )

    downsizing_items = lines_factory(
        line_id=1,
        old_quantity=10,
        quantity=8,
        external_vendor_id="sku-downsized",
    )
    upsizing_items = lines_factory(
        line_id=2,
        old_quantity=10,
        quantity=12,
        external_vendor_id="sku-upsized",
    )
    new_items = lines_factory(
        line_id=3,
        name="New cool product",
        old_quantity=0,
        quantity=5,
        external_vendor_id="sku-new",
    )

    downsizing_items_out_of_window = lines_factory(
        line_id=4,
        old_quantity=10,
        quantity=8,
        external_vendor_id="sku-downsize-out",
    )

    order_items = (
        upsizing_items + new_items + downsizing_items + downsizing_items_out_of_window
    )

    preview_order_items = upsizing_items + new_items + downsizing_items

    order_subscriptions = (
        subscriptions_factory(
            subscription_id="SUB-001",
            adobe_subscription_id="sub-1",
            lines=lines_factory(
                line_id=1,
                quantity=10,
                external_vendor_id="sku-downsized",
            ),
        )
        + subscriptions_factory(
            subscription_id="SUB-002",
            adobe_subscription_id="sub-2",
            lines=lines_factory(
                line_id=2,
                quantity=10,
                external_vendor_id="sku-upsized",
            ),
        )
        + subscriptions_factory(
            subscription_id="SUB-004",
            adobe_subscription_id="sub-4",
            lines=lines_factory(
                line_id=4,
                quantity=10,
                external_vendor_id="sku-downsize-out",
            ),
            start_date=datetime.now(UTC) - timedelta(days=CANCELLATION_WINDOW_DAYS + 1),
        )
    )

    processing_change_order = order_factory(
        order_type="change",
        lines=order_items,
        fulfillment_parameters=fulfillment_parameters_factory(
            customer_id="a-client-id",
        ),
        order_parameters=[],
        subscriptions=order_subscriptions,
    )

    updated_change_order = order_factory(
        order_type="change",
        lines=order_items,
        subscriptions=order_subscriptions,
        fulfillment_parameters=fulfillment_parameters_factory(
            customer_id="a-client-id",
        ),
        order_parameters=[],
        external_ids={"vendor": adobe_order["orderId"]},
    )

    mocked_mpt_client = mocker.MagicMock()
    mocked_update_order = mocker.patch(
        "adobe_vipm.flows.fulfillment.shared.update_order",
        return_value=updated_change_order,
    )

    mocked_create_subscription = mocker.patch(
        "adobe_vipm.flows.fulfillment.shared.create_subscription",
    )

    mocked_update_subscription = mocker.patch(
        "adobe_vipm.flows.fulfillment.shared.update_subscription",
    )

    mocked_complete_order = mocker.patch(
        "adobe_vipm.flows.fulfillment.shared.complete_order",
    )

    fulfill_order(mocked_mpt_client, processing_change_order)

    seller_country = seller["address"]["country"]

    mocked_adobe_client.create_preview_order.assert_called_once_with(
        seller_country,
        "a-client-id",
        processing_change_order["id"],
        preview_order_items,
    )
    mocked_adobe_client.update_subscription.assert_called_once_with(
        seller_country,
        "a-client-id",
        "sub-4",
        quantity=8,
    )

    assert mocked_update_order.mock_calls[0].args == (
        mocked_mpt_client,
        processing_change_order["id"],
    )
    assert mocked_update_order.mock_calls[0].kwargs == {
        "parameters": processing_change_order["parameters"],
    }

    assert mocked_update_order.mock_calls[1].args == (
        mocked_mpt_client,
        processing_change_order["id"],
    )

    assert mocked_update_order.mock_calls[1].kwargs == {
        "externalIds": {
            "vendor": adobe_order["orderId"],
        },
    }

    mocked_create_subscription.assert_called_once_with(
        mocked_mpt_client,
        processing_change_order["id"],
        {
            "name": "Subscription for New cool product",
            "parameters": {
                "fulfillment": [
                    {
                        "externalId": "adobeSKU",
                        "value": adobe_new_sub["offerId"],
                    },
                ],
            },
            "externalIds": {"vendor": adobe_new_sub["subscriptionId"]},
            "lines": [
                {
                    "id": processing_change_order["lines"][1]["id"],
                },
            ],
            "startDate": adobe_new_sub["creationDate"],
        },
    )

    assert mocked_update_subscription.mock_calls[0].args == (
        mocked_mpt_client,
        processing_change_order["id"],
        order_subscriptions[2]["id"],
    )
    assert mocked_update_subscription.mock_calls[0].kwargs == {
        "parameters": {
            "fulfillment": [
                {
                    "externalId": "adobeSKU",
                    "value": "sku-downsize-out-full-sku",
                },
            ],
        },
    }

    assert mocked_update_subscription.mock_calls[1].args == (
        mocked_mpt_client,
        processing_change_order["id"],
        order_subscriptions[0]["id"],
    )
    assert mocked_update_subscription.mock_calls[1].kwargs == {
        "parameters": {
            "fulfillment": [
                {
                    "externalId": "adobeSKU",
                    "value": adobe_sub_downsized_to_update["offerId"],
                },
            ],
        },
    }

    assert mocked_update_subscription.mock_calls[2].args == (
        mocked_mpt_client,
        processing_change_order["id"],
        order_subscriptions[1]["id"],
    )
    assert mocked_update_subscription.mock_calls[2].kwargs == {
        "parameters": {
            "fulfillment": [
                {
                    "externalId": "adobeSKU",
                    "value": adobe_sub_upsized_to_update["offerId"],
                },
            ],
        },
    }


    mocked_complete_order.assert_called_once_with(
        mocked_mpt_client,
        processing_change_order["id"],
        "TPL-1111",
    )


def test_upsize_of_previously_downsized_out_of_win_without_new_order(
    mocker,
    settings,
    seller,
    agreement,
    order_factory,
    lines_factory,
    fulfillment_parameters_factory,
    subscriptions_factory,
    adobe_subscription_factory,
):
    """
    Tests a change order in case of an upsizing after a previous downsizing change
    order fulfilled outside the cancellation window.
    Only the renewal quantity of the subscription should be updated.
    """
    settings.EXTENSION_CONFIG["COMPLETED_TEMPLATE_ID"] = "TPL-1111"
    mocker.patch("adobe_vipm.flows.helpers.get_agreement", return_value=agreement)

    adobe_sub_to_update = adobe_subscription_factory(
        subscription_id="sub-4",
        current_quantity=18,
        renewal_quantity=10,
    )

    mocked_adobe_client = mocker.MagicMock()

    mocked_adobe_client.get_subscription.return_value = adobe_sub_to_update
    mocker.patch(
        "adobe_vipm.flows.fulfillment.change.get_adobe_client",
        return_value=mocked_adobe_client,
    )

    upsizing_items_out_of_window = lines_factory(
        line_id=4,
        old_quantity=10,
        quantity=18,
    )

    order_subscriptions = subscriptions_factory(
        subscription_id="SUB-004",
        adobe_subscription_id="sub-4",
        lines=lines_factory(
            line_id=4,
            quantity=10,
        ),
        start_date=datetime.now(UTC) - timedelta(days=CANCELLATION_WINDOW_DAYS + 1),
    )

    processing_change_order = order_factory(
        order_type="change",
        lines=upsizing_items_out_of_window,
        fulfillment_parameters=fulfillment_parameters_factory(
            customer_id="a-client-id",
        ),
        order_parameters=[],
        subscriptions=order_subscriptions,
    )

    mocked_mpt_client = mocker.MagicMock()

    mocked_complete_order = mocker.patch(
        "adobe_vipm.flows.fulfillment.shared.complete_order",
    )

    fulfill_order(mocked_mpt_client, processing_change_order)

    seller_country = seller["address"]["country"]

    mocked_adobe_client.update_subscription.assert_called_once_with(
        seller_country,
        "a-client-id",
        "sub-4",
        quantity=18,
    )

    mocked_complete_order.assert_called_once_with(
        mocked_mpt_client,
        processing_change_order["id"],
        "TPL-1111",
    )


def test_upsize_of_previously_downsized_out_of_win_with_new_order(
    mocker,
    settings,
    seller,
    agreement,
    order_factory,
    lines_factory,
    fulfillment_parameters_factory,
    subscriptions_factory,
    adobe_order_factory,
    adobe_items_factory,
    adobe_subscription_factory,
):
    """
    Tests a change order in case of an upsizing after a previous downsizing change
    order fulfilled outside the cancellation window and with a quantity that exceed
    the current.
    The renewal quantity of the subscription should not be updated because of the
    current quantity is equal to the auto renewal.
    """
    settings.EXTENSION_CONFIG["COMPLETED_TEMPLATE_ID"] = "TPL-1111"
    mocker.patch("adobe_vipm.flows.helpers.get_agreement", return_value=agreement)

    adobe_preview_order = adobe_order_factory(
        ORDER_TYPE_PREVIEW,
        items=adobe_items_factory(
            line_number=4,
            quantity=3,
        ),
    )
    adobe_order = adobe_order_factory(
        ORDER_TYPE_NEW,
        status=STATUS_PROCESSED,
        items=adobe_items_factory(
            line_number=4,
            quantity=3,
            subscription_id="sub-4",
        ),
    )

    adobe_sub_to_update = adobe_subscription_factory(
        subscription_id="sub-4",
        current_quantity=18,
        renewal_quantity=18,
    )

    mocked_adobe_client = mocker.MagicMock()
    mocked_adobe_client.create_preview_order.return_value = adobe_preview_order
    mocked_adobe_client.create_new_order.return_value = adobe_order
    mocked_adobe_client.get_order.return_value = adobe_order
    mocked_adobe_client.get_subscription.return_value = adobe_sub_to_update
    mocker.patch(
        "adobe_vipm.flows.fulfillment.change.get_adobe_client",
        return_value=mocked_adobe_client,
    )

    upsizing_items_out_of_window = lines_factory(
        line_id=4,
        old_quantity=10,
        quantity=21,
    )

    order_subscriptions = subscriptions_factory(
        subscription_id="SUB-004",
        adobe_subscription_id="sub-4",
        lines=lines_factory(
            line_id=4,
            quantity=10,
        ),
        start_date=datetime.now(UTC) - timedelta(days=CANCELLATION_WINDOW_DAYS + 1),
    )

    processing_change_order = order_factory(
        order_type="change",
        lines=upsizing_items_out_of_window,
        fulfillment_parameters=fulfillment_parameters_factory(
            customer_id="a-client-id",
        ),
        order_parameters=[],
        subscriptions=order_subscriptions,
    )

    updated_change_order = order_factory(
        order_type="change",
        lines=upsizing_items_out_of_window,
        subscriptions=order_subscriptions,
        fulfillment_parameters=fulfillment_parameters_factory(
            customer_id="a-client-id",
        ),
        order_parameters=[],
        external_ids={"vendor": adobe_order["orderId"]},
    )

    mocked_mpt_client = mocker.MagicMock()

    mocker.patch(
        "adobe_vipm.flows.fulfillment.shared.update_order",
        return_value=updated_change_order,
    )

    mocked_complete_order = mocker.patch(
        "adobe_vipm.flows.fulfillment.shared.complete_order",
    )

    fulfill_order(mocked_mpt_client, processing_change_order)

    seller_country = seller["address"]["country"]

    mocked_adobe_client.create_preview_order.assert_called_once_with(
        seller_country,
        "a-client-id",
        processing_change_order["id"],
        lines_factory(
            line_id=4,
            old_quantity=18,
            quantity=21,
        ),
    )

    mocked_adobe_client.update_subscription.assert_not_called()

    mocked_complete_order.assert_called_once_with(
        mocked_mpt_client,
        processing_change_order["id"],
        "TPL-1111",
    )
