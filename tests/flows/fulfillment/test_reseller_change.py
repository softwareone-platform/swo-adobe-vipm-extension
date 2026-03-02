from adobe_vipm.adobe.constants import AdobeStatus, ResellerChangeAction
from adobe_vipm.adobe.errors import AdobeAPIError
from adobe_vipm.flows.constants import TEMPLATE_NAME_TRANSFER
from adobe_vipm.flows.context import Context
from adobe_vipm.flows.fulfillment import transfer
from adobe_vipm.flows.fulfillment.reseller_transfer import (
    CheckAdobeResellerTransfer,
    CommitResellerChange,
    CompleteResellerTransferOrder,
    GetAdobeCustomer,
    ProcessResellerTransferOrder,
    SetupResellerChangeContext,
    UpdateAutorenewalSubscriptions,
    fulfill_purchase_order,
    fulfill_reseller_change_order,
)
from adobe_vipm.flows.fulfillment.shared import (
    CompleteOrder,
    CreateOrUpdateAssets,
    CreateOrUpdateSubscriptions,
    GetPreviewOrder,
    NullifyFlexDiscountParam,
    SetOrUpdateCotermDate,
    SetupDueDate,
    StartOrderProcessing,
    SubmitNewOrder,
    SyncAgreement,
)
from adobe_vipm.flows.helpers import (
    FetchResellerChangeData,
    SetupContext,
    UpdatePrices,
    ValidateResellerChange,
)
from adobe_vipm.flows.pipeline import Pipeline
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

    step(mock_mpt_client, context, mock_next_step)  # act

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
    mock_next_step.assert_called_once_with(mock_mpt_client, context)


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

    step(mock_mpt_client, context, mock_next_step)  # act

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
        "adobe_vipm.flows.fulfillment.shared.switch_order_to_failed",
        autospec=True,
    )
    order = order_factory(order_parameters=reseller_change_order_parameters_factory())
    context = Context(order=order, authorization_id="authorization-id")
    step = CommitResellerChange()

    step(mock_mpt_client, context, mock_next_step)  # act

    mock_adobe_client.reseller_change_request.assert_called_once()
    mocked_switch_to_failed.assert_called_once()


def test_check_adobe_reseller_transfer_step_success(
    mocker,
    order_factory,
    adobe_reseller_change_factory,
    reseller_change_order_parameters_factory,
    mock_next_step,
    mock_mpt_client,
    mock_adobe_client,
):
    adobe_transfer_order = adobe_reseller_change_factory()
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
    context = Context(order=order, authorization_id="AUT-1234-4567")
    context.adobe_transfer_order = adobe_transfer_order
    step = CheckAdobeResellerTransfer()

    step(mock_mpt_client, context, mock_next_step)  # act

    mock_adobe_client.get_reseller_transfer.assert_called_once_with(
        context.authorization_id, "110014510"
    )
    for item in context.adobe_transfer_order["lineItems"]:
        assert "ADOBE-" not in item["offerId"]
    assert context.adobe_transfer_order["membershipId"] == "88888888"
    mock_next_step.assert_called_once_with(mock_mpt_client, context)


def test_check_adobe_reseller_transfer_step_pending_status(
    mocker,
    order_factory,
    adobe_reseller_change_factory,
    reseller_change_order_parameters_factory,
    mock_next_step,
    mock_mpt_client,
    mock_adobe_client,
):
    adobe_transfer_order = adobe_reseller_change_factory()
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
    context.adobe_transfer_order = adobe_transfer_order
    step = CheckAdobeResellerTransfer()

    step(mock_mpt_client, context, mock_next_step)  # act

    mock_adobe_client.get_reseller_transfer.assert_called_once_with(
        context.authorization_id, "110014510"
    )
    for item in context.adobe_transfer_order["lineItems"]:
        assert "ADOBE-" not in item["offerId"]
    assert context.adobe_transfer_order["membershipId"] == "88888888"
    mock_next_step.assert_not_called()


def test_check_adobe_reseller_transfer_step_no_transfer_id(
    mocker,
    mock_next_step,
    mock_mpt_client,
    mock_adobe_client,
    mock_order,
):
    mocker.patch(
        "adobe_vipm.flows.fulfillment.reseller_transfer.get_adobe_client",
        return_value=mock_adobe_client,
    )
    context = Context(order=mock_order, authorization_id="AUT-1234-4567")
    context.adobe_transfer_order = {}
    step = CheckAdobeResellerTransfer()

    step(mock_mpt_client, context, mock_next_step)  # act

    mock_adobe_client.get_reseller_transfer.assert_not_called()
    mock_next_step.assert_called_once_with(mock_mpt_client, context)


def test_check_adobe_reseller_transfer_step_no_line_items_fallback_to_purchase(
    order_factory,
    adobe_reseller_change_preview_factory,
    reseller_change_order_parameters_factory,
    mock_next_step,
    mock_mpt_client,
    mock_fulfill_purchase_order,
):
    adobe_transfer_order = adobe_reseller_change_preview_factory()
    adobe_transfer_order["status"] = AdobeStatus.PROCESSED
    adobe_transfer_order["lineItems"] = []
    order = order_factory(
        order_parameters=reseller_change_order_parameters_factory(),
        external_ids={"vendor": "TRANSFER-123"},
    )
    context = Context(order=order, authorization_id="AUT-1234-4567")
    context.adobe_transfer_order = adobe_transfer_order
    step = ProcessResellerTransferOrder()

    step(mock_mpt_client, context, mock_next_step)  # act

    mock_next_step.assert_not_called()
    mock_fulfill_purchase_order.assert_called_once()


def test_check_adobe_reseller_transfer_step_reset_order_id_when_ids_match(
    mocker,
    order_factory,
    adobe_reseller_change_preview_factory,
    reseller_change_order_parameters_factory,
    mock_next_step,
    mock_mpt_client,
    mock_adobe_client,
    mock_fulfill_purchase_order,
):
    adobe_transfer_order = adobe_reseller_change_preview_factory()
    adobe_transfer_order["status"] = AdobeStatus.PROCESSED
    adobe_transfer_order["lineItems"] = []
    adobe_transfer_order["transferId"] = "TRANSFER-123"
    mocked_save_adobe_order_id = mocker.patch(
        "adobe_vipm.flows.fulfillment.reseller_transfer.shared.save_adobe_order_id", spec=True
    )
    order = order_factory(
        order_parameters=reseller_change_order_parameters_factory(),
        external_ids={"vendor": "TRANSFER-123"},
    )
    context = Context(
        order=order,
        authorization_id="AUT-1234-4567",
        adobe_new_order_id="TRANSFER-123",
    )
    context.adobe_transfer_order = adobe_transfer_order
    step = ProcessResellerTransferOrder()

    step(mock_mpt_client, context, mock_next_step)  # act

    mocked_save_adobe_order_id.assert_called_once()
    assert mocked_save_adobe_order_id.call_args[0][0] is mock_mpt_client
    assert not mocked_save_adobe_order_id.call_args[0][2]
    assert not context.adobe_new_order_id
    mock_next_step.assert_not_called()
    mock_fulfill_purchase_order.assert_called_once_with(mock_mpt_client, context)


def test_check_adobe_reseller_transfer_step_processes_transfer_line_items(
    mocker,
    order_factory,
    adobe_reseller_change_preview_factory,
    reseller_change_order_parameters_factory,
    mock_next_step,
    mock_mpt_client,
    mock_fulfill_purchase_order,
):
    adobe_transfer_order = adobe_reseller_change_preview_factory()
    filtered_transfer_order = {
        **adobe_transfer_order,
        "lineItems": [{"offerId": "sku-no-deployment"}],
    }
    mocked_exclude_items = mocker.patch(
        "adobe_vipm.flows.fulfillment.reseller_transfer.exclude_items_with_deployment_id",
        return_value=filtered_transfer_order,
        spec=True,
    )
    updated_order = {"id": "ORDER-UPDATED"}
    mocked_save_order_data = mocker.patch(
        "adobe_vipm.flows.fulfillment.reseller_transfer.shared.save_adobe_order_id_and_customer_data",
        return_value=updated_order,
        spec=True,
    )
    order = order_factory(
        order_parameters=reseller_change_order_parameters_factory(),
        external_ids={"vendor": "TRANSFER-123"},
    )
    context = Context(
        order=order,
        authorization_id="AUT-1234-4567",
        adobe_new_order_id="TRANSFER-123",
    )
    context.adobe_customer = {"customerId": "CUSTOMER-123"}
    context.adobe_transfer_order = adobe_transfer_order
    step = ProcessResellerTransferOrder()

    step(mock_mpt_client, context, mock_next_step)  # act

    mocked_exclude_items.assert_called_once_with(adobe_transfer_order)
    mocked_save_order_data.assert_called_once_with(
        mock_mpt_client,
        order,
        context.adobe_new_order_id,
        context.adobe_customer,
    )
    assert context.adobe_transfer_order == filtered_transfer_order
    assert context.order == updated_order
    mock_next_step.assert_called_once_with(mock_mpt_client, context)
    mock_fulfill_purchase_order.assert_not_called()


def test_get_adobe_customer_uses_order_customer_id_when_transfer_missing(
    mocker, order_factory, mock_mpt_client, mock_adobe_client, mock_next_step, mock_get_customer_id
):
    mocker.patch(
        "adobe_vipm.flows.fulfillment.reseller_transfer.get_adobe_client",
        return_value=mock_adobe_client,
    )
    mock_get_customer_id.return_value = "CUSTOMER-ORDER-123"
    mocked_save_order_data = mocker.patch(
        "adobe_vipm.flows.fulfillment.reseller_transfer.shared.save_adobe_order_id_and_customer_data",
        return_value={"id": "ORDER-UPDATED"},
        spec=True,
    )
    mock_adobe_client.get_customer.return_value = {"customerId": "CUSTOMER-ORDER-123"}
    order = order_factory()
    context = Context(
        order=order,
        authorization_id="AUT-1234-4567",
        adobe_transfer_order={},
        adobe_new_order_id="ORDER-123",
    )
    step = GetAdobeCustomer()

    step(mock_mpt_client, context, mock_next_step)  # act

    mock_get_customer_id.assert_called_once_with(order)
    mock_adobe_client.get_customer.assert_called_once_with(
        context.authorization_id, "CUSTOMER-ORDER-123"
    )
    mocked_save_order_data.assert_called_once_with(
        mock_mpt_client,
        order,
        context.adobe_new_order_id,
        mock_adobe_client.get_customer.return_value,
    )
    mock_next_step.assert_called_once_with(mock_mpt_client, context)


def test_get_adobe_customer_prefers_transfer_customer_id(
    mocker, order_factory, mock_mpt_client, mock_adobe_client, mock_next_step, mock_get_customer_id
):
    mocker.patch(
        "adobe_vipm.flows.fulfillment.reseller_transfer.get_adobe_client",
        return_value=mock_adobe_client,
    )
    mocked_save_order_data = mocker.patch(
        "adobe_vipm.flows.fulfillment.reseller_transfer.shared.save_adobe_order_id_and_customer_data",
        return_value={"id": "ORDER-UPDATED"},
        autospec=True,
    )
    mock_adobe_client.get_customer.return_value = {"customerId": "CUSTOMER-TRANSFER-999"}
    order = order_factory()
    context = Context(
        order=order,
        authorization_id="AUT-1234-4567",
        adobe_transfer_order={"customerId": "CUSTOMER-TRANSFER-999"},
        adobe_new_order_id="ORDER-123",
    )
    step = GetAdobeCustomer()

    step(mock_mpt_client, context, mock_next_step)  # act

    mock_get_customer_id.assert_not_called()
    mock_adobe_client.get_customer.assert_called_once_with(
        context.authorization_id, "CUSTOMER-TRANSFER-999"
    )
    mocked_save_order_data.assert_called_once_with(
        mock_mpt_client,
        order,
        context.adobe_new_order_id,
        mock_adobe_client.get_customer.return_value,
    )
    mock_next_step.assert_called_once_with(mock_mpt_client, context)


def test_complete_reseller_transfer_order_step(
    mocker,
    order_factory,
    mock_mpt_client,
    mock_adobe_client,
    mock_next_step,
):
    mocked_switch_to_completed = mocker.patch(
        "adobe_vipm.flows.fulfillment.reseller_transfer.shared.switch_order_to_completed",
        autospec=True,
    )
    mocker.patch(
        "adobe_vipm.flows.fulfillment.reseller_transfer.get_adobe_client",
        return_value=mock_adobe_client,
    )
    mocked_sync_agreements = mocker.patch(
        "adobe_vipm.flows.fulfillment.reseller_transfer.sync_agreements_by_agreement_ids",
        autospec=True,
    )
    mocked_sync_airtable = mocker.patch(
        "adobe_vipm.flows.fulfillment.reseller_transfer.transfer.sync_airtable_main_agreement",
        autospec=True,
    )
    order = order_factory()
    context = Context(
        order=order,
        product_id="PRD-1111-1111",
        authorization_id="AUT-1234-4567",
        adobe_customer_id="CUSTOMER-123",
    )
    context.gc_main_agreement = {"id": "AGR-123"}
    step = CompleteResellerTransferOrder()

    step(mock_mpt_client, context, mock_next_step)  # act

    mocked_switch_to_completed.assert_called_once_with(
        mock_mpt_client,
        context.order,
        TEMPLATE_NAME_TRANSFER,
    )
    mocked_sync_agreements.assert_called_once_with(
        mock_mpt_client,
        mock_adobe_client,
        [order["agreement"]["id"]],
        dry_run=False,
        sync_prices=False,
    )
    mocked_sync_airtable.assert_called_once_with(
        context.gc_main_agreement,
        context.product_id,
        context.authorization_id,
        context.adobe_customer_id,
    )
    mock_next_step.assert_called_once_with(mock_mpt_client, context)


def test_fulfill_reseller_change_order(mocker, mock_mpt_client):
    mocked_pipeline_instance = mocker.MagicMock(spec=Pipeline)
    mocked_pipeline_ctor = mocker.patch(
        "adobe_vipm.flows.fulfillment.reseller_transfer.Pipeline",
        return_value=mocked_pipeline_instance,
        autospec=True,
    )
    mocked_context = mocker.MagicMock(spec=Context)
    mocked_context_ctor = mocker.patch(
        "adobe_vipm.flows.fulfillment.reseller_transfer.Context",
        return_value=mocked_context,
        autospec=True,
    )
    mocked_order = mocker.MagicMock()

    fulfill_reseller_change_order(mock_mpt_client, mocked_order)  # act

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
        UpdateAutorenewalSubscriptions,
        transfer.ValidateGCMainAgreement,
        transfer.ValidateAgreementDeployments,
        ProcessResellerTransferOrder,
        transfer.CreateTransferAssets,
        transfer.CreateTransferSubscriptions,
        transfer.SetCommitmentDates,
        CompleteResellerTransferOrder,
        SyncAgreement,
    ]
    actual_steps = [type(step) for step in mocked_pipeline_ctor.mock_calls[0].args]
    assert actual_steps == expected_steps
    mocked_context_ctor.assert_called_once_with(order=mocked_order)
    mocked_pipeline_instance.run.assert_called_once_with(
        mock_mpt_client,
        mocked_context,
    )


def test_fulfill_purchase_order(mocker, mock_mpt_client):
    mocked_pipeline_ctor = mocker.patch(
        "adobe_vipm.flows.fulfillment.reseller_transfer.Pipeline",
        autospec=True,
    )
    mocked_pipeline_instance = mocked_pipeline_ctor.return_value
    mocked_context = mocker.MagicMock(spec=Context)

    fulfill_purchase_order(mock_mpt_client, mocked_context)  # act

    assert len(mocked_pipeline_ctor.mock_calls[0].args) == 9
    expected_steps = [
        GetPreviewOrder,
        UpdatePrices,
        SubmitNewOrder,
        CreateOrUpdateAssets,
        CreateOrUpdateSubscriptions,
        SetOrUpdateCotermDate,
        CompleteOrder,
        NullifyFlexDiscountParam,
        SyncAgreement,
    ]
    actual_steps = [type(step) for step in mocked_pipeline_ctor.mock_calls[0].args]
    assert actual_steps == expected_steps
    mocked_pipeline_instance.run.assert_called_once_with(mock_mpt_client, mocked_context)


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
        "adobe_vipm.flows.fulfillment.transfer.get_main_agreement"
    )
    mocked_get_main_agreement.return_value = None
    mocked_get_agreement_deployments = mocker.patch(
        "adobe_vipm.flows.fulfillment.transfer.get_agreement_deployments"
    )
    mocked_get_agreement_deployments.return_value = []
    order = order_factory(order_parameters=reseller_change_order_parameters_factory())
    context = Context(order=order, product_id="product-123", authorization_id="AUT-1234-4567")
    step = SetupResellerChangeContext()

    step(mock_mpt_client, context, mock_next_step)  # act

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


def test_update_autorenewal_subscriptions_step_success(
    mocker,
    order_factory,
    reseller_change_order_parameters_factory,
    mock_adobe_client,
    mock_mpt_client,
    mock_next_step,
    adobe_api_error_factory,
    caplog,
):
    mock_adobe_client.get_subscriptions.return_value = {
        "items": [
            {
                "subscriptionId": "SUB-1234-5678",
                "status": "1000",
                "autoRenewal": {
                    "enabled": False,
                },
            },
            {
                "subscriptionId": "SUB-1234-5679",
                "status": "1000",
                "autoRenewal": {
                    "enabled": True,
                },
            },
            {
                "subscriptionId": "SUB-1234-5680",
                "status": "1004",
                "autoRenewal": {
                    "enabled": False,
                },
            },
        ]
    }
    mock_adobe_client.update_subscription.side_effect = [
        None,
        AdobeAPIError(400, adobe_api_error_factory("1004", "API error")),
    ]
    order = order_factory()
    context = Context(order=order, authorization_id="AUT-1234-4567")
    context.adobe_customer_id = "CUSTOMER-1234-5678"
    step = UpdateAutorenewalSubscriptions()

    step(mock_mpt_client, context, mock_next_step)  # act

    mock_adobe_client.get_subscriptions.assert_called_once_with(
        context.authorization_id,
        context.adobe_customer_id,
    )
    mock_adobe_client.update_subscription.assert_has_calls([
        mocker.call(
            context.authorization_id,
            context.adobe_customer_id,
            "SUB-1234-5678",
            auto_renewal=True,
        ),
        mocker.call(
            context.authorization_id,
            context.adobe_customer_id,
            "SUB-1234-5680",
            auto_renewal=True,
        ),
    ])
    mock_next_step.assert_called_once_with(mock_mpt_client, context)
    expected_msg = (
        "None - None None AUT-1234-4567 - CUSTOMER-1234-5678 -: "
        "Error updating the auto renewal status of the subscription SUB-1234-5680"
    )
    assert caplog.messages == [expected_msg]


def test_update_autorenewal_subscriptions_step_no_disabled_subscriptions(
    mocker,
    order_factory,
    mock_adobe_client,
    mock_mpt_client,
    mock_next_step,
):
    mock_adobe_client.get_subscriptions.return_value = {
        "items": [
            {
                "subscriptionId": "SUB-1234-5678",
                "status": "1000",
                "autoRenewal": {
                    "enabled": True,
                },
            },
        ]
    }
    order = order_factory()
    context = Context(order=order, authorization_id="AUT-1234-4567")
    context.adobe_customer_id = "CUSTOMER-1234-5678"
    step = UpdateAutorenewalSubscriptions()

    step(mock_mpt_client, context, mock_next_step)  # act

    mock_adobe_client.get_subscriptions.assert_called_once_with(
        context.authorization_id,
        context.adobe_customer_id,
    )
    mock_adobe_client.update_subscription.assert_not_called()
    mock_next_step.assert_called_once_with(mock_mpt_client, context)
