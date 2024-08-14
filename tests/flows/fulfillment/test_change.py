from adobe_vipm.adobe.dataclasses import ReturnableOrderInfo
from adobe_vipm.flows.constants import (
    TEMPLATE_NAME_CHANGE,
)
from adobe_vipm.flows.context import Context
from adobe_vipm.flows.fulfillment.change import (
    GetReturnableOrders,
    UpdateRenewalQuantities,
    ValidateDuplicateLines,
    ValidateReturnableOrders,
    fulfill_change_order,
)
from adobe_vipm.flows.fulfillment.shared import (
    CompleteOrder,
    CreateOrUpdateSubscriptions,
    GetReturnOrders,
    IncrementAttemptsCounter,
    SendEmailNotification,
    SetOrUpdateCotermNextSyncDates,
    SetProcessingTemplate,
    SubmitNewOrder,
    SubmitReturnOrders,
    SyncAgreement,
    UpdatePrices,
    ValidateRenewalWindow,
)
from adobe_vipm.flows.helpers import SetupContext


def test_get_returnable_orders_step(
    mocker,
    order_factory,
    lines_factory,
    adobe_customer_factory,
    adobe_order_factory,
    adobe_items_factory,
):
    """
    Tests the computation of the map of returnable orders by sku/quantity.
    """
    order = order_factory(
        lines=lines_factory(
            quantity=3,
            old_quantity=7,
        )
    )
    adobe_customer = adobe_customer_factory()
    adobe_order_1 = adobe_order_factory(
        order_type="NEW",
        items=adobe_items_factory(quantity=1),
    )
    adobe_order_2 = adobe_order_factory(
        order_type="NEW",
        items=adobe_items_factory(quantity=2),
    )
    adobe_order_3 = adobe_order_factory(
        order_type="NEW",
        items=adobe_items_factory(quantity=4),
    )

    ret_info_1 = ReturnableOrderInfo(
        adobe_order_1,
        adobe_order_1["lineItems"][0],
        adobe_order_1["lineItems"][0]["quantity"],
    )
    ret_info_2 = ReturnableOrderInfo(
        adobe_order_2,
        adobe_order_2["lineItems"][0],
        adobe_order_2["lineItems"][0]["quantity"],
    )
    ret_info_3 = ReturnableOrderInfo(
        adobe_order_3,
        adobe_order_3["lineItems"][0],
        adobe_order_3["lineItems"][0]["quantity"],
    )

    sku = order["lines"][0]["item"]["externalIds"]["vendor"]

    mocked_adobe_client = mocker.MagicMock()
    mocked_adobe_client.get_returnable_orders_by_sku.return_value = [
        ret_info_1,
        ret_info_2,
        ret_info_3,
    ]

    mocker.patch(
        "adobe_vipm.flows.fulfillment.change.get_adobe_client",
        return_value=mocked_adobe_client,
    )
    mocked_client = mocker.MagicMock()
    mocked_next_step = mocker.MagicMock()

    context = Context(
        order=order,
        authorization_id=order["authorization"]["id"],
        downsize_lines=order["lines"],
        adobe_customer_id=adobe_customer["customerId"],
        adobe_customer=adobe_customer,
    )

    step = GetReturnableOrders()
    step(mocked_client, context, mocked_next_step)

    assert context.adobe_returnable_orders[sku] == (ret_info_3,)
    mocked_adobe_client.get_returnable_orders_by_sku.assert_called_once_with(
        context.authorization_id,
        context.adobe_customer_id,
        sku,
        customer_coterm_date=context.adobe_customer["cotermDate"],
    )
    mocked_next_step.assert_called_once_with(mocked_client, context)


def test_get_returnable_orders_step_quantity_mismatch(
    mocker,
    order_factory,
    lines_factory,
    adobe_customer_factory,
    adobe_order_factory,
    adobe_items_factory,
):
    """
    Tests the computation of the map of returnable orders by sku/quantity.
    Since the quantity doesn't match any of the sums of the avaibale returnable
    orders for such sku the value have to be None.
    """
    order = order_factory(
        lines=lines_factory(
            quantity=7,
            old_quantity=16,
        )
    )
    adobe_customer = adobe_customer_factory()
    adobe_order_1 = adobe_order_factory(
        order_type="NEW",
        items=adobe_items_factory(quantity=1),
    )
    adobe_order_2 = adobe_order_factory(
        order_type="NEW",
        items=adobe_items_factory(quantity=2),
    )
    adobe_order_3 = adobe_order_factory(
        order_type="NEW",
        items=adobe_items_factory(quantity=4),
    )

    ret_info_1 = ReturnableOrderInfo(
        adobe_order_1,
        adobe_order_1["lineItems"][0],
        adobe_order_1["lineItems"][0]["quantity"],
    )
    ret_info_2 = ReturnableOrderInfo(
        adobe_order_2,
        adobe_order_2["lineItems"][0],
        adobe_order_2["lineItems"][0]["quantity"],
    )
    ret_info_3 = ReturnableOrderInfo(
        adobe_order_3,
        adobe_order_3["lineItems"][0],
        adobe_order_3["lineItems"][0]["quantity"],
    )

    sku = order["lines"][0]["item"]["externalIds"]["vendor"]

    mocked_adobe_client = mocker.MagicMock()
    mocked_adobe_client.get_returnable_orders_by_sku.return_value = [
        ret_info_1,
        ret_info_2,
        ret_info_3,
    ]

    mocker.patch(
        "adobe_vipm.flows.fulfillment.change.get_adobe_client",
        return_value=mocked_adobe_client,
    )
    mocked_client = mocker.MagicMock()
    mocked_next_step = mocker.MagicMock()

    context = Context(
        order=order,
        authorization_id=order["authorization"]["id"],
        downsize_lines=order["lines"],
        adobe_customer_id=adobe_customer["customerId"],
        adobe_customer=adobe_customer,
    )

    step = GetReturnableOrders()
    step(mocked_client, context, mocked_next_step)

    assert context.adobe_returnable_orders[sku] is None
    mocked_adobe_client.get_returnable_orders_by_sku.assert_called_once_with(
        context.authorization_id,
        context.adobe_customer_id,
        sku,
        customer_coterm_date=context.adobe_customer["cotermDate"],
    )
    mocked_next_step.assert_called_once_with(mocked_client, context)


def test_validate_returnable_orders_step(mocker, order_factory):
    """
    Tests the validate returnable orders step when all downsize SKUs
    have returnable orders. The order processing pipeline will continue.
    """
    mocked_switch_to_failed = mocker.patch(
        "adobe_vipm.flows.fulfillment.change.switch_order_to_failed",
    )

    context = Context(
        order=order_factory(),
        adobe_returnable_orders={
            "sku1": (mocker.MagicMock(),),
            "sku2": (mocker.MagicMock(),),
        },
    )
    mocked_client = mocker.MagicMock()
    mocked_next_step = mocker.MagicMock()

    step = ValidateReturnableOrders()
    step(mocked_client, context, mocked_next_step)

    mocked_switch_to_failed.assert_not_called()
    mocked_next_step.assert_called_once_with(mocked_client, context)


def test_validate_returnable_orders_step_invalid(mocker, order_factory):
    """
    Tests the validate returnable orders step when at least one downsize SKU
    have no returnable orders. The order processing pipeline will stop.
    """
    mocked_switch_to_failed = mocker.patch(
        "adobe_vipm.flows.fulfillment.change.switch_order_to_failed",
    )

    context = Context(
        order=order_factory(),
        adobe_returnable_orders={
            "sku1": (mocker.MagicMock(),),
            "sku2": None,
        },
    )
    mocked_client = mocker.MagicMock()
    mocked_next_step = mocker.MagicMock()

    step = ValidateReturnableOrders()
    step(mocked_client, context, mocked_next_step)

    mocked_switch_to_failed.assert_called_once_with(
        mocked_client,
        context.order,
        "No Adobe orders that match the desired quantity delta have been found for the "
        "following SKUs: sku2",
    )
    mocked_next_step.assert_not_called()


def test_validate_duplicate_lines_step(
    mocker,
    order_factory,
    lines_factory,
):
    order = order_factory(
        order_type="Change",
        lines=lines_factory() + lines_factory(),
    )
    mocked_fail = mocker.patch(
        "adobe_vipm.flows.fulfillment.change.switch_order_to_failed",
    )

    mocked_client = mocker.MagicMock()
    mocked_next_step = mocker.MagicMock()

    context = Context(order=order, order_id=order["id"])

    step = ValidateDuplicateLines()
    step(mocked_client, context, mocked_next_step)

    mocked_fail.assert_called_once_with(
        mocked_client,
        context.order,
        "The order cannot contain multiple lines for the same item: ITM-1234-1234-1234-0001.",
    )
    mocked_next_step.assert_not_called()


def test_validate_duplicate_lines_step_existing_item(
    mocker,
    order_factory,
    lines_factory,
):
    order = order_factory(
        order_type="Change",
        lines=lines_factory(line_id=2, item_id=10),
    )
    mocked_fail = mocker.patch(
        "adobe_vipm.flows.fulfillment.change.switch_order_to_failed",
    )

    mocked_client = mocker.MagicMock()
    mocked_next_step = mocker.MagicMock()

    context = Context(order=order, order_id=order["id"])

    step = ValidateDuplicateLines()
    step(mocked_client, context, mocked_next_step)

    mocked_fail.assert_called_once_with(
        mocked_client,
        context.order,
        "The order cannot contain new lines for an existing item: ITM-1234-1234-1234-0010.",
    )
    mocked_next_step.assert_not_called()


def test_validate_duplicate_lines_step_no_duplicates(
    mocker,
    order_factory,
):
    order = order_factory(
        order_type="Change",
    )
    mocked_fail = mocker.patch(
        "adobe_vipm.flows.fulfillment.change.switch_order_to_failed",
    )

    mocked_client = mocker.MagicMock()
    mocked_next_step = mocker.MagicMock()

    context = Context(order=order, order_id=order["id"])

    step = ValidateDuplicateLines()
    step(mocked_client, context, mocked_next_step)

    mocked_fail.assert_not_called()
    mocked_next_step.assert_called_once_with(mocked_client, context)


def test_update_renewal_quantities_step(
    mocker,
    order_factory,
    lines_factory,
    subscriptions_factory,
    adobe_subscription_factory,
):
    subscriptions = subscriptions_factory()
    order = order_factory(
        lines=lines_factory(quantity=5)
        + lines_factory(line_id=2, item_id=2, external_vendor_id="99999999CA"),
        subscriptions=subscriptions,
    )

    adobe_sub = adobe_subscription_factory(
        renewal_quantity=10,
    )

    mocked_adobe_client = mocker.MagicMock()
    mocked_adobe_client.get_subscription.return_value = adobe_sub
    mocker.patch(
        "adobe_vipm.flows.fulfillment.change.get_adobe_client",
        return_value=mocked_adobe_client,
    )

    mocked_client = mocker.MagicMock()
    mocked_next_step = mocker.MagicMock()

    context = Context(
        order=order,
        order_id=order["id"],
        upsize_lines=order["lines"],
        authorization_id="auth-id",
        adobe_customer_id="adobe-customer-id",
    )

    step = UpdateRenewalQuantities()
    step(mocked_client, context, mocked_next_step)

    mocked_adobe_client.get_subscription.assert_called_once_with(
        context.authorization_id,
        context.adobe_customer_id,
        adobe_sub["subscriptionId"],
    )
    mocked_adobe_client.update_subscription.assert_called_once_with(
        context.authorization_id,
        context.adobe_customer_id,
        adobe_sub["subscriptionId"],
        quantity=5,
    )
    mocked_next_step.assert_called_once_with(mocked_client, context)


def test_update_renewal_quantities_step_quantity_match(
    mocker,
    order_factory,
    lines_factory,
    subscriptions_factory,
    adobe_subscription_factory,
):
    subscriptions = subscriptions_factory()
    order = order_factory(
        lines=lines_factory(quantity=10),
        subscriptions=subscriptions,
    )

    adobe_sub = adobe_subscription_factory(
        renewal_quantity=10,
    )

    mocked_adobe_client = mocker.MagicMock()
    mocked_adobe_client.get_subscription.return_value = adobe_sub
    mocker.patch(
        "adobe_vipm.flows.fulfillment.change.get_adobe_client",
        return_value=mocked_adobe_client,
    )

    mocked_client = mocker.MagicMock()
    mocked_next_step = mocker.MagicMock()

    context = Context(
        order=order,
        order_id=order["id"],
        upsize_lines=order["lines"],
        authorization_id="auth-id",
        adobe_customer_id="adobe-customer-id",
    )

    step = UpdateRenewalQuantities()
    step(mocked_client, context, mocked_next_step)

    mocked_adobe_client.get_subscription.assert_called_once_with(
        context.authorization_id,
        context.adobe_customer_id,
        adobe_sub["subscriptionId"],
    )
    mocked_adobe_client.update_subscription.assert_not_called()
    mocked_next_step.assert_called_once_with(mocked_client, context)


def test_fulfill_change_order(mocker):
    """
    Tests the change order pipeline is created with the
    expected steps and executed.
    """
    mocked_pipeline_instance = mocker.MagicMock()

    mocked_pipeline_ctor = mocker.patch(
        "adobe_vipm.flows.fulfillment.change.Pipeline",
        return_value=mocked_pipeline_instance,
    )
    mocked_context = mocker.MagicMock()
    mocked_context_ctor = mocker.patch(
        "adobe_vipm.flows.fulfillment.change.Context", return_value=mocked_context
    )
    mocked_client = mocker.MagicMock()
    mocked_order = mocker.MagicMock()

    fulfill_change_order(mocked_client, mocked_order)
    assert len(mocked_pipeline_ctor.mock_calls[0].args) == 18

    assert isinstance(mocked_pipeline_ctor.mock_calls[0].args[0], SetupContext)
    assert isinstance(
        mocked_pipeline_ctor.mock_calls[0].args[1], IncrementAttemptsCounter
    )
    assert isinstance(
        mocked_pipeline_ctor.mock_calls[0].args[2], ValidateDuplicateLines
    )
    assert isinstance(
        mocked_pipeline_ctor.mock_calls[0].args[3], SetOrUpdateCotermNextSyncDates
    )
    assert isinstance(mocked_pipeline_ctor.mock_calls[0].args[4], SetProcessingTemplate)
    assert (
        mocked_pipeline_ctor.mock_calls[0].args[4].template_name == TEMPLATE_NAME_CHANGE
    )
    assert isinstance(mocked_pipeline_ctor.mock_calls[0].args[5], ValidateRenewalWindow)
    assert isinstance(mocked_pipeline_ctor.mock_calls[0].args[6], SendEmailNotification)
    assert isinstance(mocked_pipeline_ctor.mock_calls[0].args[7], GetReturnableOrders)
    assert isinstance(mocked_pipeline_ctor.mock_calls[0].args[8], GetReturnOrders)
    assert isinstance(
        mocked_pipeline_ctor.mock_calls[0].args[9], ValidateReturnableOrders
    )
    assert isinstance(mocked_pipeline_ctor.mock_calls[0].args[10], SubmitReturnOrders)
    assert isinstance(mocked_pipeline_ctor.mock_calls[0].args[11], SubmitNewOrder)
    assert isinstance(
        mocked_pipeline_ctor.mock_calls[0].args[12], UpdateRenewalQuantities
    )
    assert isinstance(
        mocked_pipeline_ctor.mock_calls[0].args[13], CreateOrUpdateSubscriptions
    )
    assert isinstance(mocked_pipeline_ctor.mock_calls[0].args[14], UpdatePrices)
    assert isinstance(mocked_pipeline_ctor.mock_calls[0].args[15], CompleteOrder)
    assert (
        mocked_pipeline_ctor.mock_calls[0].args[15].template_name
        == TEMPLATE_NAME_CHANGE
    )
    assert isinstance(
        mocked_pipeline_ctor.mock_calls[0].args[16], SendEmailNotification
    )
    assert isinstance(mocked_pipeline_ctor.mock_calls[0].args[17], SyncAgreement)
    mocked_context_ctor.assert_called_once_with(order=mocked_order)
    mocked_pipeline_instance.run.assert_called_once_with(
        mocked_client,
        mocked_context,
    )
