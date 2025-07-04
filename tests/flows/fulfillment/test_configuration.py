from adobe_vipm.adobe.errors import AdobeError
from adobe_vipm.flows.constants import ERR_ADOBE_SUBSCRIPTION_UPDATE_ERROR
from adobe_vipm.flows.context import Context
from adobe_vipm.flows.fulfillment.configuration import (
    SubscriptionUpdateAutoRenewal,
    fulfill_configuration_order,
)
from adobe_vipm.flows.fulfillment.shared import SyncAgreement
from adobe_vipm.flows.pipeline import Step


def test_subscription_update_auto_renewal_step(
    mocker,
    order_factory,
    subscriptions_factory,
    adobe_subscription_factory,
):
    """
    Test the successful update of auto renewal status for a subscription.
    """
    subscriptions = subscriptions_factory()
    order = order_factory(
        subscriptions=subscriptions,
    )

    adobe_sub = adobe_subscription_factory(
        subscription_id=subscriptions[0]["externalIds"]["vendor"],
        renewal_quantity=10,
        autorenewal_enabled=False,
    )

    mocked_adobe_client = mocker.MagicMock()
    mocked_adobe_client.get_subscription.return_value = adobe_sub
    mocker.patch(
        "adobe_vipm.flows.fulfillment.configuration.get_adobe_client",
        return_value=mocked_adobe_client,
    )

    mocked_client = mocker.MagicMock()
    mocked_next_step = mocker.MagicMock()

    context = Context(order=order, adobe_customer_id="adobe-customer-id")

    step = SubscriptionUpdateAutoRenewal()
    step(mocked_client, context, mocked_next_step)

    mocked_adobe_client.get_subscription.assert_called_once_with(
        order["authorization"]["id"],
        context.adobe_customer_id,
        subscriptions[0]["externalIds"]["vendor"],
    )

    mocked_adobe_client.update_subscription.assert_called_once_with(
        order["authorization"]["id"],
        context.adobe_customer_id,
        adobe_sub["subscriptionId"],
        auto_renewal=subscriptions[0]["autoRenew"],
        quantity=subscriptions[0]["lines"][0]["quantity"],
    )
    mocked_next_step.assert_called_once_with(mocked_client, context)


def test_subscription_update_auto_renewal_step_no_matching_subscription(
    mocker,
    order_factory,
    subscriptions_factory,
):
    """
    Test the case when no matching Adobe subscription is found.
    """
    subscriptions = subscriptions_factory()
    order = order_factory(
        subscriptions=subscriptions,
    )

    mocked_adobe_client = mocker.MagicMock()
    mocked_adobe_client.get_subscription.return_value = None
    mocker.patch(
        "adobe_vipm.flows.fulfillment.configuration.get_adobe_client",
        return_value=mocked_adobe_client,
    )

    mocked_notify = mocker.patch(
        "adobe_vipm.flows.fulfillment.configuration.notify_not_updated_subscriptions"
    )
    mocked_switch_to_failed = mocker.patch(
        "adobe_vipm.flows.fulfillment.configuration.switch_order_to_failed"
    )

    mocked_client = mocker.MagicMock()
    mocked_next_step = mocker.MagicMock()

    context = Context(
        order=order, product_id="PRD-1111-1111", adobe_customer_id="adobe-customer-id"
    )

    step = SubscriptionUpdateAutoRenewal()
    step(mocked_client, context, mocked_next_step)

    mocked_adobe_client.get_subscription.assert_called_once_with(
        order["authorization"]["id"],
        context.adobe_customer_id,
        subscriptions[0]["externalIds"]["vendor"],
    )
    mocked_adobe_client.update_subscription.assert_not_called()

    error_message = f"No Adobe subscription for vendor {subscriptions[0]["externalIds"]["vendor"]}"

    mocked_notify.assert_called_once_with(
        order["id"],
        f"No Adobe subscription for vendor {subscriptions[0]["externalIds"]["vendor"]}",
        [],
        context.product_id,
    )
    mocked_switch_to_failed.assert_called_once_with(
        mocked_client,
        order,
        ERR_ADOBE_SUBSCRIPTION_UPDATE_ERROR.to_dict(error=error_message),
    )
    mocked_next_step.assert_not_called()


def test_subscription_update_auto_renewal_step_already_updated(
    mocker,
    order_factory,
    subscriptions_factory,
    adobe_subscription_factory,
):
    """
    Test the case when the subscription already has the desired auto renewal status.
    """
    subscriptions = subscriptions_factory()
    order = order_factory(
        subscriptions=subscriptions,
    )

    adobe_sub = adobe_subscription_factory(
        subscription_id=subscriptions[0]["externalIds"]["vendor"],
        renewal_quantity=subscriptions[0]["lines"][0]["quantity"],
        autorenewal_enabled=subscriptions[0]["autoRenew"],
    )

    mocked_adobe_client = mocker.MagicMock()
    mocked_adobe_client.get_subscription.return_value = adobe_sub
    mocker.patch(
        "adobe_vipm.flows.fulfillment.configuration.get_adobe_client",
        return_value=mocked_adobe_client,
    )

    mocked_client = mocker.MagicMock()
    mocked_next_step = mocker.MagicMock()

    context = Context(order=order, adobe_customer_id="adobe-customer-id")

    step = SubscriptionUpdateAutoRenewal()
    step(mocked_client, context, mocked_next_step)

    mocked_adobe_client.get_subscription.assert_called_once_with(
        order["authorization"]["id"],
        context.adobe_customer_id,
        subscriptions[0]["externalIds"]["vendor"],
    )
    mocked_adobe_client.update_subscription.assert_not_called()
    mocked_next_step.assert_called_once_with(mocked_client, context)


def test_subscription_update_auto_renewal_step_error(
    mocker,
    order_factory,
    subscriptions_factory,
    adobe_subscription_factory,
):
    """
    Test the case when an error occurs while updating the subscription.
    """
    subscriptions = subscriptions_factory()
    order = order_factory(
        subscriptions=subscriptions,
    )

    adobe_sub = adobe_subscription_factory(
        subscription_id=subscriptions[0]["externalIds"]["vendor"],
        renewal_quantity=10,
        autorenewal_enabled=False,
    )
    error = AdobeError("Update error")
    mocked_adobe_client = mocker.MagicMock()
    mocked_adobe_client.get_subscription.return_value = adobe_sub
    mocked_adobe_client.update_subscription.side_effect = error
    mocker.patch(
        "adobe_vipm.flows.fulfillment.configuration.get_adobe_client",
        return_value=mocked_adobe_client,
    )

    mocked_notify = mocker.patch(
        "adobe_vipm.flows.fulfillment.configuration.notify_not_updated_subscriptions"
    )

    mocked_switch_to_failed = mocker.patch(
        "adobe_vipm.flows.fulfillment.configuration.switch_order_to_failed"
    )

    mocked_client = mocker.MagicMock()
    mocked_next_step = mocker.MagicMock()

    context = Context(
        order=order, product_id="PRD-1111-1111", adobe_customer_id="adobe-customer-id"
    )

    step = SubscriptionUpdateAutoRenewal()
    step(mocked_client, context, mocked_next_step)

    mocked_adobe_client.get_subscription.assert_called_once_with(
        order["authorization"]["id"],
        context.adobe_customer_id,
        subscriptions[0]["externalIds"]["vendor"],
    )
    mocked_adobe_client.update_subscription.assert_called_once_with(
        order["authorization"]["id"],
        context.adobe_customer_id,
        adobe_sub["subscriptionId"],
        auto_renewal=subscriptions[0]["autoRenew"],
        quantity=subscriptions[0]["lines"][0]["quantity"],
    )

    assert mocked_notify.call_count == 1
    call_args = mocked_notify.call_args[0]
    assert call_args[0] == order["id"]
    assert call_args[3] == context.product_id

    assert mocked_switch_to_failed.call_count == 1
    call_args = mocked_switch_to_failed.call_args[0]
    assert call_args[0] == mocked_client
    assert call_args[1] == order

    mocked_next_step.assert_not_called()


def test_subscription_update_auto_renewal_step_all_failed(
    mocker,
    order_factory,
    subscriptions_factory,
):
    """
    Test the case when all subscription updates fail.
    """
    subscriptions = subscriptions_factory()
    order = order_factory(
        subscriptions=subscriptions,
    )

    mocked_adobe_client = mocker.MagicMock()
    mocked_adobe_client.get_subscription.return_value = None
    mocker.patch(
        "adobe_vipm.flows.fulfillment.configuration.get_adobe_client",
        return_value=mocked_adobe_client,
    )

    mocked_notify = mocker.patch(
        "adobe_vipm.flows.fulfillment.configuration.notify_not_updated_subscriptions"
    )
    mocked_switch_to_failed = mocker.patch(
        "adobe_vipm.flows.fulfillment.configuration.switch_order_to_failed"
    )

    mocked_client = mocker.MagicMock()
    mocked_next_step = mocker.MagicMock()

    context = Context(
        order=order, product_id="PRD-1111-1111", adobe_customer_id="adobe-customer-id"
    )

    step = SubscriptionUpdateAutoRenewal()
    step(mocked_client, context, mocked_next_step)

    mocked_adobe_client.get_subscription.assert_called_once_with(
        order["authorization"]["id"],
        context.adobe_customer_id,
        subscriptions[0]["externalIds"]["vendor"],
    )
    mocked_adobe_client.update_subscription.assert_not_called()

    error_message = f"No Adobe subscription for vendor {subscriptions[0]["externalIds"]["vendor"]}"

    mocked_notify.assert_called_once_with(
        order["id"],
        f"No Adobe subscription for vendor {subscriptions[0]["externalIds"]["vendor"]}",
        [],
        context.product_id,
    )
    mocked_switch_to_failed.assert_called_once_with(
        mocked_client,
        order,
        ERR_ADOBE_SUBSCRIPTION_UPDATE_ERROR.to_dict(error=error_message),
    )

    mocked_next_step.assert_not_called()


def test_subscription_update_auto_renewal_step_rollback_on_partial_failure(
    mocker,
    order_factory,
    subscriptions_factory,
    adobe_subscription_factory,
):
    """
    Test rollback is triggered when one subscription update succeeds and a subsequent one fails.
    """

    subscriptions1 = subscriptions_factory()
    subscriptions2 = subscriptions_factory()
    subscriptions1[0]["externalIds"]["vendor"] = "a-sub-id_1"
    subscriptions2[0]["externalIds"]["vendor"] = "a-sub-id_2"
    subscriptions = [subscriptions1[0], subscriptions2[0]]

    order = order_factory(subscriptions=subscriptions)

    adobe_sub_1 = adobe_subscription_factory(
        subscription_id="a-sub-id_1",
        renewal_quantity=10,
        autorenewal_enabled=False,
    )
    adobe_sub_2 = adobe_subscription_factory(
        subscription_id="a-sub-id_2",
        renewal_quantity=5,
        autorenewal_enabled=False,
    )

    mocked_adobe_client = mocker.MagicMock()

    mocked_adobe_client.get_subscription.side_effect = [
        adobe_sub_1,
        adobe_sub_2,
    ]

    mocked_adobe_client.update_subscription.side_effect = [
        None,
        AdobeError("Update error on second subscription"),
        None,
    ]

    mocker.patch(
        "adobe_vipm.flows.fulfillment.configuration.get_adobe_client",
        return_value=mocked_adobe_client,
    )

    mocked_notify = mocker.patch(
        "adobe_vipm.flows.fulfillment.configuration.notify_not_updated_subscriptions"
    )
    mocked_switch_to_failed = mocker.patch(
        "adobe_vipm.flows.fulfillment.configuration.switch_order_to_failed"
    )

    mocked_client = mocker.MagicMock()
    mocked_next_step = mocker.MagicMock()

    context = Context(order=order, product_id="PRD-1111-1111")

    step = SubscriptionUpdateAutoRenewal()
    step(mocked_client, context, mocked_next_step)

    assert mocked_adobe_client.update_subscription.call_count == 3  # 2 updates + 1 rollback

    first_update_call = mocked_adobe_client.update_subscription.call_args_list[0]
    assert first_update_call == mocker.call(
        order["authorization"]["id"],
        context.adobe_customer_id,
        adobe_sub_1["subscriptionId"],
        auto_renewal=subscriptions[0]["autoRenew"],
        quantity=subscriptions[0]["lines"][0]["quantity"],
    )

    second_update_call = mocked_adobe_client.update_subscription.call_args_list[1]
    assert second_update_call == mocker.call(
        order["authorization"]["id"],
        context.adobe_customer_id,
        adobe_sub_2["subscriptionId"],
        auto_renewal=subscriptions[1]["autoRenew"],
        quantity=subscriptions[1]["lines"][0]["quantity"],
    )

    rollback_call = mocked_adobe_client.update_subscription.call_args_list[2]
    assert rollback_call == mocker.call(
        order["authorization"]["id"],
        context.adobe_customer_id,
        adobe_sub_1["subscriptionId"],
        auto_renewal=not subscriptions[0]["autoRenew"],
        quantity=subscriptions[0]["lines"][0]["quantity"],
    )

    mocked_notify.assert_called_once()
    mocked_switch_to_failed.assert_called_once()
    mocked_next_step.assert_not_called()


def test_fulfill_configuration_order(mocker):
    """
    Test the configuration order pipeline is created with the expected steps and executed.
    """
    mocked_pipeline_instance = mocker.MagicMock()

    mocked_pipeline_ctor = mocker.patch(
        "adobe_vipm.flows.fulfillment.configuration.Pipeline",
        return_value=mocked_pipeline_instance,
    )
    mocked_context = mocker.MagicMock()
    mocked_context_ctor = mocker.patch(
        "adobe_vipm.flows.fulfillment.configuration.Context",
        return_value=mocked_context,
    )
    mocked_client = mocker.MagicMock()
    mocked_order = mocker.MagicMock()

    fulfill_configuration_order(mocked_client, mocked_order)

    assert len(mocked_pipeline_ctor.mock_calls[0].args) == 8

    expected_steps = [
        Step,
        Step,
        Step,
        Step,
        Step,
        SubscriptionUpdateAutoRenewal,
        Step,
        SyncAgreement,
    ]
    actual_steps = list(mocked_pipeline_ctor.mock_calls[0].args)

    for actual, expected in zip(actual_steps, expected_steps):
        assert isinstance(actual, expected)

    mocked_context_ctor.assert_called_once_with(order=mocked_order)
    mocked_pipeline_instance.run.assert_called_once_with(
        mocked_client,
        mocked_context,
    )
