import pytest

from adobe_vipm.adobe.constants import (
    ORDER_TYPE_PREVIEW_RENEWAL,
    ORDER_TYPE_RENEWAL,
    AdobeErrorCode,
    AdobeOrderStatus,
)
from adobe_vipm.adobe.errors import AdobeAPIError
from adobe_vipm.flows.constants import TEMPLATE_NAME_CHANGE
from adobe_vipm.flows.context import Context
from adobe_vipm.flows.fulfillment.renewal_now import (
    DisableLapsingSubscriptions,
    NormalizeRenewedSubscriptions,
    PreviewRenewalNowOrder,
    ReturnPreviousRenewalOrders,
    SubmitRenewalNowOrder,
    fulfill_renewal_now_order,
)
from adobe_vipm.flows.fulfillment.shared import (
    CompleteOrder,
    SetOrUpdateCotermDate,
    SetSubscriptionTemplate,
    SetupDueDate,
    SetupRenewalPlan,
    StartOrderProcessing,
    SyncAgreement,
    UpdateAgreementParamsVisibility,
    ValidateDuplicateLines,
    ValidateRenewalWindow,
)
from adobe_vipm.flows.helpers import SetupContext

pytestmark = pytest.mark.usefixtures("mock_adobe_config")


@pytest.fixture
def renewal_now_order(order_factory, order_parameters_factory, lines_factory, renewal_payload):
    lines = lines_factory(
        line_id=1, item_id=1, external_vendor_id="65304578CA", quantity=15
    ) + lines_factory(line_id=2, item_id=2, external_vendor_id="77777777CA", quantity=10)
    payload = {**renewal_payload, "renewalPath": "now"}
    return order_factory(
        order_type="Change",
        order_parameters=order_parameters_factory(renewal_payload=payload),
        lines=lines,
    )


@pytest.fixture
def renewal_now_context(renewal_now_order, renewal_payload):
    return Context(
        order=renewal_now_order,
        order_id=renewal_now_order["id"],
        product_id="PRD-1111-1111",
        authorization_id="authorization-id",
        adobe_customer_id="customer-id",
        renewal_payload={**renewal_payload, "renewalPath": "now"},
    )


def plan_entry(
    subscription_id="renewing-sub-id",
    offer_id="65304578CA01A12",
    renew=True,  # ruff:ignore[boolean-default-value-positional-argument]
    renewal_quantity=15,
    flex_discount_codes=None,
    snapshot_enabled=True,  # ruff:ignore[boolean-default-value-positional-argument]
    snapshot_quantity=10,
    snapshot_codes=None,
    snapshot_renewed_quantity=None,
):
    return {
        "subscription_id": subscription_id,
        "offer_id": offer_id,
        "renew": renew,
        "renewal_quantity": renewal_quantity,
        "flex_discount_codes": flex_discount_codes or [],
        "snapshot": {
            "enabled": snapshot_enabled,
            "renewal_quantity": snapshot_quantity,
            "flex_discount_codes": snapshot_codes or [],
            "renewed_quantity": snapshot_renewed_quantity,
        },
    }


def test_preview_renewal_now_order_step_no_renewing_subscriptions(
    mocker, mock_adobe_client, mock_mpt_client, renewal_now_context
):
    renewal_now_context.renewal_plan_subscriptions = [
        plan_entry(subscription_id="lapsing-sub-id", renew=False, renewal_quantity=0),
    ]
    mocked_next_step = mocker.MagicMock()
    step = PreviewRenewalNowOrder()

    step(mock_mpt_client, renewal_now_context, mocked_next_step)  # act

    mock_adobe_client.create_renewal_order.assert_not_called()
    mock_adobe_client.get_orders.assert_not_called()
    mocked_next_step.assert_called_once_with(mock_mpt_client, renewal_now_context)


def test_preview_renewal_now_order_step_existing_order_skips_preview(
    mocker, mock_adobe_client, mock_mpt_client, renewal_now_context, adobe_order_factory
):
    renewal_now_context.renewal_plan_subscriptions = [plan_entry()]
    existing_order = adobe_order_factory(
        order_type="RENEWAL",
        status=AdobeOrderStatus.COMPLETE.value,
        external_id=renewal_now_context.order_id,
        order_id="ADOBE-RENEWAL-EXISTING",
    )
    mock_adobe_client.get_orders.return_value = [existing_order]
    mocked_next_step = mocker.MagicMock()
    step = PreviewRenewalNowOrder()

    step(mock_mpt_client, renewal_now_context, mocked_next_step)  # act

    mock_adobe_client.create_renewal_order.assert_not_called()
    assert renewal_now_context.preview_renewal_order is None
    mocked_next_step.assert_called_once_with(mock_mpt_client, renewal_now_context)


def test_preview_renewal_now_order_step_validates_preview(
    mocker, mock_adobe_client, mock_mpt_client, renewal_now_context, adobe_order_factory
):
    renewal_now_context.renewal_plan_subscriptions = [plan_entry(flex_discount_codes=["CODE-1"])]
    mock_adobe_client.get_orders.return_value = []
    preview_order = adobe_order_factory(
        order_type="PREVIEW_RENEWAL", status=AdobeOrderStatus.COMPLETE.value
    )
    mock_adobe_client.create_renewal_order.return_value = preview_order
    mocked_next_step = mocker.MagicMock()
    step = PreviewRenewalNowOrder()

    step(mock_mpt_client, renewal_now_context, mocked_next_step)  # act

    mock_adobe_client.get_orders.assert_called_once_with(
        renewal_now_context.authorization_id,
        renewal_now_context.adobe_customer_id,
        filters={"order-type": ORDER_TYPE_RENEWAL},
    )
    mock_adobe_client.create_renewal_order.assert_called_once_with(
        renewal_now_context.authorization_id,
        renewal_now_context.adobe_customer_id,
        renewal_now_context.order_id,
        [
            {
                "extLineItemNumber": 1,
                "offerId": "65304578CA01A12",
                "subscriptionId": "renewing-sub-id",
                "quantity": 15,
                "flexDiscountCodes": ["CODE-1"],
            },
        ],
        order_type=ORDER_TYPE_PREVIEW_RENEWAL,
    )
    assert renewal_now_context.preview_renewal_order == preview_order
    mocked_next_step.assert_called_once_with(mock_mpt_client, renewal_now_context)


def test_preview_renewal_now_order_step_includes_already_renewed_subscription(
    mocker, mock_adobe_client, mock_mpt_client, renewal_now_context, adobe_order_factory
):
    """A renewing sub already committed in a previous renewal order is re-submitted normally."""
    renewal_now_context.renewal_plan_subscriptions = [plan_entry(snapshot_renewed_quantity=9)]
    mock_adobe_client.get_orders.return_value = []
    mock_adobe_client.create_renewal_order.return_value = adobe_order_factory(
        order_type="PREVIEW_RENEWAL", status=AdobeOrderStatus.COMPLETE.value
    )
    mocked_next_step = mocker.MagicMock()
    step = PreviewRenewalNowOrder()

    step(mock_mpt_client, renewal_now_context, mocked_next_step)  # act

    mock_adobe_client.create_renewal_order.assert_called_once_with(
        renewal_now_context.authorization_id,
        renewal_now_context.adobe_customer_id,
        renewal_now_context.order_id,
        [
            {
                "extLineItemNumber": 1,
                "offerId": "65304578CA01A12",
                "subscriptionId": "renewing-sub-id",
                "quantity": 15,
            },
        ],
        order_type=ORDER_TYPE_PREVIEW_RENEWAL,
    )
    mocked_next_step.assert_called_once_with(mock_mpt_client, renewal_now_context)


def test_preview_renewal_now_order_step_excludes_already_renewed_without_change(
    mocker, mock_adobe_client, mock_mpt_client, renewal_now_context, adobe_order_factory
):
    """A renewing sub already renewed with no requested quantity is left out of the preview."""
    renewal_now_context.renewal_plan_subscriptions = [
        plan_entry(
            subscription_id="already-renewed-sub-id",
            offer_id="77777777CA01A12",
            renewal_quantity=0,
            snapshot_renewed_quantity=9,
        ),
        plan_entry(),
    ]
    mock_adobe_client.get_orders.return_value = []
    mock_adobe_client.create_renewal_order.return_value = adobe_order_factory(
        order_type="PREVIEW_RENEWAL", status=AdobeOrderStatus.COMPLETE.value
    )
    mocked_next_step = mocker.MagicMock()
    step = PreviewRenewalNowOrder()

    step(mock_mpt_client, renewal_now_context, mocked_next_step)  # act

    mock_adobe_client.create_renewal_order.assert_called_once_with(
        renewal_now_context.authorization_id,
        renewal_now_context.adobe_customer_id,
        renewal_now_context.order_id,
        [
            {
                "extLineItemNumber": 1,
                "offerId": "65304578CA01A12",
                "subscriptionId": "renewing-sub-id",
                "quantity": 15,
            },
        ],
        order_type=ORDER_TYPE_PREVIEW_RENEWAL,
    )
    mocked_next_step.assert_called_once_with(mock_mpt_client, renewal_now_context)


def test_preview_renewal_now_order_step_all_already_renewed_skips_preview(
    mocker, mock_adobe_client, mock_mpt_client, renewal_now_context
):
    renewal_now_context.renewal_plan_subscriptions = [
        plan_entry(renewal_quantity=0, snapshot_renewed_quantity=9),
    ]
    mocked_next_step = mocker.MagicMock()
    step = PreviewRenewalNowOrder()

    step(mock_mpt_client, renewal_now_context, mocked_next_step)  # act

    mock_adobe_client.get_orders.assert_not_called()
    mock_adobe_client.create_renewal_order.assert_not_called()
    mocked_next_step.assert_called_once_with(mock_mpt_client, renewal_now_context)


def test_submit_renewal_now_order_step_all_already_renewed_skips_order(
    mocker, mock_adobe_client, mock_mpt_client, renewal_now_context
):
    renewal_now_context.renewal_plan_subscriptions = [
        plan_entry(renewal_quantity=0, snapshot_renewed_quantity=9),
    ]
    mocked_next_step = mocker.MagicMock()
    step = SubmitRenewalNowOrder()

    step(mock_mpt_client, renewal_now_context, mocked_next_step)  # act

    mock_adobe_client.get_orders.assert_not_called()
    mock_adobe_client.create_renewal_order.assert_not_called()
    mocked_next_step.assert_called_once_with(mock_mpt_client, renewal_now_context)


def test_preview_renewal_now_order_step_preview_failed(
    mocker, mock_adobe_client, mock_mpt_client, renewal_now_context, adobe_api_error_factory
):
    renewal_now_context.renewal_plan_subscriptions = [plan_entry()]
    mock_adobe_client.get_orders.return_value = []
    mock_adobe_client.create_renewal_order.side_effect = AdobeAPIError(
        400,
        adobe_api_error_factory(
            code=AdobeErrorCode.INVALID_FIELDS.value,
            message="Invalid discount code",
        ),
    )
    mocked_switch_to_failed = mocker.patch(
        "adobe_vipm.flows.fulfillment.renewal_now.switch_order_to_failed"
    )
    mocked_next_step = mocker.MagicMock()
    step = PreviewRenewalNowOrder()

    step(mock_mpt_client, renewal_now_context, mocked_next_step)  # act

    mocked_switch_to_failed.assert_called_once()
    assert "Invalid discount code" in mocked_switch_to_failed.mock_calls[0].args[2]["message"]
    assert renewal_now_context.preview_renewal_order is None
    mocked_next_step.assert_not_called()


def test_submit_renewal_now_order_step_no_renewing_subscriptions(
    mocker, mock_adobe_client, mock_mpt_client, renewal_now_context
):
    renewal_now_context.renewal_plan_subscriptions = [
        plan_entry(subscription_id="lapsing-sub-id", renew=False, renewal_quantity=0),
    ]
    mocked_next_step = mocker.MagicMock()
    step = SubmitRenewalNowOrder()

    step(mock_mpt_client, renewal_now_context, mocked_next_step)  # act

    mock_adobe_client.get_orders.assert_not_called()
    mock_adobe_client.create_renewal_order.assert_not_called()
    mocked_next_step.assert_called_once_with(mock_mpt_client, renewal_now_context)


def test_submit_renewal_now_order_step_no_preview_available(
    mocker, mock_adobe_client, mock_mpt_client, renewal_now_context
):
    """Defensive fallback if this step ever runs without PreviewRenewalNowOrder first."""
    renewal_now_context.renewal_plan_subscriptions = [plan_entry()]
    renewal_now_context.preview_renewal_order = None
    mock_adobe_client.get_orders.return_value = []
    mocked_next_step = mocker.MagicMock()
    step = SubmitRenewalNowOrder()

    step(mock_mpt_client, renewal_now_context, mocked_next_step)  # act

    mock_adobe_client.create_renewal_order.assert_not_called()
    assert renewal_now_context.adobe_renewal_order is None
    mocked_next_step.assert_called_once_with(mock_mpt_client, renewal_now_context)


def test_submit_renewal_now_order_step_existing_order_reused(
    mocker, mock_adobe_client, mock_mpt_client, renewal_now_context, adobe_order_factory
):
    renewal_now_context.renewal_plan_subscriptions = [plan_entry()]
    existing_order = adobe_order_factory(
        order_type="RENEWAL",
        status=AdobeOrderStatus.COMPLETE.value,
        external_id=renewal_now_context.order_id,
        order_id="ADOBE-RENEWAL-EXISTING",
    )
    mock_adobe_client.get_orders.return_value = [existing_order]
    mocked_next_step = mocker.MagicMock()
    step = SubmitRenewalNowOrder()

    step(mock_mpt_client, renewal_now_context, mocked_next_step)  # act

    mock_adobe_client.create_renewal_order.assert_not_called()
    assert renewal_now_context.adobe_renewal_order == existing_order
    mocked_next_step.assert_called_once_with(mock_mpt_client, renewal_now_context)


def test_submit_renewal_now_order_step_commits_order(
    mocker, mock_adobe_client, mock_mpt_client, renewal_now_context, adobe_order_factory
):
    renewal_now_context.renewal_plan_subscriptions = [plan_entry(flex_discount_codes=["CODE-1"])]
    # The preview response (set by PreviewRenewalNowOrder in a prior pipeline step) is
    # response-shaped (flexDiscounts, pricing) and can resolve a different quantity than
    # requested (e.g. Adobe adjusting it) — both must be honored.
    renewal_now_context.preview_renewal_order = adobe_order_factory(
        order_type="PREVIEW_RENEWAL",
        status=AdobeOrderStatus.COMPLETE.value,
        items=[
            {
                "extLineItemNumber": 1,
                "offerId": "65304578CA01A12",
                "subscriptionId": "renewing-sub-id",
                "quantity": 14,
                "flexDiscounts": [{"code": "CODE-1", "result": "SUCCESS"}],
                "pricing": {"unitPP": "10.00"},
            },
        ],
    )
    mocked_update_order = mocker.patch("adobe_vipm.flows.fulfillment.renewal_now.update_order")
    renewal_order = adobe_order_factory(
        order_type="RENEWAL",
        status=AdobeOrderStatus.COMPLETE.value,
        order_id="ADOBE-RENEWAL-001",
    )
    mock_adobe_client.get_orders.return_value = []
    mock_adobe_client.create_renewal_order.return_value = renewal_order
    mocked_next_step = mocker.MagicMock()
    step = SubmitRenewalNowOrder()

    step(mock_mpt_client, renewal_now_context, mocked_next_step)  # act

    mock_adobe_client.get_orders.assert_called_once_with(
        renewal_now_context.authorization_id,
        renewal_now_context.adobe_customer_id,
        filters={"order-type": ORDER_TYPE_RENEWAL},
    )
    mock_adobe_client.create_renewal_order.assert_called_once_with(
        renewal_now_context.authorization_id,
        renewal_now_context.adobe_customer_id,
        renewal_now_context.order_id,
        [
            {
                "extLineItemNumber": 1,
                "offerId": "65304578CA01A12",
                "subscriptionId": "renewing-sub-id",
                "quantity": 14,
                "flexDiscountCodes": ["CODE-1"],
            },
        ],
    )
    mocked_update_order.assert_called_once_with(
        mock_mpt_client,
        renewal_now_context.order_id,
        parameters=renewal_now_context.order["parameters"],
    )
    assert renewal_now_context.adobe_renewal_order == renewal_order
    mocked_next_step.assert_called_once_with(mock_mpt_client, renewal_now_context)


def test_submit_renewal_now_order_step_order_failed(
    mocker, mock_adobe_client, mock_mpt_client, renewal_now_context, adobe_api_error_factory
):
    renewal_now_context.renewal_plan_subscriptions = [plan_entry()]
    renewal_now_context.preview_renewal_order = {
        "lineItems": [
            {
                "extLineItemNumber": 1,
                "offerId": "65304578CA01A12",
                "subscriptionId": "renewing-sub-id",
                "quantity": 15,
            },
        ],
    }
    mock_adobe_client.get_orders.return_value = []
    mock_adobe_client.create_renewal_order.side_effect = AdobeAPIError(
        400, adobe_api_error_factory("9999", "order error")
    )
    mocked_switch_to_failed = mocker.patch(
        "adobe_vipm.flows.fulfillment.renewal_now.switch_order_to_failed"
    )
    mocked_next_step = mocker.MagicMock()
    step = SubmitRenewalNowOrder()

    step(mock_mpt_client, renewal_now_context, mocked_next_step)  # act

    mocked_switch_to_failed.assert_called_once()
    assert "order error" in mocked_switch_to_failed.mock_calls[0].args[2]["message"]
    assert renewal_now_context.adobe_renewal_order is None
    mocked_next_step.assert_not_called()


def test_submit_renewal_now_order_step_pending(
    mocker, mock_adobe_client, mock_mpt_client, renewal_now_context, adobe_order_factory
):
    renewal_now_context.renewal_plan_subscriptions = [plan_entry()]
    renewal_now_context.preview_renewal_order = {
        "lineItems": [
            {
                "extLineItemNumber": 1,
                "offerId": "65304578CA01A12",
                "subscriptionId": "renewing-sub-id",
                "quantity": 15,
            },
        ],
    }
    mocker.patch("adobe_vipm.flows.fulfillment.renewal_now.update_order")
    renewal_order = adobe_order_factory(order_type="RENEWAL", status=AdobeOrderStatus.OPEN.value)
    mock_adobe_client.get_orders.return_value = []
    mock_adobe_client.create_renewal_order.return_value = renewal_order
    mocked_next_step = mocker.MagicMock()
    step = SubmitRenewalNowOrder()

    step(mock_mpt_client, renewal_now_context, mocked_next_step)  # act

    assert renewal_now_context.adobe_renewal_order is None
    mocked_next_step.assert_not_called()


def test_submit_renewal_now_order_step_unrecoverable_status(
    mocker, mock_adobe_client, mock_mpt_client, renewal_now_context, adobe_order_factory
):
    renewal_now_context.renewal_plan_subscriptions = [plan_entry()]
    renewal_now_context.preview_renewal_order = {
        "lineItems": [
            {
                "extLineItemNumber": 1,
                "offerId": "65304578CA01A12",
                "subscriptionId": "renewing-sub-id",
                "quantity": 15,
            },
        ],
    }
    mocker.patch("adobe_vipm.flows.fulfillment.renewal_now.update_order")
    renewal_order = adobe_order_factory(
        order_type="RENEWAL",
        status=AdobeOrderStatus.FAILED.value,
        order_id="ADOBE-RENEWAL-002",
    )
    mock_adobe_client.get_orders.return_value = []
    mock_adobe_client.create_renewal_order.return_value = renewal_order
    mocked_switch_to_failed = mocker.patch(
        "adobe_vipm.flows.fulfillment.renewal_now.switch_order_to_failed"
    )
    mocked_next_step = mocker.MagicMock()
    step = SubmitRenewalNowOrder()

    step(mock_mpt_client, renewal_now_context, mocked_next_step)  # act

    mocked_switch_to_failed.assert_called_once()
    assert renewal_now_context.adobe_renewal_order is None
    mocked_next_step.assert_not_called()


def test_submit_renewal_now_order_step_unexpected_status(
    mocker, mock_adobe_client, mock_mpt_client, renewal_now_context, adobe_order_factory
):
    renewal_now_context.renewal_plan_subscriptions = [plan_entry()]
    renewal_now_context.preview_renewal_order = {
        "lineItems": [
            {
                "extLineItemNumber": 1,
                "offerId": "65304578CA01A12",
                "subscriptionId": "renewing-sub-id",
                "quantity": 15,
            },
        ],
    }
    mocker.patch("adobe_vipm.flows.fulfillment.renewal_now.update_order")
    renewal_order = {
        **adobe_order_factory(order_type="RENEWAL", order_id="ADOBE-RENEWAL-003"),
        "status": "9999",
    }
    mock_adobe_client.get_orders.return_value = []
    mock_adobe_client.create_renewal_order.return_value = renewal_order
    mocked_switch_to_failed = mocker.patch(
        "adobe_vipm.flows.fulfillment.renewal_now.switch_order_to_failed"
    )
    mocked_next_step = mocker.MagicMock()
    step = SubmitRenewalNowOrder()

    step(mock_mpt_client, renewal_now_context, mocked_next_step)  # act

    mocked_switch_to_failed.assert_called_once()
    assert renewal_now_context.adobe_renewal_order is None
    mocked_next_step.assert_not_called()


def test_normalize_renewed_subscriptions_step(
    mocker, mock_adobe_client, mock_mpt_client, renewal_now_context
):
    renewal_now_context.renewal_plan_subscriptions = [
        plan_entry(),
        plan_entry(subscription_id="lapsing-sub-id", renew=False, renewal_quantity=0),
    ]
    mock_adobe_client.get_subscription.return_value = {
        "subscriptionId": "renewing-sub-id",
        "renewedQuantity": 9,
    }
    mocked_next_step = mocker.MagicMock()
    step = NormalizeRenewedSubscriptions()

    step(mock_mpt_client, renewal_now_context, mocked_next_step)  # act

    mock_adobe_client.get_subscription.assert_called_once_with(
        renewal_now_context.authorization_id,
        renewal_now_context.adobe_customer_id,
        "renewing-sub-id",
    )
    mock_adobe_client.update_subscription.assert_called_once_with(
        renewal_now_context.authorization_id,
        renewal_now_context.adobe_customer_id,
        "renewing-sub-id",
        auto_renewal=True,
        quantity=9,
    )
    mocked_next_step.assert_called_once_with(mock_mpt_client, renewal_now_context)


def test_normalize_renewed_subscriptions_step_already_renewed_excluded(
    mocker, mock_adobe_client, mock_mpt_client, renewal_now_context
):
    """A sub renewed by a PREVIOUS order keeps what that order set — no re-fetch, no PATCH."""
    renewal_now_context.renewal_plan_subscriptions = [
        plan_entry(renewal_quantity=0, snapshot_renewed_quantity=9),
    ]
    mocked_next_step = mocker.MagicMock()
    step = NormalizeRenewedSubscriptions()

    step(mock_mpt_client, renewal_now_context, mocked_next_step)  # act

    mock_adobe_client.get_subscription.assert_not_called()
    mock_adobe_client.update_subscription.assert_not_called()
    mocked_next_step.assert_called_once_with(mock_mpt_client, renewal_now_context)


def test_normalize_renewed_subscriptions_step_no_renewed_quantity_skips_patch(
    mocker, mock_adobe_client, mock_mpt_client, renewal_now_context
):
    renewal_now_context.renewal_plan_subscriptions = [plan_entry()]
    mock_adobe_client.get_subscription.return_value = {"subscriptionId": "renewing-sub-id"}
    mocked_next_step = mocker.MagicMock()
    step = NormalizeRenewedSubscriptions()

    step(mock_mpt_client, renewal_now_context, mocked_next_step)  # act

    mock_adobe_client.update_subscription.assert_not_called()
    mocked_next_step.assert_called_once_with(mock_mpt_client, renewal_now_context)


def test_normalize_renewed_subscriptions_step_get_subscription_error(
    mocker, mock_adobe_client, mock_mpt_client, renewal_now_context, adobe_api_error_factory
):
    renewal_now_context.renewal_plan_subscriptions = [plan_entry()]
    mock_adobe_client.get_subscription.side_effect = AdobeAPIError(
        400, adobe_api_error_factory("9999", "cannot fetch subscription")
    )
    mocked_switch_to_failed = mocker.patch(
        "adobe_vipm.flows.fulfillment.renewal_now.switch_order_to_failed"
    )
    mocked_next_step = mocker.MagicMock()
    step = NormalizeRenewedSubscriptions()

    step(mock_mpt_client, renewal_now_context, mocked_next_step)  # act

    mocked_switch_to_failed.assert_called_once()
    assert "renewing-sub-id" in mocked_switch_to_failed.mock_calls[0].args[2]["message"]
    mock_adobe_client.update_subscription.assert_not_called()
    mocked_next_step.assert_not_called()


def test_normalize_renewed_subscriptions_step_update_subscription_error(
    mocker, mock_adobe_client, mock_mpt_client, renewal_now_context, adobe_api_error_factory
):
    renewal_now_context.renewal_plan_subscriptions = [plan_entry()]
    mock_adobe_client.get_subscription.return_value = {
        "subscriptionId": "renewing-sub-id",
        "renewedQuantity": 9,
    }
    mock_adobe_client.update_subscription.side_effect = AdobeAPIError(
        400, adobe_api_error_factory("9999", "cannot patch subscription")
    )
    mocked_switch_to_failed = mocker.patch(
        "adobe_vipm.flows.fulfillment.renewal_now.switch_order_to_failed"
    )
    mocked_next_step = mocker.MagicMock()
    step = NormalizeRenewedSubscriptions()

    step(mock_mpt_client, renewal_now_context, mocked_next_step)  # act

    mocked_switch_to_failed.assert_called_once()
    assert "renewing-sub-id" in mocked_switch_to_failed.mock_calls[0].args[2]["message"]
    mocked_next_step.assert_not_called()


def test_disable_lapsing_subscriptions_step(
    mocker, mock_adobe_client, mock_mpt_client, renewal_now_context
):
    renewal_now_context.renewal_plan_subscriptions = [
        plan_entry(),
        plan_entry(subscription_id="lapsing-sub-id", renew=False, renewal_quantity=0),
    ]
    mocked_next_step = mocker.MagicMock()
    step = DisableLapsingSubscriptions()

    step(mock_mpt_client, renewal_now_context, mocked_next_step)  # act

    mock_adobe_client.update_subscription.assert_called_once_with(
        renewal_now_context.authorization_id,
        renewal_now_context.adobe_customer_id,
        "lapsing-sub-id",
        auto_renewal=False,
    )
    mocked_next_step.assert_called_once_with(mock_mpt_client, renewal_now_context)


def test_disable_lapsing_subscriptions_step_already_disabled_skips(
    mocker, mock_adobe_client, mock_mpt_client, renewal_now_context
):
    renewal_now_context.renewal_plan_subscriptions = [
        plan_entry(
            subscription_id="lapsing-sub-id",
            renew=False,
            renewal_quantity=0,
            snapshot_enabled=False,
        ),
    ]
    mocked_next_step = mocker.MagicMock()
    step = DisableLapsingSubscriptions()

    step(mock_mpt_client, renewal_now_context, mocked_next_step)  # act

    mock_adobe_client.update_subscription.assert_not_called()
    mocked_next_step.assert_called_once_with(mock_mpt_client, renewal_now_context)


def test_disable_lapsing_subscriptions_step_adobe_error(
    mocker, mock_adobe_client, mock_mpt_client, renewal_now_context, adobe_api_error_factory
):
    renewal_now_context.renewal_plan_subscriptions = [
        plan_entry(subscription_id="lapsing-sub-id", renew=False, renewal_quantity=0),
    ]
    mock_adobe_client.update_subscription.side_effect = AdobeAPIError(
        400, adobe_api_error_factory("9999", "cannot disable")
    )
    mocked_switch_to_failed = mocker.patch(
        "adobe_vipm.flows.fulfillment.renewal_now.switch_order_to_failed"
    )
    mocked_next_step = mocker.MagicMock()
    step = DisableLapsingSubscriptions()

    step(mock_mpt_client, renewal_now_context, mocked_next_step)  # act

    mocked_switch_to_failed.assert_called_once()
    assert "lapsing-sub-id" in mocked_switch_to_failed.mock_calls[0].args[2]["message"]
    mocked_next_step.assert_not_called()


def lapsing_renewed_plan_entry(renewed_quantity=10):
    return plan_entry(
        subscription_id="lapsing-sub-id",
        offer_id="77777777CA01A12",
        renew=False,
        renewal_quantity=0,
        snapshot_renewed_quantity=renewed_quantity,
    )


def previous_renewal_order_factory(
    adobe_order_factory,
    order_id="ADOBE-RENEWAL-PREV",
    external_id="ORD-PREVIOUS",
    creation_date="2026-08-01T10:00:00Z",
    subscription_id="lapsing-sub-id",
    deployment_id=None,
):
    line_item = {
        "extLineItemNumber": 1,
        "offerId": "77777777CA01A12",
        "subscriptionId": subscription_id,
        "quantity": 10,
    }
    if deployment_id:
        line_item["deploymentId"] = deployment_id
    return adobe_order_factory(
        order_type="RENEWAL",
        status=AdobeOrderStatus.COMPLETE.value,
        external_id=external_id,
        order_id=order_id,
        creation_date=creation_date,
        items=[line_item],
    )


def test_return_previous_renewal_orders_step_no_candidates(
    mocker, mock_adobe_client, mock_mpt_client, renewal_now_context
):
    renewal_now_context.renewal_plan_subscriptions = [
        # Renewing sub already renewed: handled by the RENEWAL order, not returned.
        plan_entry(snapshot_renewed_quantity=9),
        # Lapsing sub never committed in a previous renewal order: nothing to return.
        plan_entry(subscription_id="lapsing-sub-id", renew=False, renewal_quantity=0),
    ]
    mocked_next_step = mocker.MagicMock()
    step = ReturnPreviousRenewalOrders()

    step(mock_mpt_client, renewal_now_context, mocked_next_step)  # act

    mock_adobe_client.get_orders.assert_not_called()
    mock_adobe_client.get_return_orders_by_external_reference.assert_not_called()
    mock_adobe_client.create_return_order.assert_not_called()
    mocked_next_step.assert_called_once_with(mock_mpt_client, renewal_now_context)


def test_return_previous_renewal_orders_step_creates_return(
    mocker, mock_adobe_client, mock_mpt_client, renewal_now_context, adobe_order_factory
):
    renewal_now_context.renewal_plan_subscriptions = [lapsing_renewed_plan_entry()]
    previous_renewal = previous_renewal_order_factory(adobe_order_factory)
    mock_adobe_client.get_orders.return_value = [previous_renewal]
    mock_adobe_client.get_return_orders_by_external_reference.return_value = {}
    return_order = adobe_order_factory(
        order_type="RETURN",
        status=AdobeOrderStatus.COMPLETE.value,
        order_id="ADOBE-RETURN-001",
        reference_order_id="ADOBE-RENEWAL-PREV",
    )
    mock_adobe_client.create_return_order.return_value = return_order
    mocked_update_order = mocker.patch("adobe_vipm.flows.fulfillment.renewal_now.update_order")
    mocked_next_step = mocker.MagicMock()
    step = ReturnPreviousRenewalOrders()

    step(mock_mpt_client, renewal_now_context, mocked_next_step)  # act

    mock_adobe_client.get_orders.assert_called_once_with(
        renewal_now_context.authorization_id,
        renewal_now_context.adobe_customer_id,
        filters={
            "order-type": ORDER_TYPE_RENEWAL,
            "status": AdobeOrderStatus.COMPLETE,
        },
    )
    mock_adobe_client.get_return_orders_by_external_reference.assert_called_once_with(
        renewal_now_context.authorization_id,
        renewal_now_context.adobe_customer_id,
        renewal_now_context.order_id,
    )
    mock_adobe_client.create_return_order.assert_called_once_with(
        renewal_now_context.authorization_id,
        renewal_now_context.adobe_customer_id,
        previous_renewal,
        previous_renewal["lineItems"][0],
        renewal_now_context.order_id,
        None,
    )
    mocked_update_order.assert_called_once_with(
        mock_mpt_client,
        renewal_now_context.order_id,
        parameters=renewal_now_context.order["parameters"],
    )
    mocked_next_step.assert_called_once_with(mock_mpt_client, renewal_now_context)


def test_return_previous_renewal_orders_step_existing_return_reused(
    mocker, mock_adobe_client, mock_mpt_client, renewal_now_context, adobe_order_factory
):
    renewal_now_context.renewal_plan_subscriptions = [lapsing_renewed_plan_entry()]
    mock_adobe_client.get_orders.return_value = [
        previous_renewal_order_factory(adobe_order_factory)
    ]
    existing_return = adobe_order_factory(
        order_type="RETURN",
        status=AdobeOrderStatus.COMPLETE.value,
        order_id="ADOBE-RETURN-EXISTING",
    )
    mock_adobe_client.get_return_orders_by_external_reference.return_value = {
        "77777777CA": [existing_return],
    }
    mocked_next_step = mocker.MagicMock()
    step = ReturnPreviousRenewalOrders()

    step(mock_mpt_client, renewal_now_context, mocked_next_step)  # act

    mock_adobe_client.create_return_order.assert_not_called()
    mocked_next_step.assert_called_once_with(mock_mpt_client, renewal_now_context)


def test_return_previous_renewal_orders_step_pending_return(
    mocker, mock_adobe_client, mock_mpt_client, renewal_now_context, adobe_order_factory
):
    renewal_now_context.renewal_plan_subscriptions = [lapsing_renewed_plan_entry()]
    mock_adobe_client.get_orders.return_value = [
        previous_renewal_order_factory(adobe_order_factory)
    ]
    mock_adobe_client.get_return_orders_by_external_reference.return_value = {}
    mock_adobe_client.create_return_order.return_value = adobe_order_factory(
        order_type="RETURN",
        status=AdobeOrderStatus.OPEN.value,
        order_id="ADOBE-RETURN-PENDING",
    )
    mocker.patch("adobe_vipm.flows.fulfillment.renewal_now.update_order")
    mocked_switch_to_failed = mocker.patch(
        "adobe_vipm.flows.fulfillment.renewal_now.switch_order_to_failed"
    )
    mocked_next_step = mocker.MagicMock()
    step = ReturnPreviousRenewalOrders()

    step(mock_mpt_client, renewal_now_context, mocked_next_step)  # act

    mocked_switch_to_failed.assert_not_called()
    mocked_next_step.assert_not_called()


def test_return_previous_renewal_orders_step_previous_order_not_found(
    mocker, mock_adobe_client, mock_mpt_client, renewal_now_context
):
    renewal_now_context.renewal_plan_subscriptions = [lapsing_renewed_plan_entry()]
    mock_adobe_client.get_orders.return_value = []
    mock_adobe_client.get_return_orders_by_external_reference.return_value = {}
    mocked_switch_to_failed = mocker.patch(
        "adobe_vipm.flows.fulfillment.renewal_now.switch_order_to_failed"
    )
    mocked_next_step = mocker.MagicMock()
    step = ReturnPreviousRenewalOrders()

    step(mock_mpt_client, renewal_now_context, mocked_next_step)  # act

    mock_adobe_client.create_return_order.assert_not_called()
    mocked_switch_to_failed.assert_called_once()
    assert "lapsing-sub-id" in mocked_switch_to_failed.mock_calls[0].args[2]["message"]
    mocked_next_step.assert_not_called()


def test_return_previous_renewal_orders_step_return_failed(
    mocker,
    mock_adobe_client,
    mock_mpt_client,
    renewal_now_context,
    adobe_order_factory,
    adobe_api_error_factory,
):
    renewal_now_context.renewal_plan_subscriptions = [lapsing_renewed_plan_entry()]
    mock_adobe_client.get_orders.return_value = [
        previous_renewal_order_factory(adobe_order_factory)
    ]
    mock_adobe_client.get_return_orders_by_external_reference.return_value = {}
    mock_adobe_client.create_return_order.side_effect = AdobeAPIError(
        400, adobe_api_error_factory("9999", "cannot return")
    )
    mocked_switch_to_failed = mocker.patch(
        "adobe_vipm.flows.fulfillment.renewal_now.switch_order_to_failed"
    )
    mocked_next_step = mocker.MagicMock()
    step = ReturnPreviousRenewalOrders()

    step(mock_mpt_client, renewal_now_context, mocked_next_step)  # act

    mocked_switch_to_failed.assert_called_once()
    assert "cannot return" in mocked_switch_to_failed.mock_calls[0].args[2]["message"]
    mocked_next_step.assert_not_called()


def test_return_previous_renewal_orders_step_picks_most_recent_order(
    mocker, mock_adobe_client, mock_mpt_client, renewal_now_context, adobe_order_factory
):
    renewal_now_context.renewal_plan_subscriptions = [lapsing_renewed_plan_entry()]
    older_renewal = previous_renewal_order_factory(
        adobe_order_factory,
        order_id="ADOBE-RENEWAL-OLDER",
        external_id="ORD-OLDER",
        creation_date="2026-07-01T10:00:00Z",
    )
    newer_renewal = previous_renewal_order_factory(
        adobe_order_factory,
        order_id="ADOBE-RENEWAL-NEWER",
        external_id="ORD-NEWER",
        creation_date="2026-08-01T10:00:00Z",
    )
    # The renewal order committed by this very MPT order never contains lapsing
    # subscriptions, but it is excluded defensively even if it did.
    own_renewal = previous_renewal_order_factory(
        adobe_order_factory,
        order_id="ADOBE-RENEWAL-OWN",
        external_id=renewal_now_context.order_id,
        creation_date="2026-08-10T10:00:00Z",
    )
    unrelated_renewal = previous_renewal_order_factory(
        adobe_order_factory,
        order_id="ADOBE-RENEWAL-UNRELATED",
        external_id="ORD-UNRELATED",
        creation_date="2026-08-05T10:00:00Z",
        subscription_id="other-sub-id",
    )
    mock_adobe_client.get_orders.return_value = [
        older_renewal,
        own_renewal,
        unrelated_renewal,
        newer_renewal,
    ]
    mock_adobe_client.get_return_orders_by_external_reference.return_value = {}
    mock_adobe_client.create_return_order.return_value = adobe_order_factory(
        order_type="RETURN",
        status=AdobeOrderStatus.COMPLETE.value,
        order_id="ADOBE-RETURN-001",
    )
    mocker.patch("adobe_vipm.flows.fulfillment.renewal_now.update_order")
    mocked_next_step = mocker.MagicMock()
    step = ReturnPreviousRenewalOrders()

    step(mock_mpt_client, renewal_now_context, mocked_next_step)  # act

    mock_adobe_client.create_return_order.assert_called_once_with(
        renewal_now_context.authorization_id,
        renewal_now_context.adobe_customer_id,
        newer_renewal,
        newer_renewal["lineItems"][0],
        renewal_now_context.order_id,
        None,
    )
    mocked_next_step.assert_called_once_with(mock_mpt_client, renewal_now_context)


def test_fulfill_renewal_now_order(mocker):
    mocked_pipeline_instance = mocker.MagicMock()
    mocked_pipeline_ctor = mocker.patch(
        "adobe_vipm.flows.fulfillment.renewal_now.Pipeline",
        return_value=mocked_pipeline_instance,
    )
    mocked_context = mocker.MagicMock()
    mocked_context_ctor = mocker.patch(
        "adobe_vipm.flows.fulfillment.renewal_now.Context", return_value=mocked_context
    )
    mocked_client = mocker.MagicMock()
    mocked_order = mocker.MagicMock()

    fulfill_renewal_now_order(mocked_client, mocked_order)  # act

    expected_steps = [
        SetupContext,
        StartOrderProcessing,
        SetupDueDate,
        ValidateDuplicateLines,
        SetOrUpdateCotermDate,
        UpdateAgreementParamsVisibility,
        ValidateRenewalWindow,
        SetupRenewalPlan,
        PreviewRenewalNowOrder,
        SubmitRenewalNowOrder,
        ReturnPreviousRenewalOrders,
        NormalizeRenewedSubscriptions,
        DisableLapsingSubscriptions,
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
