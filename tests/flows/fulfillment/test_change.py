from adobe_vipm.adobe.constants import AdobeErrorCode, AdobeOrderStatus
from adobe_vipm.adobe.errors import AdobeAPIError
from adobe_vipm.flows.constants import (
    ERR_INVALID_RENEWAL_STATE,
    TEMPLATE_NAME_CHANGE,
)
from adobe_vipm.flows.context import Context
from adobe_vipm.flows.fulfillment.change import (
    UpdateRenewalQuantities,
    UpdateRenewalQuantitiesDownsizes,
    ValidateDuplicateLines,
    fulfill_change_order,
)
from adobe_vipm.flows.fulfillment.downsize_returns import (
    PlanDownsizeReturns,
    SubmitReturnAllocations,
)
from adobe_vipm.flows.fulfillment.renewal import RecordDiscountRedemptions
from adobe_vipm.flows.fulfillment.shared import (
    CheckManualRenewalSubscriptions,
    CompleteOrder,
    CreateOrUpdateAssets,
    CreateOrUpdateSubscriptions,
    GetPreviewOrder,
    GetReturnOrders,
    NullifyFlexDiscountParam,
    PreviewRenewalOrders,
    SelectFlexDiscounts,
    SetOrUpdateCotermDate,
    SetSubscriptionTemplate,
    SetupDueDate,
    StartOrderProcessing,
    SubmitNewOrder,
    SubmitRenewalOrders,
    SyncAgreement,
    UpdateAgreementParamsVisibility,
    ValidateRenewalWindow,
)
from adobe_vipm.flows.helpers import (
    SetupContext,
    UpdatePrices,
    Validate3YCCommitment,
    ValidateSkuAvailability,
)


def test_update_renewal_quantities_step(
    mocker,
    mock_adobe_client,
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
    adobe_sub = adobe_subscription_factory(renewal_quantity=10)
    mock_adobe_client.get_subscription.return_value = adobe_sub
    mocked_client = mocker.MagicMock()
    mocked_next_step = mocker.MagicMock()
    context = Context(
        order=order,
        order_id=order["id"],
        upsize_lines=order["lines"],
        downsize_lines=order["lines"],
        authorization_id="auth-id",
        adobe_customer_id="adobe-customer-id",
    )
    step = UpdateRenewalQuantities()

    step(mocked_client, context, mocked_next_step)  # act

    mock_adobe_client.get_subscription.assert_called_once_with(
        context.authorization_id,
        context.adobe_customer_id,
        adobe_sub["subscriptionId"],
    )
    mock_adobe_client.update_subscription.assert_called_once_with(
        context.authorization_id,
        context.adobe_customer_id,
        adobe_sub["subscriptionId"],
        quantity=5,
    )
    mocked_next_step.assert_called_once_with(mocked_client, context)


def test_update_renewal_quantities_downsize_step(
    mocker,
    mock_adobe_client,
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
    adobe_sub = adobe_subscription_factory(renewal_quantity=10)
    mock_adobe_client.get_subscription.return_value = adobe_sub
    mocked_client = mocker.MagicMock()
    mocked_next_step = mocker.MagicMock()
    context = Context(
        order=order,
        order_id=order["id"],
        upsize_lines=order["lines"],
        downsize_lines=order["lines"],
        authorization_id="auth-id",
        adobe_customer_id="adobe-customer-id",
    )
    step = UpdateRenewalQuantitiesDownsizes()

    step(mocked_client, context, mocked_next_step)  # act

    mock_adobe_client.get_subscription.assert_called_once_with(
        context.authorization_id,
        context.adobe_customer_id,
        adobe_sub["subscriptionId"],
    )
    mock_adobe_client.update_subscription.assert_called_once_with(
        context.authorization_id, context.adobe_customer_id, adobe_sub["subscriptionId"], quantity=5
    )
    mocked_next_step.assert_called_once_with(mocked_client, context)


def test_update_renewal_quantities_step_quantity_match(
    mocker,
    mock_adobe_client,
    order_factory,
    lines_factory,
    subscriptions_factory,
    adobe_subscription_factory,
):
    subscriptions = subscriptions_factory()
    order = order_factory(lines=lines_factory(quantity=10), subscriptions=subscriptions)
    adobe_sub = adobe_subscription_factory(renewal_quantity=10)
    mock_adobe_client.get_subscription.return_value = adobe_sub
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

    step(mocked_client, context, mocked_next_step)  # act

    mock_adobe_client.get_subscription.assert_called_once_with(
        context.authorization_id,
        context.adobe_customer_id,
        adobe_sub["subscriptionId"],
    )
    mock_adobe_client.update_subscription.assert_not_called()
    mocked_next_step.assert_called_once_with(mocked_client, context)


def test_fulfill_change_order(mocker):
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

    fulfill_change_order(mocked_client, mocked_order)  # act

    expected_steps = [
        SetupContext,
        StartOrderProcessing,
        SetupDueDate,
        ValidateDuplicateLines,
        SetOrUpdateCotermDate,
        UpdateAgreementParamsVisibility,
        ValidateRenewalWindow,
        ValidateSkuAvailability,
        GetReturnOrders,
        CheckManualRenewalSubscriptions,
        Validate3YCCommitment,
        PlanDownsizeReturns,
        SelectFlexDiscounts,
        GetPreviewOrder,
        UpdatePrices,
        PreviewRenewalOrders,
        SubmitRenewalOrders,
        SubmitNewOrder,
        UpdateRenewalQuantities,
        SubmitReturnAllocations,
        UpdateRenewalQuantitiesDownsizes,
        CreateOrUpdateAssets,
        CreateOrUpdateSubscriptions,
        CompleteOrder,
        SetSubscriptionTemplate,
        RecordDiscountRedemptions,
        NullifyFlexDiscountParam,
        SyncAgreement,
    ]
    pipeline_args = mocked_pipeline_ctor.mock_calls[0].args
    assert len(pipeline_args) == len(expected_steps)
    actual_steps = [type(step) for step in mocked_pipeline_ctor.mock_calls[0].args]
    assert actual_steps == expected_steps
    assert pipeline_args[1].template_name == TEMPLATE_NAME_CHANGE
    assert pipeline_args[23].template_name == TEMPLATE_NAME_CHANGE
    mocked_context_ctor.assert_called_once_with(order=mocked_order)
    mocked_pipeline_instance.run.assert_called_once_with(mocked_client, mocked_context)


def test_validate_update_renewal_quantity_invalid_renewal_state(
    order_factory,
    adobe_subscription_factory,
    adobe_api_error_factory,
    subscriptions_factory,
    lines_factory,
    mock_mpt_client,
    mock_adobe_client,
    mock_switch_order_to_failed,
    mock_notify_not_updated_subscriptions,
    mock_next_step,
):
    subscriptions = subscriptions_factory()
    order = order_factory(
        lines=lines_factory(quantity=5)
        + lines_factory(line_id=2, item_id=2, external_vendor_id="99999999CA"),
        subscriptions=subscriptions,
    )
    context = Context(
        order=order,
        order_id=order["id"],
        upsize_lines=order["lines"],
        authorization_id="auth-id",
        adobe_customer_id="adobe-customer-id",
    )
    adobe_sub = adobe_subscription_factory(renewal_quantity=10)
    mock_adobe_client.get_subscription.return_value = adobe_sub
    mock_adobe_client.update_subscription.side_effect = AdobeAPIError(
        400,
        adobe_api_error_factory(
            AdobeErrorCode.INACTIVE_SUBSCRIPTION_NOT_EDITABLE.value,
            "Inactive Subscription or Pending Renewal is not Editable",
        ),
    )
    step = UpdateRenewalQuantities()

    step(mock_mpt_client, context, mock_next_step)  # act

    mock_switch_order_to_failed.assert_called_once_with(
        mock_mpt_client,
        context.order,
        ERR_INVALID_RENEWAL_STATE.to_dict(
            error="Inactive Subscription or Pending Renewal is not Editable",
        ),
    )
    mock_notify_not_updated_subscriptions.assert_called_once()
    mock_next_step.assert_not_called()


def test_validate_update_renewal_quantity_invalid_renewal_state_ok(
    order_factory,
    adobe_subscription_factory,
    adobe_api_error_factory,
    subscriptions_factory,
    lines_factory,
    mock_mpt_client,
    mock_adobe_client,
    mock_switch_order_to_failed,
    mock_notify_not_updated_subscriptions,
    mock_next_step,
):
    subscriptions = subscriptions_factory()
    order = order_factory(
        lines=lines_factory(quantity=15)
        + lines_factory(line_id=2, item_id=2, external_vendor_id="99999999CA"),
        subscriptions=subscriptions,
    )
    context = Context(
        order=order,
        order_id=order["id"],
        upsize_lines=order["lines"],
        authorization_id="auth-id",
        adobe_customer_id="adobe-customer-id",
    )
    adobe_sub = adobe_subscription_factory(renewal_quantity=10)
    mock_adobe_client.get_subscription.return_value = adobe_sub
    mock_adobe_client.update_subscription.side_effect = AdobeAPIError(
        400,
        adobe_api_error_factory(
            AdobeErrorCode.INVALID_RENEWAL_STATE.value,
            "Update could not be performed because it would create an invalid renewal state",
        ),
    )
    step = UpdateRenewalQuantities()

    step(mock_mpt_client, context, mock_next_step)  # act

    mock_switch_order_to_failed.assert_not_called()
    mock_notify_not_updated_subscriptions.assert_not_called()
    mock_next_step.assert_called()


def test_validate_update_renewal_quantity_invalid_renewal_state_order_ok(
    order_factory,
    adobe_subscription_factory,
    adobe_api_error_factory,
    adobe_order_factory,
    subscriptions_factory,
    lines_factory,
    mock_mpt_client,
    mock_adobe_client,
    mock_switch_order_to_failed,
    mock_notify_not_updated_subscriptions,
    mock_next_step,
):
    subscriptions = subscriptions_factory()
    order = order_factory(
        lines=lines_factory(quantity=15)
        + lines_factory(line_id=2, item_id=2, external_vendor_id="99999999CA"),
        subscriptions=subscriptions,
    )
    context = Context(
        order=order,
        order_id=order["id"],
        upsize_lines=order["lines"],
        authorization_id="auth-id",
        adobe_customer_id="adobe-customer-id",
        adobe_new_order=adobe_order_factory(
            order_type="NEW",
            status=AdobeOrderStatus.COMPLETE.value,
        ),
    )
    adobe_sub = adobe_subscription_factory(renewal_quantity=10)
    mock_adobe_client.get_subscription.return_value = adobe_sub
    mock_adobe_client.update_subscription.side_effect = AdobeAPIError(
        400,
        adobe_api_error_factory(
            AdobeErrorCode.INVALID_RENEWAL_STATE.value,
            "Update could not be performed because it would create an invalid renewal state",
        ),
    )
    step = UpdateRenewalQuantities()

    step(mock_mpt_client, context, mock_next_step)  # act

    mock_switch_order_to_failed.assert_not_called()
    mock_notify_not_updated_subscriptions.assert_not_called()
    mock_next_step.assert_called()


def test_validate_update_renewal_quantity_invalid_renewal_state_order_failed(
    order_factory,
    adobe_subscription_factory,
    adobe_api_error_factory,
    adobe_order_factory,
    subscriptions_factory,
    lines_factory,
    mock_mpt_client,
    mock_adobe_client,
    mock_switch_order_to_failed,
    mock_notify_not_updated_subscriptions,
    mock_next_step,
):
    subscriptions = subscriptions_factory()
    order = order_factory(
        lines=lines_factory(quantity=15)
        + lines_factory(line_id=2, item_id=2, external_vendor_id="99999999CA"),
        subscriptions=subscriptions,
    )
    context = Context(
        order=order,
        order_id=order["id"],
        upsize_lines=order["lines"],
        authorization_id="auth-id",
        adobe_customer_id="adobe-customer-id",
        adobe_new_order=adobe_order_factory(
            order_type="NEW",
            status=AdobeOrderStatus.FAILED.value,
        ),
    )
    adobe_sub = adobe_subscription_factory(renewal_quantity=10)
    mock_adobe_client.get_subscription.return_value = adobe_sub
    mock_adobe_client.update_subscription.side_effect = AdobeAPIError(
        400,
        adobe_api_error_factory(
            AdobeErrorCode.INVALID_RENEWAL_STATE.value,
            "Update could not be performed because it would create an invalid renewal state",
        ),
    )
    step = UpdateRenewalQuantities()

    step(mock_mpt_client, context, mock_next_step)  # act

    mock_switch_order_to_failed.assert_called()
    mock_next_step.assert_not_called()
    mock_notify_not_updated_subscriptions.assert_called()


def test_validate_update_renewal_quantity_error(
    mocker,
    mock_adobe_client,
    order_factory,
    adobe_subscription_factory,
    adobe_api_error_factory,
    subscriptions_factory,
    lines_factory,
):
    mocked_switch_to_failed = mocker.patch(
        "adobe_vipm.flows.fulfillment.change.switch_order_to_failed",
    )
    mocked_notify = mocker.patch(
        "adobe_vipm.flows.fulfillment.change.notify_not_updated_subscriptions",
    )
    subscriptions = subscriptions_factory()
    order = order_factory(
        lines=lines_factory(quantity=5)
        + lines_factory(line_id=2, item_id=2, external_vendor_id="99999999CA"),
        subscriptions=subscriptions,
    )
    context = Context(
        order=order,
        order_id=order["id"],
        upsize_lines=order["lines"],
        authorization_id="auth-id",
        adobe_customer_id="adobe-customer-id",
    )
    mocked_client = mocker.MagicMock()
    mocked_next_step = mocker.MagicMock()
    adobe_sub = adobe_subscription_factory(renewal_quantity=10)
    mock_adobe_client.get_subscription.return_value = adobe_sub
    mock_adobe_client.update_subscription.side_effect = AdobeAPIError(
        400, adobe_api_error_factory("1000", "Error updating autorenewal quantity")
    )
    step = UpdateRenewalQuantities()

    step(mocked_client, context, mocked_next_step)  # act

    mocked_switch_to_failed.assert_not_called()
    mocked_notify.assert_called_once()
    mocked_next_step.assert_not_called()


def test_rollback_updated_subscriptions_error(
    mocker,
    mock_adobe_client,
    order_factory,
    lines_factory,
    subscriptions_factory,
    adobe_subscription_factory,
    adobe_order_factory,
):
    subscriptions = subscriptions_factory()
    subscriptions2 = subscriptions_factory()
    subscriptions2[0]["id"] = "sub-2"
    subscriptions2[0]["externalIds"]["vendor"] = "sub-2-id"
    subscriptions2[0]["lines"][0]["item"]["id"] = "ITM-1234-1234-1234-0002"
    subscriptions2[0]["lines"][0]["id"] = "ALI-2119-4550-8674-5962-0002"
    order = order_factory(
        lines=lines_factory(quantity=5)
        + lines_factory(line_id=2, item_id=2, external_vendor_id="99999999CA"),
        subscriptions=subscriptions + subscriptions2,
    )
    adobe_sub = adobe_subscription_factory(subscription_id="sub-1-id", renewal_quantity=10)
    adobe_sub2 = adobe_subscription_factory(subscription_id="sub-2-id", renewal_quantity=15)
    adobe_order = adobe_order_factory(order_type="NEW", status="PROCESSED")
    mock_adobe_client.get_subscription.side_effect = [adobe_sub, adobe_sub2]
    mock_adobe_client.update_subscription.side_effect = [
        None,
        AdobeAPIError(400, {"code": "1000", "message": "Error during rollback"}),
        None,
    ]
    mocked_notify = mocker.patch(
        "adobe_vipm.flows.fulfillment.change.notify_not_updated_subscriptions"
    )
    mocked_client = mocker.MagicMock()
    mocked_next_step = mocker.MagicMock()
    context = Context(
        order=order,
        order_id=order["id"],
        upsize_lines=order["lines"],
        authorization_id="auth-id",
        adobe_customer_id="adobe-customer-id",
        product_id="PRD-1111-1111",
        adobe_new_order=adobe_order,
    )
    context.updated = [
        {"subscription_vendor_id": "sub-1-id", "old_quantity": 10, "new_quantity": 5}
    ]
    step = UpdateRenewalQuantities()

    step(mocked_client, context, mocked_next_step)  # act

    assert mock_adobe_client.update_subscription.call_count == 3
    mock_adobe_client.update_subscription.assert_any_call(
        context.authorization_id,
        context.adobe_customer_id,
        "a-sub-id",
        quantity=5,
    )
    mock_adobe_client.update_subscription.assert_any_call(
        context.authorization_id,
        context.adobe_customer_id,
        "a-sub-id",
        quantity=5,
    )
    mock_adobe_client.update_subscription.assert_any_call(
        context.authorization_id,
        context.adobe_customer_id,
        "a-sub-id",
        quantity=10,
    )
    mock_adobe_client.create_return_order_by_adobe_order.assert_called_once_with(
        context.authorization_id,
        context.adobe_customer_id,
        adobe_order,
    )
    mocked_notify.assert_called_with(
        context.order["id"],
        "Error updating subscription sub-2, 1000 - Error during rollback",
        [],
        context.product_id,
    )
    mocked_next_step.assert_not_called()


def test_rollback_updated_subscriptions_error_during_rollback(
    mocker,
    mock_adobe_client,
    order_factory,
    lines_factory,
    subscriptions_factory,
    adobe_subscription_factory,
    adobe_order_factory,
):
    subscriptions = subscriptions_factory()
    subscriptions2 = subscriptions_factory()
    subscriptions2[0]["id"] = "sub-2"
    subscriptions2[0]["externalIds"]["vendor"] = "sub-2-id"
    subscriptions2[0]["lines"][0]["item"]["id"] = "ITM-1234-1234-1234-0002"
    subscriptions2[0]["lines"][0]["id"] = "ALI-2119-4550-8674-5962-0002"
    order = order_factory(
        lines=lines_factory(quantity=5)
        + lines_factory(line_id=2, item_id=2, external_vendor_id="99999999CA"),
        subscriptions=subscriptions + subscriptions2,
    )
    adobe_sub = adobe_subscription_factory(subscription_id="sub-1-id", renewal_quantity=10)
    adobe_sub2 = adobe_subscription_factory(subscription_id="sub-2-id", renewal_quantity=15)
    adobe_order = adobe_order_factory(order_type="NEW", status="PROCESSED")
    mock_adobe_client.get_subscription.side_effect = [adobe_sub, adobe_sub2]
    mock_adobe_client.update_subscription.side_effect = [
        None,
        AdobeAPIError(400, {"code": "1000", "message": "Error during rollback"}),
        AdobeAPIError(400, {"code": "1000", "message": "Error during rollback"}),
    ]
    mocked_notify = mocker.patch(
        "adobe_vipm.flows.fulfillment.change.notify_not_updated_subscriptions"
    )
    mocked_client = mocker.MagicMock()
    mocked_next_step = mocker.MagicMock()
    context = Context(
        order=order,
        order_id=order["id"],
        upsize_lines=order["lines"],
        authorization_id="auth-id",
        adobe_customer_id="adobe-customer-id",
        product_id="PRD-1111-1111",
        adobe_new_order=adobe_order,
    )
    context.updated = [
        {"subscription_vendor_id": "sub-1-id", "old_quantity": 10, "new_quantity": 5},
        {"subscription_vendor_id": "sub-2-id", "old_quantity": 15, "new_quantity": 5},
    ]
    step = UpdateRenewalQuantities()

    step(mocked_client, context, mocked_next_step)  # act

    assert mock_adobe_client.update_subscription.call_count == 3
    mock_adobe_client.update_subscription.assert_any_call(
        context.authorization_id,
        context.adobe_customer_id,
        "a-sub-id",
        quantity=5,
    )
    mock_adobe_client.update_subscription.assert_any_call(
        context.authorization_id,
        context.adobe_customer_id,
        "a-sub-id",
        quantity=5,
    )
    mock_adobe_client.update_subscription.assert_any_call(
        context.authorization_id,
        context.adobe_customer_id,
        "a-sub-id",
        quantity=10,
    )
    mocked_notify.assert_called_with(
        context.order["id"],
        "Error rolling back updated subscriptions: 1000 - Error during rollback",
        context.updated,
        context.product_id,
    )
    mocked_next_step.assert_not_called()
