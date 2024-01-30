from adobe_vipm.adobe.constants import (
    ORDER_TYPE_NEW,
    ORDER_TYPE_PREVIEW,
    ORDER_TYPE_RETURN,
    STATUS_PENDING,
    STATUS_PROCESSED,
)
from adobe_vipm.adobe.errors import AdobeError
from adobe_vipm.flows.fulfillment import fulfill_order


def test_upsizing(
    mocker,
    settings,
    agreement,
    seller,
    order_factory,
    items_factory,
    fulfillment_parameters_factory,
    subscriptions_factory,
    adobe_order_factory,
    adobe_items_factory,
):
    """
    Tests a change order in case of upsizing.
    """
    settings.EXTENSION_CONFIG["COMPLETED_TEMPLATE_ID"] = "TPL-1111"
    mocker.patch("adobe_vipm.flows.fulfillment.get_agreement", return_value=agreement)
    mocked_get_seller = mocker.patch(
        "adobe_vipm.flows.fulfillment.get_seller",
        return_value=seller,
    )

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
        "adobe_vipm.flows.fulfillment.get_adobe_client",
        return_value=mocked_adobe_client,
    )

    processing_change_order = order_factory(
        order_type="Change",
        items=items_factory(
            old_quantity=10,
            quantity=20,
        ),
        fulfillment_parameters=fulfillment_parameters_factory(
            customer_id="a-client-id",
        ),
        order_parameters=[],
    )

    subscriptions = subscriptions_factory(items=items_factory(quantity=10))

    updated_change_order = order_factory(
        order_type="Change",
        items=items_factory(
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
        "adobe_vipm.flows.fulfillment.update_order",
        return_value=updated_change_order,
    )

    mocked_complete_order = mocker.patch(
        "adobe_vipm.flows.fulfillment.complete_order",
    )
    mocker.patch(
        "adobe_vipm.flows.fulfillment.get_order_subscriptions",
        return_value=subscriptions,
    )

    fulfill_order(mocked_mpt_client, processing_change_order)

    seller_country = seller["address"]["country"]

    mocked_get_seller.assert_called_once_with(mocked_mpt_client, seller["id"])
    mocked_adobe_client.create_preview_order.assert_called_once_with(
        seller_country,
        "a-client-id",
        processing_change_order,
    )

    assert mocked_update_order.mock_calls[0].args == (
        mocked_mpt_client,
        processing_change_order["id"],
        {
            "externalIDs": {
                "vendor": adobe_order["orderId"],
            },
        },
    )
    assert mocked_update_order.mock_calls[1].args == (
        mocked_mpt_client,
        processing_change_order["id"],
        {
            "parameters": {
                "fulfillment": fulfillment_parameters_factory(
                    customer_id="a-client-id",
                    retry_count="0",
                ),
                "order": [],
            },
        },
    )

    mocked_complete_order.assert_called_once_with(
        mocked_mpt_client,
        processing_change_order["id"],
        "TPL-1111",
    )


def test_upsizing_order_already_created_adobe_order_not_ready(
    mocker,
    agreement,
    seller,
    order_factory,
    items_factory,
    fulfillment_parameters_factory,
    adobe_order_factory,
):
    """
    Tests the processing of an change order (upsizing) that has been placed in the previous
    attemp and still pending.
    """
    mocker.patch("adobe_vipm.flows.fulfillment.get_agreement", return_value=agreement)
    mocked_get_seller = mocker.patch(
        "adobe_vipm.flows.fulfillment.get_seller",
        return_value=seller,
    )
    mocked_update_order = mocker.patch(
        "adobe_vipm.flows.fulfillment.update_order",
    )
    mocked_complete_order = mocker.patch(
        "adobe_vipm.flows.fulfillment.complete_order",
    )

    adobe_order = adobe_order_factory(ORDER_TYPE_NEW, status=STATUS_PENDING)

    mocked_adobe_client = mocker.MagicMock()
    mocked_adobe_client.get_order.return_value = adobe_order
    mocker.patch(
        "adobe_vipm.flows.fulfillment.get_adobe_client",
        return_value=mocked_adobe_client,
    )
    mocked_mpt_client = mocker.MagicMock()

    order = order_factory(
        order_type="Change",
        items=items_factory(
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

    mocked_get_seller.assert_called_once_with(mocked_mpt_client, seller["id"])
    mocked_adobe_client.get_subscription.assert_not_called()
    mocked_update_order.assert_called_once_with(
        mocked_mpt_client,
        order["id"],
        {
            "parameters": {
                "fulfillment": fulfillment_parameters_factory(
                    retry_count="1",
                    customer_id="a-client-id",
                ),
                "order": [],
            }
        },
    )
    mocked_complete_order.assert_not_called()


def test_upsizing_create_adobe_preview_order_error(
    mocker,
    seller,
    order_factory,
    items_factory,
    fulfillment_parameters_factory,
    adobe_api_error_factory,
):
    """
    Tests the processing of a change order (upsizing) when the Adobe preview order
    creation fails. The change order will be failed.
    """
    mocker.patch(
        "adobe_vipm.flows.fulfillment.get_seller",
        return_value=seller,
    )

    adobe_error = AdobeError(
        adobe_api_error_factory("9999", "Error while creating a preview order")
    )

    mocked_adobe_client = mocker.MagicMock()
    mocked_adobe_client.create_preview_order.side_effect = adobe_error
    mocker.patch(
        "adobe_vipm.flows.fulfillment.get_adobe_client",
        return_value=mocked_adobe_client,
    )

    mocked_fail_order = mocker.patch("adobe_vipm.flows.fulfillment.fail_order")

    mocked_mpt_client = mocker.MagicMock()

    order = order_factory(
        order_type="Change",
        items=items_factory(
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
    agreement,
    seller,
    order_factory,
    items_factory,
    fulfillment_parameters_factory,
    subscriptions_factory,
    adobe_order_factory,
    adobe_items_factory,
    adobe_subscription_factory,
):
    """
    Tests the processing of a change order (downsizing) including:
        * search adobe last order by sku that must be referenced in return order
        * adobe return order creation
        * adobe preview order creation
        * adobe new order creation
        * order completion
    """
    settings.EXTENSION_CONFIG["COMPLETED_TEMPLATE_ID"] = "TPL-1111"
    mocker.patch("adobe_vipm.flows.fulfillment.get_agreement", return_value=agreement)
    mocked_get_seller = mocker.patch(
        "adobe_vipm.flows.fulfillment.get_seller",
        return_value=seller,
    )

    last_adobe_order_for_sku = adobe_order_factory(
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
    mocked_adobe_client.search_last_order_by_sku.return_value = last_adobe_order_for_sku
    mocked_adobe_client.search_last_return_order_by_order.return_value = None
    mocked_adobe_client.create_return_order.return_value = adobe_return_order
    mocked_adobe_client.create_preview_order.return_value = adobe_preview_order
    mocked_adobe_client.create_new_order.return_value = adobe_order
    mocked_adobe_client.get_order.return_value = adobe_order
    mocker.patch(
        "adobe_vipm.flows.fulfillment.get_adobe_client",
        return_value=mocked_adobe_client,
    )

    subscriptions = subscriptions_factory(items=items_factory(quantity=20))

    updated_order = order_factory(
        order_type="Change",
        items=items_factory(
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
        order_type="Change",
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
    mocked_update_order = mocker.patch(
        "adobe_vipm.flows.fulfillment.update_order",
        return_value=updated_order,
    )

    mocked_complete_order = mocker.patch(
        "adobe_vipm.flows.fulfillment.complete_order",
    )
    mocker.patch(
        "adobe_vipm.flows.fulfillment.get_order_subscriptions",
        return_value=subscriptions,
    )

    fulfill_order(mocked_mpt_client, processing_order)

    seller_country = seller["address"]["country"]

    mocked_get_seller.assert_called_once_with(mocked_mpt_client, seller["id"])
    mocked_adobe_client.create_return_order.assert_called_once_with(
        seller_country,
        "a-client-id",
        last_adobe_order_for_sku["orderId"],
        processing_order,
        items_factory(old_quantity=20, quantity=10)[0],
    )

    assert mocked_update_order.mock_calls[0].args == (
        mocked_mpt_client,
        processing_order["id"],
        {
            "externalIDs": {
                "vendor": adobe_order["orderId"],
            },
        },
    )

    mocked_complete_order.assert_called_once_with(
        mocked_mpt_client,
        processing_order["id"],
        "TPL-1111",
    )


def test_downsizing_return_order_exists(
    mocker,
    settings,
    agreement,
    seller,
    order_factory,
    items_factory,
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
    mocker.patch("adobe_vipm.flows.fulfillment.get_agreement", return_value=agreement)
    mocked_get_seller = mocker.patch(
        "adobe_vipm.flows.fulfillment.get_seller",
        return_value=seller,
    )

    last_adobe_order_for_sku = adobe_order_factory(
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
    mocked_adobe_client.search_last_order_by_sku.return_value = last_adobe_order_for_sku
    mocked_adobe_client.search_last_return_order_by_order.return_value = adobe_return_order
    mocked_adobe_client.create_new_order.return_value = adobe_order
    mocked_adobe_client.get_order.return_value = adobe_order
    mocked_adobe_client.get_subscription.return_value = adobe_subscription

    mocker.patch(
        "adobe_vipm.flows.fulfillment.get_adobe_client",
        return_value=mocked_adobe_client,
    )

    processing_order = order_factory(
        order_type="Change",
        items=items_factory(
            old_quantity=20,
            quantity=10,
        ),
        fulfillment_parameters=fulfillment_parameters_factory(
            customer_id="a-client-id",
        ),
        order_parameters=[],
    )

    subscriptions = subscriptions_factory(items=items_factory(quantity=20))

    updated_order = order_factory(
        order_type="Change",
        items=items_factory(
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
        "adobe_vipm.flows.fulfillment.update_order",
        return_value=updated_order,
    )
    mocked_complete_order = mocker.patch(
        "adobe_vipm.flows.fulfillment.complete_order",
    )
    mocker.patch(
        "adobe_vipm.flows.fulfillment.get_order_subscriptions",
        return_value=subscriptions,
    )

    fulfill_order(mocked_mpt_client, processing_order)

    mocked_get_seller.assert_called_once_with(mocked_mpt_client, seller["id"])

    assert mocked_update_order.mock_calls[0].args == (
        mocked_mpt_client,
        processing_order["id"],
        {
            "externalIDs": {
                "vendor": adobe_order["orderId"],
            },
        },
    )

    mocked_complete_order.assert_called_once_with(
        mocked_mpt_client,
        processing_order["id"],
        "TPL-1111",
    )
    mocked_adobe_client.create_return_order.assert_not_called()


def test_downsizing_return_order_pending(
    mocker,
    agreement,
    seller,
    order_factory,
    items_factory,
    fulfillment_parameters_factory,
    adobe_order_factory,
):
    """
    Tests the processing of a change order (downsizing) when the return order
    has already been created in Adobe but it is still pending.
    The return order will not be placed again.
    The new order will not be placed yet.
    """
    mocker.patch("adobe_vipm.flows.fulfillment.get_agreement", return_value=agreement)
    mocked_get_seller = mocker.patch(
        "adobe_vipm.flows.fulfillment.get_seller",
        return_value=seller,
    )

    last_adobe_order_for_sku = adobe_order_factory(
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
    mocked_adobe_client.search_last_order_by_sku.return_value = last_adobe_order_for_sku
    mocked_adobe_client.search_last_return_order_by_order.return_value = adobe_return_order

    mocker.patch(
        "adobe_vipm.flows.fulfillment.get_adobe_client",
        return_value=mocked_adobe_client,
    )
    mocked_mpt_client = mocker.MagicMock()
    mocked_update_order = mocker.patch(
        "adobe_vipm.flows.fulfillment.update_order",
    )
    mocked_complete_order = mocker.patch(
        "adobe_vipm.flows.fulfillment.complete_order",
    )

    order = order_factory(
        order_type="Change",
        items=items_factory(
            old_quantity=20,
            quantity=10,
        ),
        fulfillment_parameters=fulfillment_parameters_factory(
            customer_id="a-client-id",
        ),
        order_parameters=[],
    )

    fulfill_order(mocked_mpt_client, order)

    mocked_get_seller.assert_called_once_with(mocked_mpt_client, seller["id"])
    mocked_update_order.assert_called_once_with(
        mocked_mpt_client,
        order["id"],
        {
            "parameters": {
                "fulfillment": fulfillment_parameters_factory(
                    retry_count="1",
                    customer_id="a-client-id",
                ),
                "order": [],
            },
        },
    )
    mocked_complete_order.assert_not_called()
    mocked_adobe_client.create_return_order.assert_not_called()


def test_downsizing_new_order_pending(
    mocker,
    agreement,
    seller,
    order_factory,
    items_factory,
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
    mocker.patch("adobe_vipm.flows.fulfillment.get_agreement", return_value=agreement)
    mocked_get_seller = mocker.patch(
        "adobe_vipm.flows.fulfillment.get_seller",
        return_value=seller,
    )

    adobe_order = adobe_order_factory(
        ORDER_TYPE_NEW,
        status=STATUS_PENDING,
    )

    mocked_adobe_client = mocker.MagicMock()
    mocked_adobe_client.get_order.return_value = adobe_order
    mocker.patch(
        "adobe_vipm.flows.fulfillment.get_adobe_client",
        return_value=mocked_adobe_client,
    )
    mocked_mpt_client = mocker.MagicMock()

    order = order_factory(
        order_type="Change",
        items=items_factory(
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
        "adobe_vipm.flows.fulfillment.update_order",
        return_value=order,
    )

    mocked_complete_order = mocker.patch(
        "adobe_vipm.flows.fulfillment.complete_order",
    )

    fulfill_order(mocked_mpt_client, order)

    mocked_get_seller.assert_called_once_with(mocked_mpt_client, seller["id"])
    mocked_adobe_client.create_return_order.assert_not_called()
    mocked_complete_order.assert_not_called()
    mocked_update_order.assert_called_once_with(
        mocked_mpt_client,
        order["id"],
        {
            "parameters": {
                "fulfillment": fulfillment_parameters_factory(
                    retry_count="1",
                    customer_id="a-client-id",
                ),
                "order": [],
            },
        },
    )


def test_downsizing_create_new_order_error(
    mocker,
    settings,
    seller,
    order_factory,
    items_factory,
    fulfillment_parameters_factory,
    adobe_order_factory,
    adobe_api_error_factory,
):
    """
    Tests the processing of a change order (downsizing) when the create new order
    returns an error.

    """
    settings.EXTENSION_CONFIG["COMPLETED_TEMPLATE_ID"] = "TPL-1111"
    mocker.patch(
        "adobe_vipm.flows.fulfillment.get_seller",
        return_value=seller,
    )

    last_adobe_order_for_sku = adobe_order_factory(
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
    mocked_adobe_client.search_last_order_by_sku.return_value = last_adobe_order_for_sku
    mocked_adobe_client.search_last_return_order_by_order.return_value = None
    mocked_adobe_client.create_return_order.return_value = adobe_return_order
    mocked_adobe_client.create_new_order.side_effect = adobe_error

    mocker.patch(
        "adobe_vipm.flows.fulfillment.get_adobe_client",
        return_value=mocked_adobe_client,
    )
    mocked_mpt_client = mocker.MagicMock()

    order = order_factory(
        order_type="Change",
        items=items_factory(
            old_quantity=20,
            quantity=10,
        ),
        fulfillment_parameters=fulfillment_parameters_factory(
            customer_id="a-client-id",
        ),
        order_parameters=[],
    )

    mocked_fail_order = mocker.patch("adobe_vipm.flows.fulfillment.fail_order")

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
    agreement,
    seller,
    order_factory,
    items_factory,
    fulfillment_parameters_factory,
    subscriptions_factory,
    adobe_order_factory,
    adobe_items_factory,
    adobe_subscription_factory,
):
    """
    Tests a change order in case of upsizing + downsizing + new item. It includes:
        * return order creation for downsized item
        * order creation for the three items
        * subscription creation for new item
    """
    settings.EXTENSION_CONFIG["COMPLETED_TEMPLATE_ID"] = "TPL-1111"
    mocker.patch("adobe_vipm.flows.fulfillment.get_agreement", return_value=agreement)
    mocked_get_seller = mocker.patch(
        "adobe_vipm.flows.fulfillment.get_seller",
        return_value=seller,
    )

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

    last_adobe_order_for_sku = adobe_order_factory(
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

    adobe_new_sub = adobe_subscription_factory(
        subscription_id="sub-3",
        offer_id="sku-new",
    )

    mocked_adobe_client = mocker.MagicMock()
    mocked_adobe_client.search_last_order_by_sku.return_value = last_adobe_order_for_sku
    mocked_adobe_client.search_last_return_order_by_order.return_value = None
    mocked_adobe_client.create_return_order.return_value = adobe_return_order
    mocked_adobe_client.create_preview_order.return_value = adobe_preview_order
    mocked_adobe_client.create_new_order.return_value = adobe_order
    mocked_adobe_client.get_order.return_value = adobe_order
    mocked_adobe_client.get_subscription.return_value = adobe_new_sub
    mocker.patch(
        "adobe_vipm.flows.fulfillment.get_adobe_client",
        return_value=mocked_adobe_client,
    )

    order_items = (
        items_factory(
            line_number=1,
            product_item_id="sku-downsized",
            old_quantity=10,
            quantity=8,
        )
        + items_factory(
            line_number=2,
            product_item_id="sku-upsized",
            old_quantity=10,
            quantity=12,
        )
        + items_factory(
            line_number=3,
            product_item_id="sku-new",
            name="New cool product",
            old_quantity=0,
            quantity=5,
        )
    )

    order_subscriptions = subscriptions_factory(
        subscription_id="SUB-001",
        adobe_subscription_id="sub-1",
        items=items_factory(
            line_number=1,
            product_item_id="sku-downsized",
            quantity=10,
        ),
    ) + subscriptions_factory(
        subscription_id="SUB-002",
        adobe_subscription_id="sub-2",
        items=items_factory(
            line_number=2,
            product_item_id="sku-upsized",
            quantity=10,
        ),
    )

    processing_change_order = order_factory(
        order_type="Change",
        items=order_items,
        fulfillment_parameters=fulfillment_parameters_factory(
            customer_id="a-client-id",
        ),
        order_parameters=[],
        subscriptions=order_subscriptions,
    )

    updated_change_order = order_factory(
        order_type="Change",
        items=order_items,
        subscriptions=order_subscriptions,
        fulfillment_parameters=fulfillment_parameters_factory(
            customer_id="a-client-id",
        ),
        order_parameters=[],
        external_ids={"vendor": adobe_order["orderId"]},
    )

    mocked_mpt_client = mocker.MagicMock()
    mocked_update_order = mocker.patch(
        "adobe_vipm.flows.fulfillment.update_order",
        return_value=updated_change_order,
    )

    mocked_create_subscription = mocker.patch(
        "adobe_vipm.flows.fulfillment.create_subscription",
    )

    mocked_complete_order = mocker.patch(
        "adobe_vipm.flows.fulfillment.complete_order",
    )
    mocker.patch(
        "adobe_vipm.flows.fulfillment.get_order_subscriptions",
        return_value=order_subscriptions,
    )

    fulfill_order(mocked_mpt_client, processing_change_order)

    seller_country = seller["address"]["country"]

    mocked_get_seller.assert_called_once_with(mocked_mpt_client, seller["id"])
    mocked_adobe_client.create_preview_order.assert_called_once_with(
        seller_country,
        "a-client-id",
        processing_change_order,
    )

    assert mocked_update_order.mock_calls[0].args == (
        mocked_mpt_client,
        processing_change_order["id"],
        {
            "externalIDs": {
                "vendor": adobe_order["orderId"],
            },
        },
    )

    mocked_create_subscription.assert_called_once_with(
        mocked_mpt_client,
        processing_change_order["id"],
        {
            "name": "Subscription for New cool product",
            "parameters": {
                "fulfillment": [
                    {
                        "name": "SubscriptionId",
                        "value": adobe_new_sub["subscriptionId"],
                    },
                ],
            },
            "items": [
                {
                    "lineNumber": 3,
                },
            ],
            "startDate": adobe_new_sub["creationDate"],
        },
    )

    mocked_complete_order.assert_called_once_with(
        mocked_mpt_client,
        processing_change_order["id"],
        "TPL-1111",
    )
