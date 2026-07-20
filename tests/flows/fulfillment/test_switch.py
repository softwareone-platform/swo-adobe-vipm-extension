import pytest

from adobe_vipm.adobe.constants import (
    ORDER_TYPE_PREVIEW_SWITCH,
    ORDER_TYPE_SWITCH,
    AdobeErrorCode,
    AdobeOrderStatus,
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
    GetSwitchPreviewOrder,
    SubmitSwitchOrder,
    fulfill_switch_order,
)
from adobe_vipm.flows.helpers import SetupContext, UpdatePrices, ValidateSkuAvailability
from adobe_vipm.flows.utils import get_adobe_order_id, get_ordering_parameter

pytestmark = pytest.mark.usefixtures("mock_adobe_config")


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
        CompleteOrder,
        SetSubscriptionTemplate,
        SyncAgreement,
    ]
    pipeline_args = mocked_pipeline_ctor.mock_calls[0].args
    assert len(pipeline_args) == len(expected_steps)
    actual_steps = [type(step) for step in pipeline_args]
    assert actual_steps == expected_steps
    assert pipeline_args[1].template_name == TEMPLATE_NAME_CHANGE
    assert pipeline_args[12].template_name == TEMPLATE_NAME_CHANGE
    mocked_context_ctor.assert_called_once_with(order=mocked_order)
    mocked_pipeline_instance.run.assert_called_once_with(mocked_client, mocked_context)
