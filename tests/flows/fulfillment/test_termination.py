from adobe_vipm.adobe.dataclasses import ReturnableOrderInfo
from adobe_vipm.flows.constants import TEMPLATE_NAME_TERMINATION
from adobe_vipm.flows.context import Context
from adobe_vipm.flows.fulfillment.shared import (
    CompleteOrder,
    GetReturnOrders,
    IncrementAttemptsCounter,
    SendEmailNotification,
    SetOrUpdateCotermNextSyncDates,
    SetProcessingTemplate,
    SubmitReturnOrders,
    ValidateRenewalWindow,
)
from adobe_vipm.flows.fulfillment.termination import (
    GetReturnableOrders,
    SwitchAutoRenewalOff,
    fulfill_termination_order,
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
    Tests the retrieval of returnable orders by sku.
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
        "adobe_vipm.flows.fulfillment.termination.get_adobe_client",
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

    assert context.adobe_returnable_orders[sku] == [ret_info_1, ret_info_2, ret_info_3]
    mocked_adobe_client.get_returnable_orders_by_sku.assert_called_once_with(
        context.authorization_id,
        context.adobe_customer_id,
        sku,
    )
    mocked_next_step.assert_called_once_with(mocked_client, context)


def test_switch_autorenewal_off(
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
        "adobe_vipm.flows.fulfillment.termination.get_adobe_client",
        return_value=mocked_adobe_client,
    )

    mocked_client = mocker.MagicMock()
    mocked_next_step = mocker.MagicMock()

    context = Context(
        order=order,
        order_id=order["id"],
        downsize_lines=order["lines"],
        authorization_id="auth-id",
        adobe_customer_id="adobe-customer-id",
    )

    step = SwitchAutoRenewalOff()
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
        auto_renewal=False,
    )
    mocked_next_step.assert_called_once_with(mocked_client, context)


def test_switch_autorenewal_off_already_off(
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
        autorenewal_enabled=False,
    )

    mocked_adobe_client = mocker.MagicMock()
    mocked_adobe_client.get_subscription.return_value = adobe_sub
    mocker.patch(
        "adobe_vipm.flows.fulfillment.termination.get_adobe_client",
        return_value=mocked_adobe_client,
    )

    mocked_client = mocker.MagicMock()
    mocked_next_step = mocker.MagicMock()

    context = Context(
        order=order,
        order_id=order["id"],
        downsize_lines=order["lines"],
        authorization_id="auth-id",
        adobe_customer_id="adobe-customer-id",
    )

    step = SwitchAutoRenewalOff()
    step(mocked_client, context, mocked_next_step)

    mocked_adobe_client.get_subscription.assert_called_once_with(
        context.authorization_id,
        context.adobe_customer_id,
        adobe_sub["subscriptionId"],
    )
    mocked_adobe_client.update_subscription.assert_not_called()
    mocked_next_step.assert_called_once_with(mocked_client, context)


def test_fulfill_termination_order(mocker):
    """
    Tests the termination order pipeline is created with the
    expected steps and executed.
    """
    mocked_pipeline_instance = mocker.MagicMock()

    mocked_pipeline_ctor = mocker.patch(
        "adobe_vipm.flows.fulfillment.termination.Pipeline",
        return_value=mocked_pipeline_instance,
    )
    mocked_context = mocker.MagicMock()
    mocked_context_ctor = mocker.patch(
        "adobe_vipm.flows.fulfillment.termination.Context", return_value=mocked_context
    )
    mocked_client = mocker.MagicMock()
    mocked_order = mocker.MagicMock()

    fulfill_termination_order(mocked_client, mocked_order)
    assert len(mocked_pipeline_ctor.mock_calls[0].args) == 12

    assert isinstance(mocked_pipeline_ctor.mock_calls[0].args[0], SetupContext)
    assert isinstance(
        mocked_pipeline_ctor.mock_calls[0].args[1], IncrementAttemptsCounter
    )
    assert isinstance(
        mocked_pipeline_ctor.mock_calls[0].args[2], SetOrUpdateCotermNextSyncDates
    )
    assert isinstance(mocked_pipeline_ctor.mock_calls[0].args[3], SetProcessingTemplate)
    assert (
        mocked_pipeline_ctor.mock_calls[0].args[3].template_name == TEMPLATE_NAME_TERMINATION
    )
    assert isinstance(mocked_pipeline_ctor.mock_calls[0].args[4], ValidateRenewalWindow)
    assert isinstance(mocked_pipeline_ctor.mock_calls[0].args[5], SendEmailNotification)
    assert isinstance(mocked_pipeline_ctor.mock_calls[0].args[6], GetReturnableOrders)
    assert isinstance(mocked_pipeline_ctor.mock_calls[0].args[7], GetReturnOrders)
    assert isinstance(mocked_pipeline_ctor.mock_calls[0].args[8], SubmitReturnOrders)
    assert isinstance(mocked_pipeline_ctor.mock_calls[0].args[9], SwitchAutoRenewalOff)
    assert isinstance(mocked_pipeline_ctor.mock_calls[0].args[10], CompleteOrder)
    assert (
        mocked_pipeline_ctor.mock_calls[0].args[10].template_name
        == TEMPLATE_NAME_TERMINATION
    )
    assert isinstance(
        mocked_pipeline_ctor.mock_calls[0].args[11], SendEmailNotification
    )
    mocked_context_ctor.assert_called_once_with(order=mocked_order)
    mocked_pipeline_instance.run.assert_called_once_with(
        mocked_client,
        mocked_context,
    )
