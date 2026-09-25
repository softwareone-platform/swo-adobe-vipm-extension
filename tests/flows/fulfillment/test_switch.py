import pytest

from adobe_vipm.adobe.constants import (
    ORDER_TYPE_PREVIEW_SWITCH,
    ORDER_TYPE_SWITCH,
    AdobeErrorCode,
    AdobeOrderStatus,
    AdobeSubscriptionStatus,
)
from adobe_vipm.adobe.errors import AdobeAPIError
from adobe_vipm.flows.constants import TEMPLATE_NAME_CHANGE, Param
from adobe_vipm.flows.context import Context
from adobe_vipm.flows.fulfillment.shared import (
    CompleteOrder,
    CreateOrUpdateSubscriptions,
    SetOrUpdateCotermDate,
    SetSubscriptionTemplate,
    SetupDueDate,
    StartOrderProcessing,
    SyncAgreement,
    UpdateAgreementParamsVisibility,
    ValidateDuplicateLines,
    ValidateRenewalWindow,
)
from adobe_vipm.flows.fulfillment.switch import (
    AlignSwitchRenewalQuantities,
    GetSwitchPreviewOrder,
    SubmitSwitchOrder,
    fulfill_switch_order,
)
from adobe_vipm.flows.helpers import SetupContext, UpdatePrices, ValidateSkuAvailability
from adobe_vipm.flows.utils import get_adobe_order_id, get_ordering_parameter

pytestmark = pytest.mark.usefixtures("mock_adobe_config")

SOURCE_SUBSCRIPTION_ID = "2409029d1344028fe34b1a8cc09e8fNA"
TARGET_SUBSCRIPTION_ID = "target-sub-id"


@pytest.fixture
def switch_order(order_factory, order_parameters_factory, switch_payload):
    return order_factory(
        order_type="Change",
        order_parameters=order_parameters_factory(switch_payload=switch_payload),
    )


def test_get_switch_preview_order_step(
    mocker, mock_adobe_client, mock_mpt_client, switch_order, switch_payload, adobe_order_factory
):
    preview_order = adobe_order_factory(order_type=ORDER_TYPE_PREVIEW_SWITCH)
    mock_adobe_client.create_switch_preview_order.return_value = preview_order
    mocked_next_step = mocker.MagicMock()
    context = Context(
        order=switch_order,
        order_id=switch_order["id"],
        authorization_id="authorization-id",
        adobe_customer_id="customer-id",
    )
    step = GetSwitchPreviewOrder()

    step(mock_mpt_client, context, mocked_next_step)  # act

    mock_adobe_client.create_switch_preview_order.assert_called_once_with(
        context.authorization_id,
        context.adobe_customer_id,
        context.order_id,
        switch_payload,
    )
    assert context.adobe_preview_order == preview_order
    mocked_next_step.assert_called_once_with(mock_mpt_client, context)


def test_get_switch_preview_order_step_skipped_when_order_already_created(
    mocker, mock_adobe_client, mock_mpt_client, switch_order
):
    mocked_next_step = mocker.MagicMock()
    context = Context(
        order=switch_order,
        order_id=switch_order["id"],
        authorization_id="authorization-id",
        adobe_customer_id="customer-id",
        adobe_new_order_id="adobe-order-id",
    )
    step = GetSwitchPreviewOrder()

    step(mock_mpt_client, context, mocked_next_step)  # act

    mock_adobe_client.create_switch_preview_order.assert_not_called()
    assert context.adobe_preview_order is None
    mocked_next_step.assert_called_once_with(mock_mpt_client, context)


def test_get_switch_preview_order_step_adobe_error(
    mocker, mock_adobe_client, mock_mpt_client, switch_order, adobe_api_error_factory
):
    error = AdobeAPIError(
        400,
        adobe_api_error_factory(
            code=AdobeErrorCode.INVALID_FIELDS.value,
            message="Invalid switch payload",
        ),
    )
    mock_adobe_client.create_switch_preview_order.side_effect = error
    mocked_switch_to_failed = mocker.patch(
        "adobe_vipm.flows.fulfillment.switch.switch_order_to_failed"
    )
    mocked_next_step = mocker.MagicMock()
    context = Context(
        order=switch_order,
        order_id=switch_order["id"],
        authorization_id="authorization-id",
        adobe_customer_id="customer-id",
    )
    step = GetSwitchPreviewOrder()

    step(mock_mpt_client, context, mocked_next_step)  # act

    mocked_switch_to_failed.assert_called_once()
    assert "Invalid switch payload" in mocked_switch_to_failed.mock_calls[0].args[2]["message"]
    mocked_next_step.assert_not_called()


def test_get_switch_preview_order_step_multiple_flex_discount_codes(
    mocker,
    mock_adobe_client,
    mock_mpt_client,
    order_factory,
    order_parameters_factory,
    switch_payload,
):
    switch_payload["lineItems"][0]["flexDiscountCodes"] = ["CODE-1", "CODE-2"]
    order = order_factory(
        order_type="Change",
        order_parameters=order_parameters_factory(switch_payload=switch_payload),
    )
    mocked_switch_to_failed = mocker.patch(
        "adobe_vipm.flows.fulfillment.switch.switch_order_to_failed"
    )
    mocked_next_step = mocker.MagicMock()
    context = Context(
        order=order,
        order_id=order["id"],
        authorization_id="authorization-id",
        adobe_customer_id="customer-id",
    )
    step = GetSwitchPreviewOrder()

    step(mock_mpt_client, context, mocked_next_step)  # act

    mock_adobe_client.create_switch_preview_order.assert_not_called()
    mocked_switch_to_failed.assert_called_once()
    message = mocked_switch_to_failed.mock_calls[0].args[2]["message"]
    assert "Only one flexible discount code per line item is allowed" in message
    assert "CODE-1, CODE-2" in message
    mocked_next_step.assert_not_called()


def test_get_switch_preview_order_step_flex_discount_limit_adobe_error(
    mocker, mock_adobe_client, mock_mpt_client, switch_order, adobe_api_error_factory
):
    error = AdobeAPIError(
        400,
        adobe_api_error_factory(
            code=AdobeErrorCode.FLEX_DISCOUNT_CODE_LIMIT_EXCEEDED.value,
            message="Line Item: 1, Reason: Invalid Flexible Discount",
        ),
    )
    mock_adobe_client.create_switch_preview_order.side_effect = error
    mocked_switch_to_failed = mocker.patch(
        "adobe_vipm.flows.fulfillment.switch.switch_order_to_failed"
    )
    mocked_next_step = mocker.MagicMock()
    context = Context(
        order=switch_order,
        order_id=switch_order["id"],
        authorization_id="authorization-id",
        adobe_customer_id="customer-id",
    )
    step = GetSwitchPreviewOrder()

    step(mock_mpt_client, context, mocked_next_step)  # act

    mocked_switch_to_failed.assert_called_once()
    message = mocked_switch_to_failed.mock_calls[0].args[2]["message"]
    assert "Only one flexible discount code per line item is allowed" in message
    mocked_next_step.assert_not_called()


def test_submit_switch_order_step_creates_order_still_pending(
    mocker,
    mock_adobe_client,
    mock_mpt_client,
    switch_order,
    switch_payload,
    adobe_order_factory,
):
    adobe_order = adobe_order_factory(
        order_type=ORDER_TYPE_SWITCH,
        order_id="adobe-switch-order-id",
        status=AdobeOrderStatus.OPEN.value,
    )
    mock_adobe_client.create_switch_order.return_value = adobe_order
    mocked_update = mocker.patch("adobe_vipm.flows.fulfillment.switch.update_order")
    mocked_next_step = mocker.MagicMock()
    context = Context(
        order=switch_order,
        order_id=switch_order["id"],
        authorization_id="authorization-id",
        adobe_customer_id="customer-id",
    )
    step = SubmitSwitchOrder()

    step(mock_mpt_client, context, mocked_next_step)  # act

    mock_adobe_client.create_switch_order.assert_called_once_with(
        context.authorization_id,
        context.adobe_customer_id,
        context.order_id,
        switch_payload,
    )
    mocked_update.assert_called_once_with(
        mock_mpt_client,
        context.order_id,
        externalIds=context.order["externalIds"],
        parameters=context.order["parameters"],
    )
    assert get_adobe_order_id(context.order) == "adobe-switch-order-id"
    order_ids_param = get_ordering_parameter(context.order, Param.ADOBE_ORDER_IDS.value)
    assert order_ids_param["value"] == "adobe-switch-order-id"
    assert context.adobe_new_order == adobe_order
    assert context.adobe_new_order_id == "adobe-switch-order-id"
    mocked_next_step.assert_not_called()


def test_submit_switch_order_step_order_created_and_processed(
    mocker, mock_adobe_client, mock_mpt_client, switch_order, adobe_order_factory
):
    adobe_order = adobe_order_factory(
        order_type=ORDER_TYPE_SWITCH,
        order_id="adobe-switch-order-id",
        status=AdobeOrderStatus.COMPLETE.value,
    )
    mock_adobe_client.get_order.return_value = adobe_order
    mocked_next_step = mocker.MagicMock()
    context = Context(
        order=switch_order,
        order_id=switch_order["id"],
        authorization_id="authorization-id",
        adobe_customer_id="customer-id",
        adobe_new_order_id="adobe-switch-order-id",
    )
    step = SubmitSwitchOrder()

    step(mock_mpt_client, context, mocked_next_step)  # act

    mock_adobe_client.create_switch_order.assert_not_called()
    mock_adobe_client.get_order.assert_called_once_with(
        context.authorization_id,
        context.adobe_customer_id,
        "adobe-switch-order-id",
    )
    assert context.adobe_new_order == adobe_order
    mocked_next_step.assert_called_once_with(mock_mpt_client, context)


def test_submit_switch_order_step_unrecoverable_status(
    mocker, mock_adobe_client, mock_mpt_client, switch_order, adobe_order_factory
):
    adobe_order = adobe_order_factory(
        order_type=ORDER_TYPE_SWITCH,
        order_id="adobe-switch-order-id",
        status=AdobeOrderStatus.FAILED.value,
    )
    mock_adobe_client.get_order.return_value = adobe_order
    mocked_switch_to_failed = mocker.patch(
        "adobe_vipm.flows.fulfillment.switch.switch_order_to_failed"
    )
    mocked_next_step = mocker.MagicMock()
    context = Context(
        order=switch_order,
        order_id=switch_order["id"],
        authorization_id="authorization-id",
        adobe_customer_id="customer-id",
        adobe_new_order_id="adobe-switch-order-id",
    )
    step = SubmitSwitchOrder()

    step(mock_mpt_client, context, mocked_next_step)  # act

    mocked_switch_to_failed.assert_called_once()
    assert "Order has failed" in mocked_switch_to_failed.mock_calls[0].args[2]["message"]
    mocked_next_step.assert_not_called()


def test_submit_switch_order_step_unexpected_status(
    mocker, mock_adobe_client, mock_mpt_client, switch_order, adobe_order_factory
):
    adobe_order = adobe_order_factory(
        order_type=ORDER_TYPE_SWITCH,
        order_id="adobe-switch-order-id",
        status="9999",
    )
    mock_adobe_client.get_order.return_value = adobe_order
    mocked_switch_to_failed = mocker.patch(
        "adobe_vipm.flows.fulfillment.switch.switch_order_to_failed"
    )
    mocked_next_step = mocker.MagicMock()
    context = Context(
        order=switch_order,
        order_id=switch_order["id"],
        authorization_id="authorization-id",
        adobe_customer_id="customer-id",
        adobe_new_order_id="adobe-switch-order-id",
    )
    step = SubmitSwitchOrder()

    step(mock_mpt_client, context, mocked_next_step)  # act

    mocked_switch_to_failed.assert_called_once()
    assert "9999" in mocked_switch_to_failed.mock_calls[0].args[2]["message"]
    mocked_next_step.assert_not_called()


def test_submit_switch_order_step_flex_discount_limit_error(
    mocker, mock_adobe_client, mock_mpt_client, switch_order, adobe_api_error_factory
):
    mock_adobe_client.create_switch_order.side_effect = AdobeAPIError(
        400,
        adobe_api_error_factory(
            code=AdobeErrorCode.FLEX_DISCOUNT_CODE_LIMIT_EXCEEDED.value,
            message="Line Item: 1, Reason: Invalid Flexible Discount",
        ),
    )
    mocked_switch_to_failed = mocker.patch(
        "adobe_vipm.flows.fulfillment.switch.switch_order_to_failed"
    )
    mocked_next_step = mocker.MagicMock()
    context = Context(
        order=switch_order,
        order_id=switch_order["id"],
        authorization_id="authorization-id",
        adobe_customer_id="customer-id",
    )
    step = SubmitSwitchOrder()

    step(mock_mpt_client, context, mocked_next_step)  # act

    mocked_switch_to_failed.assert_called_once()
    message = mocked_switch_to_failed.mock_calls[0].args[2]["message"]
    assert "Only one flexible discount code per line item is allowed" in message
    mocked_next_step.assert_not_called()


def test_submit_switch_order_step_other_adobe_error_reraised(
    mocker, mock_adobe_client, mock_mpt_client, switch_order, adobe_api_error_factory
):
    error = AdobeAPIError(
        400,
        adobe_api_error_factory(code="9999", message="Something else went wrong"),
    )
    mock_adobe_client.create_switch_order.side_effect = error
    mocked_switch_to_failed = mocker.patch(
        "adobe_vipm.flows.fulfillment.switch.switch_order_to_failed"
    )
    mocked_next_step = mocker.MagicMock()
    context = Context(
        order=switch_order,
        order_id=switch_order["id"],
        authorization_id="authorization-id",
        adobe_customer_id="customer-id",
    )
    step = SubmitSwitchOrder()

    with pytest.raises(AdobeAPIError):
        step(mock_mpt_client, context, mocked_next_step)  # act

    mocked_switch_to_failed.assert_not_called()
    mocked_next_step.assert_not_called()


@pytest.fixture
def completed_switch_context(switch_order, adobe_order_factory, adobe_items_factory):
    adobe_order = adobe_order_factory(
        order_type=ORDER_TYPE_SWITCH,
        order_id="adobe-switch-order-id",
        status=AdobeOrderStatus.COMPLETE.value,
        items=adobe_items_factory(
            offer_id="65322651CA01A12", quantity=25, subscription_id=TARGET_SUBSCRIPTION_ID
        ),
    )
    return Context(
        order=switch_order,
        order_id=switch_order["id"],
        product_id="PRD-1111-1111",
        authorization_id="authorization-id",
        adobe_customer_id="customer-id",
        adobe_new_order=adobe_order,
        adobe_new_order_id="adobe-switch-order-id",
    )


def test_align_switch_renewal_quantities_sets_source_and_target(
    mocker, mock_adobe_client, mock_mpt_client, completed_switch_context, adobe_subscription_factory
):
    subscriptions = {
        SOURCE_SUBSCRIPTION_ID: adobe_subscription_factory(
            subscription_id=SOURCE_SUBSCRIPTION_ID, current_quantity=10, renewal_quantity=12
        ),
        TARGET_SUBSCRIPTION_ID: adobe_subscription_factory(
            subscription_id=TARGET_SUBSCRIPTION_ID, current_quantity=25, renewal_quantity=20
        ),
    }
    mock_adobe_client.get_subscription.side_effect = lambda *call_args: subscriptions[call_args[-1]]
    mocked_notify = mocker.patch("adobe_vipm.flows.fulfillment.switch.send_exception")
    mocked_next_step = mocker.MagicMock()
    step = AlignSwitchRenewalQuantities()

    step(mock_mpt_client, completed_switch_context, mocked_next_step)  # act

    assert mock_adobe_client.set_renewal_quantity.call_args_list == [
        mocker.call("authorization-id", "customer-id", SOURCE_SUBSCRIPTION_ID, 10),
        mocker.call("authorization-id", "customer-id", TARGET_SUBSCRIPTION_ID, 25),
    ]
    mocked_notify.assert_not_called()
    mocked_next_step.assert_called_once_with(mock_mpt_client, completed_switch_context)


def test_align_switch_renewal_quantities_skips_inactive_source(
    mocker, mock_adobe_client, mock_mpt_client, completed_switch_context, adobe_subscription_factory
):
    """A source switched in full is inactive and must not be updated."""
    subscriptions = {
        SOURCE_SUBSCRIPTION_ID: adobe_subscription_factory(
            subscription_id=SOURCE_SUBSCRIPTION_ID,
            current_quantity=0,
            renewal_quantity=25,
            status=AdobeSubscriptionStatus.INACTIVE.value,
        ),
        TARGET_SUBSCRIPTION_ID: adobe_subscription_factory(
            subscription_id=TARGET_SUBSCRIPTION_ID, current_quantity=25, renewal_quantity=10
        ),
    }
    mock_adobe_client.get_subscription.side_effect = lambda *call_args: subscriptions[call_args[-1]]
    mocked_next_step = mocker.MagicMock()
    step = AlignSwitchRenewalQuantities()

    step(mock_mpt_client, completed_switch_context, mocked_next_step)  # act

    mock_adobe_client.set_renewal_quantity.assert_called_once_with(
        "authorization-id", "customer-id", TARGET_SUBSCRIPTION_ID, 25
    )
    mocked_next_step.assert_called_once_with(mock_mpt_client, completed_switch_context)


def test_align_switch_renewal_quantities_skips_subscriptions_not_auto_renewing(
    mocker, mock_adobe_client, mock_mpt_client, completed_switch_context, adobe_subscription_factory
):
    """Adobe ignores a renewal quantity while auto-renewal is off, so none is sent."""
    mock_adobe_client.get_subscription.return_value = adobe_subscription_factory(
        current_quantity=10, renewal_quantity=12, autorenewal_enabled=False
    )
    mocked_notify = mocker.patch("adobe_vipm.flows.fulfillment.switch.send_exception")
    mocked_next_step = mocker.MagicMock()
    step = AlignSwitchRenewalQuantities()

    step(mock_mpt_client, completed_switch_context, mocked_next_step)  # act

    mock_adobe_client.set_renewal_quantity.assert_not_called()
    mocked_notify.assert_not_called()
    mocked_next_step.assert_called_once_with(mock_mpt_client, completed_switch_context)


def test_align_switch_renewal_quantities_skips_subscriptions_already_aligned(
    mocker, mock_adobe_client, mock_mpt_client, completed_switch_context, adobe_subscription_factory
):
    mock_adobe_client.get_subscription.return_value = adobe_subscription_factory(
        current_quantity=25, renewal_quantity=25
    )
    mocked_next_step = mocker.MagicMock()
    step = AlignSwitchRenewalQuantities()

    step(mock_mpt_client, completed_switch_context, mocked_next_step)  # act

    assert mock_adobe_client.get_subscription.call_count == 2
    mock_adobe_client.set_renewal_quantity.assert_not_called()
    mocked_next_step.assert_called_once_with(mock_mpt_client, completed_switch_context)


def test_align_switch_renewal_quantities_failure_notifies_and_completes(
    mocker,
    mock_adobe_client,
    mock_mpt_client,
    completed_switch_context,
    adobe_subscription_factory,
    adobe_api_error_factory,
):
    """The SWITCH is already done, so a failed update is reported, never failed."""
    mock_adobe_client.get_subscription.return_value = adobe_subscription_factory(
        current_quantity=10, renewal_quantity=12
    )
    mock_adobe_client.set_renewal_quantity.side_effect = [
        AdobeAPIError(500, adobe_api_error_factory(code="1124", message="Internal Server Error")),
        None,
    ]
    mocked_notify = mocker.patch("adobe_vipm.flows.fulfillment.switch.send_exception")
    mocked_next_step = mocker.MagicMock()
    step = AlignSwitchRenewalQuantities()

    step(mock_mpt_client, completed_switch_context, mocked_next_step)  # act

    assert mock_adobe_client.set_renewal_quantity.call_count == 2
    mocked_notify.assert_called_once()
    title, message = mocked_notify.call_args.args
    assert title == (
        f"Renewal quantity not aligned after mid-term upgrade: {completed_switch_context.order_id}"
    )
    assert SOURCE_SUBSCRIPTION_ID in message
    assert TARGET_SUBSCRIPTION_ID not in message
    assert "Product ID: PRD-1111-1111" in message
    mocked_next_step.assert_called_once_with(mock_mpt_client, completed_switch_context)


def test_align_switch_renewal_quantities_read_failure_notifies_and_completes(
    mocker, mock_adobe_client, mock_mpt_client, completed_switch_context, adobe_api_error_factory
):
    mock_adobe_client.get_subscription.side_effect = AdobeAPIError(
        500, adobe_api_error_factory(code="1124", message="Internal Server Error")
    )
    mocked_notify = mocker.patch("adobe_vipm.flows.fulfillment.switch.send_exception")
    mocked_next_step = mocker.MagicMock()
    step = AlignSwitchRenewalQuantities()

    step(mock_mpt_client, completed_switch_context, mocked_next_step)  # act

    mock_adobe_client.set_renewal_quantity.assert_not_called()
    message = mocked_notify.call_args.args[1]
    assert SOURCE_SUBSCRIPTION_ID in message
    assert TARGET_SUBSCRIPTION_ID in message
    mocked_next_step.assert_called_once_with(mock_mpt_client, completed_switch_context)


def test_fulfill_switch_order(mocker):
    mocked_pipeline_instance = mocker.MagicMock()
    mocked_pipeline_ctor = mocker.patch(
        "adobe_vipm.flows.fulfillment.switch.Pipeline",
        return_value=mocked_pipeline_instance,
    )
    mocked_context = mocker.MagicMock()
    mocked_context_ctor = mocker.patch(
        "adobe_vipm.flows.fulfillment.switch.Context", return_value=mocked_context
    )
    mocked_client = mocker.MagicMock()
    mocked_order = mocker.MagicMock()

    fulfill_switch_order(mocked_client, mocked_order)  # act

    expected_steps = [
        SetupContext,
        StartOrderProcessing,
        SetupDueDate,
        ValidateDuplicateLines,
        SetOrUpdateCotermDate,
        UpdateAgreementParamsVisibility,
        ValidateRenewalWindow,
        ValidateSkuAvailability,
        GetSwitchPreviewOrder,
        UpdatePrices,
        SubmitSwitchOrder,
        CreateOrUpdateSubscriptions,
        AlignSwitchRenewalQuantities,
        CompleteOrder,
        SetSubscriptionTemplate,
        SyncAgreement,
    ]
    pipeline_args = mocked_pipeline_ctor.mock_calls[0].args
    assert len(pipeline_args) == len(expected_steps)
    actual_steps = [type(step) for step in pipeline_args]
    assert actual_steps == expected_steps
    assert pipeline_args[1].template_name == TEMPLATE_NAME_CHANGE
    assert pipeline_args[13].template_name == TEMPLATE_NAME_CHANGE
    mocked_context_ctor.assert_called_once_with(order=mocked_order)
    mocked_pipeline_instance.run.assert_called_once_with(mocked_client, mocked_context)
