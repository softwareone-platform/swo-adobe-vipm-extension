import pytest

from adobe_vipm.adobe.client import AdobeClient
from adobe_vipm.adobe.dataclasses import ReturnableOrderInfo
from adobe_vipm.adobe.errors import AdobeAPIError
from adobe_vipm.flows.constants import (
    ERR_INVALID_RENEWAL_STATE,
    ERR_INVALID_TERMINATION_ORDER_QUANTITY,
    TEMPLATE_NAME_TERMINATION,
)
from adobe_vipm.flows.context import Context
from adobe_vipm.flows.fulfillment.shared import (
    CompleteOrder,
    GetReturnOrders,
    SetOrUpdateCotermNextSyncDates,
    SetupDueDate,
    StartOrderProcessing,
    SubmitReturnOrders,
    SyncAgreement,
    ValidateRenewalWindow,
)
from adobe_vipm.flows.fulfillment.termination import (
    GetReturnableOrders,
    SwitchAutoRenewalOff,
    fulfill_termination_order,
)
from adobe_vipm.flows.helpers import SetupContext, Validate3YCCommitment


@pytest.mark.parametrize(
    "test_case",
    [
        {
            "name": "successful_case",
            "old_quantity": 7,
            "quantity": 0,
            "adobe_orders_quantities": [1, 2, 4],
            "should_fail": False,
        },
        {
            "name": "failure_case",
            "old_quantity": 7,
            "quantity": 0,
            "adobe_orders_quantities": [1, 2, 3],
            "should_fail": True,
        },
    ],
)
def test_get_returnable_orders_step(
    mocker,
    order_factory,
    lines_factory,
    adobe_customer_factory,
    adobe_order_factory,
    adobe_items_factory,
    test_case,
):
    """
    Tests the retrieval of returnable orders by sku.
    Tests both successful and failure cases where quantities match or don't match.
    """
    order = order_factory(
        lines=lines_factory(
            quantity=test_case["quantity"],
            old_quantity=test_case["old_quantity"],
        )
    )
    adobe_customer = adobe_customer_factory()

    adobe_orders = [
        adobe_order_factory(
            order_type="NEW",
            items=adobe_items_factory(
                quantity=qty,
                subscription_id="6158e1cf0e4414a9b3a06d123969fdNA",
            ),
        )
        for qty in test_case["adobe_orders_quantities"]
    ]

    sku = order["lines"][0]["item"]["externalIds"]["vendor"]

    returnable_orders = [
        ReturnableOrderInfo(
            order,
            order["lineItems"][0],
            order["lineItems"][0]["quantity"],
        )
        for order in adobe_orders
    ]

    sku = order["lines"][0]["item"]["externalIds"]["vendor"]

    mocked_adobe_client = mocker.MagicMock(spec=AdobeClient)
    mocked_adobe_client.get_returnable_orders_by_subscription_id.return_value = returnable_orders

    mocked_switch_to_failed = mocker.patch(
        "adobe_vipm.flows.fulfillment.termination.switch_order_to_failed",
    )

    mocker.patch(
        "adobe_vipm.flows.fulfillment.termination.get_adobe_client",
        return_value=mocked_adobe_client,
    )
    mocked_client = mocker.MagicMock()
    mocked_next_step = mocker.MagicMock()

    mocked_adobe_client.get_subscriptions.return_value = {
        "items": [{"status": "1000", "offerId": sku}]
    }

    context = Context(
        order=order,
        authorization_id=order["authorization"]["id"],
        downsize_lines=order["lines"],
        adobe_customer_id=adobe_customer["customerId"],
        adobe_customer=adobe_customer,
    )

    step = GetReturnableOrders()
    step(mocked_client, context, mocked_next_step)

    mocked_adobe_client.get_subscriptions.assert_called_once_with(
        context.authorization_id,
        context.adobe_customer_id,
    )

    if test_case["should_fail"]:
        mocked_switch_to_failed.assert_called_once_with(
            mocked_client,
            context.order,
            ERR_INVALID_TERMINATION_ORDER_QUANTITY.to_dict(),
        )
        mocked_next_step.assert_not_called()
    else:
        mocked_switch_to_failed.assert_not_called()
        mocked_next_step.assert_called_once_with(mocked_client, context)
        assert context.adobe_returnable_orders[sku] == returnable_orders


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

    mocked_adobe_client = mocker.MagicMock(spec=AdobeClient)
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

    mocked_adobe_client = mocker.MagicMock(spec=AdobeClient)
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

    expected_steps = [
        SetupContext,
        SetupDueDate,
        SetOrUpdateCotermNextSyncDates,
        StartOrderProcessing,
        ValidateRenewalWindow,
        GetReturnOrders,
        GetReturnableOrders,
        Validate3YCCommitment,
        SubmitReturnOrders,
        CompleteOrder,
        SyncAgreement,
    ]

    actual_steps = [type(step) for step in mocked_pipeline_ctor.mock_calls[0].args]
    assert actual_steps == expected_steps
    assert mocked_pipeline_ctor.mock_calls[0].args[3].template_name == TEMPLATE_NAME_TERMINATION
    assert mocked_pipeline_ctor.mock_calls[0].args[9].template_name == TEMPLATE_NAME_TERMINATION

    mocked_context_ctor.assert_called_once_with(order=mocked_order)
    mocked_pipeline_instance.run.assert_called_once_with(
        mocked_client,
        mocked_context,
    )


def test_switch_autorenewal_off_invalid_renwal_state(
    mocker,
    order_factory,
    lines_factory,
    subscriptions_factory,
    adobe_subscription_factory,
    adobe_api_error_factory,
):
    subscriptions = subscriptions_factory()
    order = order_factory(
        lines=lines_factory(quantity=10),
        subscriptions=subscriptions,
    )

    adobe_sub = adobe_subscription_factory(
        renewal_quantity=10,
    )
    mocked_switch_to_failed = mocker.patch(
        "adobe_vipm.flows.fulfillment.termination.switch_order_to_failed",
    )
    mocked_adobe_client = mocker.MagicMock(spec=AdobeClient)
    mocked_adobe_client.get_subscription.return_value = adobe_sub
    mocker.patch(
        "adobe_vipm.flows.fulfillment.termination.get_adobe_client",
        return_value=mocked_adobe_client,
    )
    mocked_adobe_client.update_subscription.side_effect = AdobeAPIError(
        400,
        adobe_api_error_factory(
            "3120",
            "Update could not be performed because it would create an invalid renewal state",
        ),
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
    mocked_switch_to_failed.assert_called_once_with(
        mocked_client,
        context.order,
        ERR_INVALID_RENEWAL_STATE.to_dict(
            error="Update could not be performed because it would create an invalid renewal state",
        ),
    )


def test_switch_autorenewal_off_error_updating_autorenew(
    mocker,
    order_factory,
    lines_factory,
    subscriptions_factory,
    adobe_subscription_factory,
    adobe_api_error_factory,
):
    subscriptions = subscriptions_factory()
    order = order_factory(
        lines=lines_factory(quantity=10),
        subscriptions=subscriptions,
    )

    adobe_sub = adobe_subscription_factory(
        renewal_quantity=10,
    )
    mocked_switch_to_failed = mocker.patch(
        "adobe_vipm.flows.fulfillment.termination.switch_order_to_failed",
    )
    mocked_adobe_client = mocker.MagicMock(spec=AdobeClient)
    mocked_adobe_client.get_subscription.return_value = adobe_sub
    mocker.patch(
        "adobe_vipm.flows.fulfillment.termination.get_adobe_client",
        return_value=mocked_adobe_client,
    )
    mocked_adobe_client.update_subscription.side_effect = AdobeAPIError(
        400,
        adobe_api_error_factory(
            "1000",
            "Error updating autorenewal",
        ),
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
    mocked_switch_to_failed.assert_not_called()


def test_get_returnable_orders_step_inactive_subscription(
    mocker,
    order_factory,
    lines_factory,
    adobe_customer_factory,
):
    """
    Tests the GetReturnableOrders step when the subscription is inactive.
    """
    order = order_factory(
        lines=lines_factory(
            quantity=0,
            old_quantity=7,
        )
    )
    adobe_customer = adobe_customer_factory()
    sku = order["lines"][0]["item"]["externalIds"]["vendor"]

    mocked_adobe_client = mocker.MagicMock(spec=AdobeClient)
    mocked_adobe_client.get_subscriptions.return_value = {
        "items": [{"status": "INACTIVE", "offerId": sku}]
    }

    mocked_switch_to_failed = mocker.patch(
        "adobe_vipm.flows.fulfillment.termination.switch_order_to_failed",
    )

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

    mocked_adobe_client.get_subscriptions.assert_called_once_with(
        context.authorization_id,
        context.adobe_customer_id,
    )
    mocked_adobe_client.get_returnable_orders_by_subscription_id.assert_not_called()
    mocked_next_step.assert_called_once_with(mocked_client, context)
    mocked_switch_to_failed.assert_not_called()


def test_get_returnable_orders_step_no_returnable_orders(
    mocker,
    order_factory,
    lines_factory,
    adobe_customer_factory,
):
    """
    Tests the GetReturnableOrders step when there are no returnable orders.
    """
    order = order_factory(
        lines=lines_factory(
            quantity=0,
            old_quantity=7,
        )
    )
    adobe_customer = adobe_customer_factory()
    sku = order["lines"][0]["item"]["externalIds"]["vendor"]

    mocked_adobe_client = mocker.MagicMock(spec=AdobeClient)
    mocked_adobe_client.get_subscriptions.return_value = {
        "items": [{"status": "1000", "offerId": sku}]
    }
    mocked_adobe_client.get_returnable_orders_by_subscription_id.return_value = []

    mocked_switch_to_failed = mocker.patch(
        "adobe_vipm.flows.fulfillment.termination.switch_order_to_failed",
    )

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

    mocked_adobe_client.get_subscriptions.assert_called_once_with(
        context.authorization_id,
        context.adobe_customer_id,
    )

    mocked_adobe_client.get_returnable_orders_by_subscription_id.assert_called_once_with(
        context.authorization_id,
        context.adobe_customer_id,
        "6158e1cf0e4414a9b3a06d123969fdNA",
        context.adobe_customer["cotermDate"],
        return_orders=context.adobe_return_orders.get(sku),
    )

    mocked_switch_to_failed.assert_called_once_with(
        mocked_client,
        context.order,
        ERR_INVALID_TERMINATION_ORDER_QUANTITY.to_dict(),
    )
    mocked_next_step.assert_not_called()
