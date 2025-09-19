from adobe_vipm.adobe.constants import AdobeStatus, ResellerChangeAction
from adobe_vipm.adobe.errors import AdobeAPIError
from adobe_vipm.flows.context import Context
from adobe_vipm.flows.fulfillment.reseller_transfer import (
    CheckAdobeResellerTransfer,
    CommitResellerChange,
    SetupResellerChangeContext,
    fulfill_reseller_change_order,
)
from adobe_vipm.flows.fulfillment.shared import (
    SetupDueDate,
    StartOrderProcessing,
    SyncAgreement,
)
from adobe_vipm.flows.fulfillment.transfer import (
    CompleteTransferOrder,
    GetAdobeCustomer,
    ValidateAgreementDeployments,
    ValidateGCMainAgreement,
)
from adobe_vipm.flows.helpers import FetchResellerChangeData, SetupContext, ValidateResellerChange
from adobe_vipm.flows.utils import get_adobe_customer_id, get_adobe_order_id


def test_commit_reseller_change_step_success(
    mocker,
    order_factory,
    adobe_reseller_change_preview_factory,
    reseller_change_order_parameters_factory,
    mock_next_step,
    mock_mpt_client,
    mock_adobe_client,
):
    """Test successful execution of CommitResellerChange step."""
    adobe_transfer_order = adobe_reseller_change_preview_factory()

    mock_adobe_client.reseller_change_request.return_value = adobe_transfer_order

    mocker.patch(
        "adobe_vipm.flows.fulfillment.reseller_transfer.get_adobe_client",
        return_value=mock_adobe_client,
    )

    mocked_update_order = mocker.patch(
        "adobe_vipm.flows.fulfillment.reseller_transfer.update_order",
    )
    mocked_update_agreement = mocker.patch(
        "adobe_vipm.flows.fulfillment.reseller_transfer.update_agreement",
    )
    order = order_factory(order_parameters=reseller_change_order_parameters_factory())

    context = Context(
        order=order,
        order_id="order-id",
        agreement_id="agreement-id",
        authorization_id="AUT-1234-4567",
    )

    step = CommitResellerChange()
    step(mock_mpt_client, context, mock_next_step)

    mock_adobe_client.reseller_change_request.assert_called_once_with(
        context.authorization_id,
        context.order["agreement"]["seller"]["id"],
        "88888888",
        "admin@admin.com",
        ResellerChangeAction.COMMIT,
    )

    assert get_adobe_order_id(context.order) == adobe_transfer_order["transferId"]
    assert get_adobe_customer_id(context.order) == adobe_transfer_order["customerId"]

    mocked_update_order.assert_called_once()
    mocked_update_agreement.assert_called_once()
    mock_next_step.assert_not_called()


def test_commit_reseller_change_step_already_has_customer_id(
    mocker,
    mock_next_step,
    mock_mpt_client,
    mock_adobe_client,
    mock_order,
):
    mocker.patch(
        "adobe_vipm.flows.fulfillment.transfer.get_adobe_client",
        return_value=mock_adobe_client,
    )
    context = Context(order=mock_order, adobe_customer_id="existing-customer-id")

    step = CommitResellerChange()
    step(mock_mpt_client, context, mock_next_step)

    mock_adobe_client.reseller_change_request.assert_not_called()
    mock_next_step.assert_called_once_with(mock_mpt_client, context)


def test_commit_reseller_change_step_adobe_api_error(
    mocker,
    adobe_api_error_factory,
    reseller_change_order_parameters_factory,
    mock_next_step,
    mock_mpt_client,
    mock_adobe_client,
    order_factory,
):
    error = AdobeAPIError(400, adobe_api_error_factory("1234", "API error"))
    mock_adobe_client.reseller_change_request.side_effect = error
    mocker.patch(
        "adobe_vipm.flows.fulfillment.reseller_transfer.get_adobe_client",
        return_value=mock_adobe_client,
    )
    mocked_switch_to_failed = mocker.patch(
        "adobe_vipm.flows.fulfillment.reseller_transfer.switch_order_to_failed",
    )

    order = order_factory(order_parameters=reseller_change_order_parameters_factory())
    context = Context(order=order, authorization_id="authorization-id")

    step = CommitResellerChange()
    step(mock_mpt_client, context, mock_next_step)
    mock_adobe_client.reseller_change_request.assert_called_once()
    mocked_switch_to_failed.assert_called_once()


def test_check_adobe_reseller_transfer_step_success(
    mocker,
    order_factory,
    adobe_reseller_change_preview_factory,
    reseller_change_order_parameters_factory,
    mock_next_step,
    mock_mpt_client,
    mock_adobe_client,
):
    """Test CheckAdobeResellerTransfer step successful execution."""
    adobe_transfer_order = adobe_reseller_change_preview_factory()
    adobe_transfer_order["status"] = AdobeStatus.PROCESSED

    mock_adobe_client.get_reseller_transfer.return_value = adobe_transfer_order

    mocker.patch(
        "adobe_vipm.flows.fulfillment.reseller_transfer.get_adobe_client",
        return_value=mock_adobe_client,
    )
    order = order_factory(
        order_parameters=reseller_change_order_parameters_factory(),
        external_ids={"vendor": "TRANSFER-123"},
    )
    context = Context(
        order=order,
        authorization_id="AUT-1234-4567",
    )

    step = CheckAdobeResellerTransfer()
    step(mock_mpt_client, context, mock_next_step)

    mock_adobe_client.get_reseller_transfer.assert_called_once_with(
        context.authorization_id,
        "TRANSFER-123",
    )

    for item in context.adobe_transfer_order["lineItems"]:
        assert "ADOBE-" not in item["offerId"]

    assert context.adobe_transfer_order["membershipId"] == "88888888"
    mock_next_step.assert_called_once_with(mock_mpt_client, context)


def test_check_adobe_reseller_transfer_step_pending_status(
    mocker,
    order_factory,
    adobe_reseller_change_preview_factory,
    reseller_change_order_parameters_factory,
    mock_next_step,
    mock_mpt_client,
    mock_adobe_client,
):
    """Test CheckAdobeResellerTransfer step when status is PENDING."""
    adobe_transfer_order = adobe_reseller_change_preview_factory()
    adobe_transfer_order["status"] = AdobeStatus.PENDING

    mock_adobe_client.get_reseller_transfer.return_value = adobe_transfer_order

    mocker.patch(
        "adobe_vipm.flows.fulfillment.reseller_transfer.get_adobe_client",
        return_value=mock_adobe_client,
    )

    order = order_factory(
        order_parameters=reseller_change_order_parameters_factory(),
        external_ids={"vendor": "TRANSFER-123"},
    )
    context = Context(
        order=order,
        authorization_id="AUT-1234-4567",
    )

    step = CheckAdobeResellerTransfer()
    step(mock_mpt_client, context, mock_next_step)

    mock_adobe_client.get_reseller_transfer.assert_called_once_with(
        context.authorization_id,
        "TRANSFER-123",
    )

    for item in context.adobe_transfer_order["lineItems"]:
        assert "ADOBE-" not in item["offerId"]

    assert context.adobe_transfer_order["membershipId"] == "88888888"
    mock_next_step.assert_not_called()


def test_fulfill_reseller_change_order(mocker, mock_mpt_client):
    mocked_pipeline_instance = mocker.MagicMock()

    mocked_pipeline_ctor = mocker.patch(
        "adobe_vipm.flows.fulfillment.reseller_transfer.Pipeline",
        return_value=mocked_pipeline_instance,
    )
    mocked_context = mocker.MagicMock()
    mocked_context_ctor = mocker.patch(
        "adobe_vipm.flows.fulfillment.reseller_transfer.Context", return_value=mocked_context
    )
    mocked_order = mocker.MagicMock()

    fulfill_reseller_change_order(mock_mpt_client, mocked_order)

    expected_steps = [
        SetupContext,
        StartOrderProcessing,
        SetupDueDate,
        SetupResellerChangeContext,
        FetchResellerChangeData,
        ValidateResellerChange,
        CommitResellerChange,
        CheckAdobeResellerTransfer,
        GetAdobeCustomer,
        ValidateGCMainAgreement,
        ValidateAgreementDeployments,
        CompleteTransferOrder,
        SyncAgreement,
    ]

    actual_steps = [type(step) for step in mocked_pipeline_ctor.mock_calls[0].args]
    assert actual_steps == expected_steps

    mocked_context_ctor.assert_called_once_with(order=mocked_order)
    mocked_pipeline_instance.run.assert_called_once_with(
        mock_mpt_client,
        mocked_context,
    )


def test_setup_reseller_change_context_success(
    mocker,
    order_factory,
    reseller_change_order_parameters_factory,
    mock_mpt_client,
    mock_next_step,
):
    mocked_get_transfer = mocker.patch(
        "adobe_vipm.flows.fulfillment.reseller_transfer.get_transfer_by_authorization_membership_or_customer"
    )
    mocked_get_transfer.return_value = None
    mocked_get_main_agreement = mocker.patch(
        "adobe_vipm.flows.fulfillment.reseller_transfer.get_main_agreement"
    )
    mocked_get_main_agreement.return_value = None
    mocked_get_agreement_deployments = mocker.patch(
        "adobe_vipm.flows.fulfillment.reseller_transfer.get_agreement_deployments"
    )
    mocked_get_agreement_deployments.return_value = []
    order = order_factory(order_parameters=reseller_change_order_parameters_factory())
    context = Context(order=order, product_id="product-123", authorization_id="AUT-1234-4567")
    step = SetupResellerChangeContext()
    step(mock_mpt_client, context, mock_next_step)
    mocked_get_transfer.assert_called_once_with(
        context.product_id, context.authorization_id, "88888888"
    )
    mocked_get_main_agreement.assert_called_once_with(
        context.product_id, context.authorization_id, "88888888"
    )
    mocked_get_agreement_deployments.assert_called_once_with(
        context.product_id, context.order.get("agreement", {}).get("id", "")
    )
    mock_next_step.assert_called_once_with(mock_mpt_client, context)
