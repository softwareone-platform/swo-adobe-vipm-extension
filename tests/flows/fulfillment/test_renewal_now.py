import datetime as dt

import pytest
from freezegun import freeze_time

from adobe_vipm.adobe.constants import (
    CANCELLATION_WINDOW_DAYS,
    ORDER_TYPE_PREVIEW_RENEWAL,
    ORDER_TYPE_RENEWAL,
    AdobeErrorCode,
    AdobeOrderStatus,
)
from adobe_vipm.adobe.errors import AdobeAPIError
from adobe_vipm.flows.constants import TEMPLATE_NAME_CHANGE
from adobe_vipm.flows.context import Context
from adobe_vipm.flows.fulfillment.renewal import (
    CreateNetNewMptSubscriptions,
    RecordClientDiscountCodes,
    RecordDiscountRedemptions,
    Validate3YCRenewalFloor,
    ValidateNetNewOrderLines,
)
from adobe_vipm.flows.fulfillment.renewal_now import (
    DisableLapsingSubscriptions,
    NormalizeRenewedSubscriptions,
    PreviewRenewalNowOrder,
    ResolveNetNewRenewedSubscriptions,
    ResolvePreviousRenewalReturns,
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
    # Net-new handling is exercised by dedicated tests that add netNewItems and a
    # matching order line; the default order carries none.
    payload = {**renewal_payload, "renewalPath": "now", "netNewItems": []}
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
        renewal_payload={**renewal_payload, "renewalPath": "now", "netNewItems": []},
    )


@pytest.fixture
def net_new_item():
    return {"offerId": "65322651CA01A12", "quantity": 5, "flexDiscountCodes": ["CODE-3"]}


@pytest.fixture
def renewal_now_order_net_new(
    order_factory, order_parameters_factory, lines_factory, renewal_payload, net_new_item
):
    lines = (
        lines_factory(line_id=1, item_id=1, external_vendor_id="65304578CA", quantity=15)
        + lines_factory(line_id=2, item_id=2, external_vendor_id="77777777CA", quantity=10)
        + lines_factory(line_id=3, item_id=3, external_vendor_id="65322651CA", quantity=5)
    )
    payload = {**renewal_payload, "renewalPath": "now", "netNewItems": [net_new_item]}
    return order_factory(
        order_type="Change",
        order_parameters=order_parameters_factory(renewal_payload=payload),
        lines=lines,
    )


@pytest.fixture
def renewal_now_context_net_new(renewal_now_order_net_new, renewal_payload, net_new_item):
    return Context(
        order=renewal_now_order_net_new,
        order_id=renewal_now_order_net_new["id"],
        product_id="PRD-1111-1111",
        authorization_id="authorization-id",
        adobe_customer_id="customer-id",
        renewal_payload={**renewal_payload, "renewalPath": "now", "netNewItems": [net_new_item]},
    )


def plan_entry(
    *,
    subscription_id="renewing-sub-id",
    offer_id="65304578CA01A12",
    renew=True,
    renewal_quantity=15,
    flex_discount_codes=None,
    snapshot_enabled=True,
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
        order_type="PREVIEW_RENEWAL",
        status=AdobeOrderStatus.COMPLETE.value,
        items=[
            {
                "extLineItemNumber": 1,
                "offerId": "65304578CA01A12",
                "quantity": 15,
                "flexDiscounts": [{"code": "CODE-1", "result": "SUCCESS"}],
            },
        ],
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
        recommendation_tracker_id=renewal_now_context.renewal_payload["recommendationTrackerId"],
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
        recommendation_tracker_id=renewal_now_context.renewal_payload["recommendationTrackerId"],
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
        recommendation_tracker_id=renewal_now_context.renewal_payload["recommendationTrackerId"],
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


@pytest.mark.parametrize(
    ("flex_discounts", "reported"),
    [
        (
            [{"code": "CODE-1", "result": "FAILURE"}],
            "CODE-1 on subscription renewing-sub-id (FAILURE)",
        ),
        ([{"code": "CODE-1"}], "CODE-1 on subscription renewing-sub-id (no result)"),
        (None, "CODE-1 on subscription renewing-sub-id (no result)"),
    ],
)
def test_preview_renewal_now_order_step_fails_on_an_unconfirmed_selected_code(  # noqa: WPS211
    mocker,
    mock_adobe_client,
    mock_mpt_client,
    renewal_now_context,
    adobe_order_factory,
    flex_discounts,
    reported,
):
    """A selected code the preview did not confirm fails the order before the commit."""
    renewal_now_context.renewal_plan_subscriptions = [plan_entry(flex_discount_codes=["CODE-1"])]
    mock_adobe_client.get_orders.return_value = []
    # The response echoes no subscriptionId and a different offer level: the line is
    # still matched to the request by its extLineItemNumber.
    mock_adobe_client.create_renewal_order.return_value = adobe_order_factory(
        order_type="PREVIEW_RENEWAL",
        status=AdobeOrderStatus.COMPLETE.value,
        items=[
            {
                "extLineItemNumber": 1,
                "offerId": "65304578CA14A12",
                "subscriptionId": "",
                "quantity": 15,
                "flexDiscounts": flex_discounts,
            },
        ],
    )
    mocked_switch_to_failed = mocker.patch(
        "adobe_vipm.flows.fulfillment.renewal_now.switch_order_to_failed"
    )
    mocked_next_step = mocker.MagicMock()

    PreviewRenewalNowOrder()(mock_mpt_client, renewal_now_context, mocked_next_step)  # act

    error = mocked_switch_to_failed.mock_calls[0].args[2]
    assert error["id"] == "VIPM0056"
    assert reported in error["message"]
    mock_adobe_client.create_renewal_order.assert_called_once()
    mocked_next_step.assert_not_called()


def test_preview_renewal_now_order_step_fails_on_an_unconfirmed_net_new_code(
    mocker, mock_adobe_client, mock_mpt_client, renewal_now_context_net_new, adobe_order_factory
):
    """A refused code on a new product names the product in the failure."""
    renewal_now_context_net_new.renewal_plan_subscriptions = []
    mock_adobe_client.get_orders.return_value = []
    mock_adobe_client.create_renewal_order.return_value = adobe_order_factory(
        order_type="PREVIEW_RENEWAL",
        status=AdobeOrderStatus.COMPLETE.value,
        items=[
            {
                "extLineItemNumber": 1,
                "offerId": "65322651CA01A12",
                "quantity": 5,
                "flexDiscounts": [{"code": "CODE-3", "result": "FAILURE"}],
            },
        ],
    )
    mocked_switch_to_failed = mocker.patch(
        "adobe_vipm.flows.fulfillment.renewal_now.switch_order_to_failed"
    )
    mocked_next_step = mocker.MagicMock()

    PreviewRenewalNowOrder()(mock_mpt_client, renewal_now_context_net_new, mocked_next_step)  # act

    message = mocked_switch_to_failed.mock_calls[0].args[2]["message"]
    assert "CODE-3 on new product 65322651CA01A12 (FAILURE)" in message
    mocked_next_step.assert_not_called()


def test_preview_renewal_now_order_step_ignores_an_unselected_code(
    mocker, mock_adobe_client, mock_mpt_client, renewal_now_context, adobe_order_factory
):
    """A code the plan did not select never blocks the order, whatever its result."""
    renewal_now_context.renewal_plan_subscriptions = [plan_entry()]
    mock_adobe_client.get_orders.return_value = []
    mock_adobe_client.create_renewal_order.return_value = adobe_order_factory(
        order_type="PREVIEW_RENEWAL",
        status=AdobeOrderStatus.COMPLETE.value,
        items=[
            {
                "extLineItemNumber": 1,
                "offerId": "65304578CA01A12",
                "quantity": 15,
                "flexDiscounts": [{"code": "HELD-REUSABLE", "result": "FAILURE"}],
            },
        ],
    )
    mocked_next_step = mocker.MagicMock()

    PreviewRenewalNowOrder()(mock_mpt_client, renewal_now_context, mocked_next_step)  # act

    mocked_next_step.assert_called_once_with(mock_mpt_client, renewal_now_context)


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
        recommendation_tracker_id=renewal_now_context.renewal_payload["recommendationTrackerId"],
    )
    mocked_update_order.assert_called_once_with(
        mock_mpt_client,
        renewal_now_context.order_id,
        parameters=renewal_now_context.order["parameters"],
    )
    assert renewal_now_context.adobe_renewal_order == renewal_order
    mocked_next_step.assert_called_once_with(mock_mpt_client, renewal_now_context)


def test_submit_renewal_now_order_step_commits_only_one_successful_flex_discount_code(
    mocker, mock_adobe_client, mock_mpt_client, renewal_now_context, adobe_order_factory
):
    renewal_now_context.renewal_plan_subscriptions = [plan_entry(flex_discount_codes=["CODE-1"])]
    # The preview can report discounts Adobe did not apply (result != SUCCESS) and
    # reusable discounts Adobe auto-applied on its own: only the code the plan
    # explicitly selected, confirmed by the preview, is committed (Adobe rejects
    # more than one code per line with error 2147).
    renewal_now_context.preview_renewal_order = adobe_order_factory(
        order_type="PREVIEW_RENEWAL",
        status=AdobeOrderStatus.COMPLETE.value,
        items=[
            {
                "extLineItemNumber": 1,
                "offerId": "65304578CA01A12",
                "subscriptionId": "renewing-sub-id",
                "quantity": 15,
                "flexDiscounts": [
                    {"code": "FAILED-CODE", "result": "FAILURE"},
                    {"code": "CODE-1", "result": "SUCCESS"},
                    {"code": "CODE-2", "result": "SUCCESS"},
                ],
            },
        ],
    )
    mocker.patch("adobe_vipm.flows.fulfillment.renewal_now.update_order")
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

    committed_line_items = mock_adobe_client.create_renewal_order.mock_calls[0].args[3]
    assert committed_line_items == [
        {
            "extLineItemNumber": 1,
            "offerId": "65304578CA01A12",
            "subscriptionId": "renewing-sub-id",
            "quantity": 15,
            "flexDiscountCodes": ["CODE-1"],
        },
    ]
    mocked_next_step.assert_called_once_with(mock_mpt_client, renewal_now_context)


@pytest.mark.parametrize(
    ("requested_codes", "preview_flex_discounts", "expected_codes"),
    [
        pytest.param(
            ["CODE-1"],
            [{"code": "INHERITED", "result": "SUCCESS"}, {"code": "CODE-1", "result": "SUCCESS"}],
            ["CODE-1"],
            id="explicit-code-takes-precedence-over-auto-applied",
        ),
        pytest.param(
            [],
            [{"code": "INHERITED", "result": "SUCCESS"}],
            None,
            id="auto-applied-reusable-is-not-echoed-back",
        ),
        pytest.param(
            ["CODE-1"],
            [{"code": "CODE-1", "result": "FAILURE"}, {"code": "INHERITED", "result": "SUCCESS"}],
            None,
            id="rejected-explicit-code-is-dropped-without-falling-back",
        ),
        pytest.param(
            ["CODE-1"],
            [],
            None,
            id="explicit-code-missing-from-preview-is-dropped",
        ),
        # Defensive: SetupRenewalPlan already rejects plan entries with more than one
        # code, but should two reach the commit only the first confirmed one is
        # submitted, honouring Adobe's one-code-per-line rule.
        pytest.param(
            ["CODE-1", "CODE-2"],
            [{"code": "CODE-1", "result": "SUCCESS"}, {"code": "CODE-2", "result": "SUCCESS"}],
            ["CODE-1"],
            id="only-one-explicit-code-is-submitted",
        ),
    ],
)
def test_submit_renewal_now_order_step_flex_discount_code_precedence(
    mocker,
    mock_adobe_client,
    mock_mpt_client,
    renewal_now_context,
    adobe_order_factory,
    requested_codes,
    preview_flex_discounts,
    expected_codes,
):
    renewal_now_context.renewal_plan_subscriptions = [
        plan_entry(flex_discount_codes=requested_codes)
    ]
    renewal_now_context.preview_renewal_order = adobe_order_factory(
        order_type="PREVIEW_RENEWAL",
        status=AdobeOrderStatus.COMPLETE.value,
        items=[
            {
                "extLineItemNumber": 1,
                "offerId": "65304578CA01A12",
                "subscriptionId": "renewing-sub-id",
                "quantity": 15,
                "flexDiscounts": preview_flex_discounts,
            },
        ],
    )
    mocker.patch("adobe_vipm.flows.fulfillment.renewal_now.update_order")
    mock_adobe_client.get_orders.return_value = []
    mock_adobe_client.create_renewal_order.return_value = adobe_order_factory(
        order_type="RENEWAL",
        status=AdobeOrderStatus.COMPLETE.value,
        order_id="ADOBE-RENEWAL-001",
    )
    mocked_next_step = mocker.MagicMock()
    step = SubmitRenewalNowOrder()

    step(mock_mpt_client, renewal_now_context, mocked_next_step)  # act

    expected_line_item = {
        "extLineItemNumber": 1,
        "offerId": "65304578CA01A12",
        "subscriptionId": "renewing-sub-id",
        "quantity": 15,
    }
    if expected_codes is not None:
        expected_line_item["flexDiscountCodes"] = expected_codes
    committed_line_items = mock_adobe_client.create_renewal_order.mock_calls[0].args[3]
    assert committed_line_items == [expected_line_item]
    mocked_next_step.assert_called_once_with(mock_mpt_client, renewal_now_context)


def test_submit_renewal_now_order_step_flex_discount_limit_error(
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
        400,
        adobe_api_error_factory(
            code=AdobeErrorCode.FLEX_DISCOUNT_CODE_LIMIT_EXCEEDED.value,
            message="Line Item: 1, Reason: Invalid Flexible Discount",
        ),
    )
    mocked_switch_to_failed = mocker.patch(
        "adobe_vipm.flows.fulfillment.renewal_now.switch_order_to_failed"
    )
    mocked_next_step = mocker.MagicMock()
    step = SubmitRenewalNowOrder()

    step(mock_mpt_client, renewal_now_context, mocked_next_step)  # act

    mocked_switch_to_failed.assert_called_once()
    message = mocked_switch_to_failed.mock_calls[0].args[2]["message"]
    assert "Only one flexible discount code per line item is allowed" in message
    assert renewal_now_context.adobe_renewal_order is None
    mocked_next_step.assert_not_called()


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
    quantity=10,
    remaining_quantity=None,
    line_status=None,
):
    line_item = {
        "extLineItemNumber": 1,
        "offerId": "77777777CA01A12",
        "subscriptionId": subscription_id,
        "quantity": quantity,
    }
    if remaining_quantity is not None:
        line_item["remainingQuantity"] = remaining_quantity
    if line_status:
        line_item["status"] = line_status
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


def return_candidate(  # noqa: WPS211
    returning_order=None,
    returning_line=None,
    return_order=None,
    subscription_id="lapsing-sub-id",
    quantity=None,
):
    return {
        "subscription_id": subscription_id,
        "return_order": return_order,
        "returning_order": returning_order,
        "returning_line": returning_line,
        "quantity": quantity,
    }


def this_order_return_factory(  # noqa: WPS211
    adobe_order_factory,
    reference_order_id="ADOBE-RENEWAL-PREV",
    quantity=10,
    status=AdobeOrderStatus.COMPLETE.value,
    order_id="ADOBE-RETURN-EXISTING",
    line_number=1,
):
    return adobe_order_factory(
        order_type="RETURN",
        status=status,
        order_id=order_id,
        reference_order_id=reference_order_id,
        items=[
            {"extLineItemNumber": line_number, "offerId": "77777777CA01A12", "quantity": quantity}
        ],
    )


def test_resolve_previous_renewal_returns_step_no_candidates(
    mocker, mock_adobe_client, mock_mpt_client, renewal_now_context
):
    renewal_now_context.renewal_plan_subscriptions = [
        # Renewing sub already renewed: handled by the RENEWAL order, not returned.
        plan_entry(snapshot_renewed_quantity=9),
        # Lapsing sub never committed in a previous renewal order: nothing to return.
        plan_entry(subscription_id="lapsing-sub-id", renew=False, renewal_quantity=0),
    ]
    mocked_next_step = mocker.MagicMock()
    step = ResolvePreviousRenewalReturns()

    step(mock_mpt_client, renewal_now_context, mocked_next_step)  # act

    assert renewal_now_context.renewal_return_candidates == []
    mock_adobe_client.get_orders.assert_not_called()
    mock_adobe_client.get_return_orders_by_external_reference.assert_not_called()
    mocked_next_step.assert_called_once_with(mock_mpt_client, renewal_now_context)


@freeze_time("2026-08-10 10:00:00")
def test_resolve_previous_renewal_returns_step_resolves_line(
    mocker, mock_adobe_client, mock_mpt_client, renewal_now_context, adobe_order_factory
):
    renewal_now_context.renewal_plan_subscriptions = [lapsing_renewed_plan_entry()]
    previous_renewal = previous_renewal_order_factory(adobe_order_factory)
    mock_adobe_client.get_orders.return_value = [previous_renewal]
    mock_adobe_client.get_return_orders_by_external_reference.return_value = {}
    mocked_next_step = mocker.MagicMock()
    step = ResolvePreviousRenewalReturns()

    step(mock_mpt_client, renewal_now_context, mocked_next_step)  # act

    mock_adobe_client.get_return_orders_by_external_reference.assert_called_once_with(
        renewal_now_context.authorization_id,
        renewal_now_context.adobe_customer_id,
        renewal_now_context.order_id,
    )
    mock_adobe_client.get_orders.assert_called_once_with(
        renewal_now_context.authorization_id,
        renewal_now_context.adobe_customer_id,
        filters={
            "order-type": ORDER_TYPE_RENEWAL,
            "status": [AdobeOrderStatus.COMPLETE, AdobeOrderStatus.CANCELLED],
        },
    )
    assert renewal_now_context.renewal_return_candidates == [
        return_candidate(
            returning_order=previous_renewal,
            returning_line=previous_renewal["lineItems"][0],
            quantity=10,
        )
    ]
    mocked_next_step.assert_called_once_with(mock_mpt_client, renewal_now_context)


@freeze_time("2026-09-30 10:00:00")
def test_resolve_previous_renewal_returns_step_existing_return_reused(
    mocker, mock_adobe_client, mock_mpt_client, renewal_now_context, adobe_order_factory
):
    # The previous renewal order is outside the return window by now, but the
    # RETURN was already created by a previous attempt of this order (still
    # pending, so renewedQuantity is not lowered yet): reused as-is.
    renewal_now_context.renewal_plan_subscriptions = [lapsing_renewed_plan_entry()]
    mock_adobe_client.get_orders.return_value = [
        previous_renewal_order_factory(adobe_order_factory)
    ]
    existing_return = this_order_return_factory(
        adobe_order_factory, status=AdobeOrderStatus.OPEN.value
    )
    mock_adobe_client.get_return_orders_by_external_reference.return_value = {
        "77777777CA": [existing_return],
    }
    mocked_switch_to_failed = mocker.patch(
        "adobe_vipm.flows.fulfillment.renewal_now.switch_order_to_failed"
    )
    mocked_next_step = mocker.MagicMock()
    step = ResolvePreviousRenewalReturns()

    step(mock_mpt_client, renewal_now_context, mocked_next_step)  # act

    assert renewal_now_context.renewal_return_candidates == [
        return_candidate(return_order=existing_return)
    ]
    mocked_switch_to_failed.assert_not_called()
    mocked_next_step.assert_called_once_with(mock_mpt_client, renewal_now_context)


def test_resolve_previous_renewal_returns_step_previous_order_not_found(
    mocker, mock_adobe_client, mock_mpt_client, renewal_now_context
):
    renewal_now_context.renewal_plan_subscriptions = [lapsing_renewed_plan_entry()]
    mock_adobe_client.get_orders.return_value = []
    mock_adobe_client.get_return_orders_by_external_reference.return_value = {}
    mocked_switch_to_failed = mocker.patch(
        "adobe_vipm.flows.fulfillment.renewal_now.switch_order_to_failed"
    )
    mocked_next_step = mocker.MagicMock()
    step = ResolvePreviousRenewalReturns()

    step(mock_mpt_client, renewal_now_context, mocked_next_step)  # act

    assert renewal_now_context.renewal_return_candidates == []
    mocked_switch_to_failed.assert_called_once()
    assert "lapsing-sub-id" in mocked_switch_to_failed.mock_calls[0].args[2]["message"]
    mocked_next_step.assert_not_called()


@freeze_time("2026-08-10 10:00:00")
def test_resolve_previous_renewal_returns_step_picks_most_recent_order(
    mocker, mock_adobe_client, mock_mpt_client, renewal_now_context, adobe_order_factory
):
    renewal_now_context.renewal_plan_subscriptions = [lapsing_renewed_plan_entry()]
    older_renewal = previous_renewal_order_factory(
        adobe_order_factory,
        order_id="ADOBE-RENEWAL-OLDER",
        external_id="ORD-OLDER",
        creation_date="2026-07-30T10:00:00Z",
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
        creation_date="2026-08-09T10:00:00Z",
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
    mocked_next_step = mocker.MagicMock()
    step = ResolvePreviousRenewalReturns()

    step(mock_mpt_client, renewal_now_context, mocked_next_step)  # act

    # The newest line already holds all 10 renewed seats, so the older one is untouched.
    assert renewal_now_context.renewal_return_candidates == [
        return_candidate(
            returning_order=newer_renewal,
            returning_line=newer_renewal["lineItems"][0],
            quantity=10,
        )
    ]
    mocked_next_step.assert_called_once_with(mock_mpt_client, renewal_now_context)


@freeze_time("2026-08-15 23:00:00")
def test_resolve_previous_renewal_returns_step_last_day_of_return_window(
    mocker, mock_adobe_client, mock_mpt_client, renewal_now_context, adobe_order_factory
):
    # Placed exactly CANCELLATION_WINDOW_DAYS ago: still returnable (inclusive window).
    previous_renewal = previous_renewal_order_factory(
        adobe_order_factory, creation_date="2026-08-01T10:00:00Z"
    )
    renewal_now_context.renewal_plan_subscriptions = [lapsing_renewed_plan_entry()]
    mock_adobe_client.get_orders.return_value = [previous_renewal]
    mock_adobe_client.get_return_orders_by_external_reference.return_value = {}
    mocked_switch_to_failed = mocker.patch(
        "adobe_vipm.flows.fulfillment.renewal_now.switch_order_to_failed"
    )
    mocked_next_step = mocker.MagicMock()
    step = ResolvePreviousRenewalReturns()

    step(mock_mpt_client, renewal_now_context, mocked_next_step)  # act

    assert CANCELLATION_WINDOW_DAYS == 14
    assert len(renewal_now_context.renewal_return_candidates) == 1
    mocked_switch_to_failed.assert_not_called()
    mocked_next_step.assert_called_once_with(mock_mpt_client, renewal_now_context)


@freeze_time("2026-08-16 10:00:00")
def test_resolve_previous_renewal_returns_step_outside_return_window(
    mocker, mock_adobe_client, mock_mpt_client, renewal_now_context, adobe_order_factory
):
    # Placed 15 days ago: Adobe would reject the RETURN, so the order fails
    # before the RENEWAL is committed.
    previous_renewal = previous_renewal_order_factory(
        adobe_order_factory, creation_date="2026-08-01T10:00:00Z"
    )
    renewal_now_context.renewal_plan_subscriptions = [lapsing_renewed_plan_entry()]
    mock_adobe_client.get_orders.return_value = [previous_renewal]
    mock_adobe_client.get_return_orders_by_external_reference.return_value = {}
    mocked_switch_to_failed = mocker.patch(
        "adobe_vipm.flows.fulfillment.renewal_now.switch_order_to_failed"
    )
    mocked_next_step = mocker.MagicMock()
    step = ResolvePreviousRenewalReturns()

    step(mock_mpt_client, renewal_now_context, mocked_next_step)  # act

    assert renewal_now_context.renewal_return_candidates == []
    mocked_switch_to_failed.assert_called_once()
    error = mocked_switch_to_failed.mock_calls[0].args[2]
    assert error["id"] == "VIPM0053"
    assert error["message"] == (
        "The previous renewal order ADOBE-RENEWAL-PREV of subscription lapsing-sub-id was "
        "placed on 2026-08-01, outside the 14-day return window, so it cannot be returned."
    )
    mocked_next_step.assert_not_called()


def run_resolve_step(mocker, context, renewal_orders, returns_by_sku=None):
    """Run ResolvePreviousRenewalReturns against the given Adobe order history."""
    adobe_client = mocker.patch(
        "adobe_vipm.flows.fulfillment.renewal_now.get_adobe_client"
    ).return_value
    adobe_client.get_orders.return_value = renewal_orders
    adobe_client.get_return_orders_by_external_reference.return_value = returns_by_sku or {}
    mocked_switch_to_failed = mocker.patch(
        "adobe_vipm.flows.fulfillment.renewal_now.switch_order_to_failed"
    )
    mocked_next_step = mocker.MagicMock()
    ResolvePreviousRenewalReturns()(mocker.MagicMock(), context, mocked_next_step)
    return mocked_switch_to_failed, mocked_next_step


@freeze_time("2026-08-10 10:00:00")
def test_resolve_previous_renewal_returns_step_returns_every_renewal(
    mocker, renewal_now_context, adobe_order_factory
):
    renewal_now_context.renewal_plan_subscriptions = [
        lapsing_renewed_plan_entry(renewed_quantity=5)
    ]
    first = previous_renewal_order_factory(
        adobe_order_factory,
        order_id="ADOBE-RENEWAL-1",
        external_id="ORD-1",
        creation_date="2026-08-02T10:00:00Z",
        quantity=3,
    )
    second = previous_renewal_order_factory(
        adobe_order_factory,
        order_id="ADOBE-RENEWAL-2",
        external_id="ORD-2",
        creation_date="2026-08-05T10:00:00Z",
        quantity=2,
    )

    switch_to_failed, next_step = run_resolve_step(
        mocker, renewal_now_context, [first, second]
    )  # act

    assert renewal_now_context.renewal_return_candidates == [
        return_candidate(returning_order=second, returning_line=second["lineItems"][0], quantity=2),
        return_candidate(returning_order=first, returning_line=first["lineItems"][0], quantity=3),
    ]
    switch_to_failed.assert_not_called()
    next_step.assert_called_once()


@freeze_time("2026-08-10 10:00:00")
def test_resolve_previous_renewal_returns_step_returns_the_remaining_quantity(
    mocker, renewal_now_context, adobe_order_factory
):
    # 1 of the first RENEWAL's 3 seats was already returned: its line stays 1000
    # with remainingQuantity 2, and renewedQuantity dropped to 4.
    renewal_now_context.renewal_plan_subscriptions = [
        lapsing_renewed_plan_entry(renewed_quantity=4)
    ]
    first = previous_renewal_order_factory(
        adobe_order_factory,
        order_id="ADOBE-RENEWAL-1",
        external_id="ORD-1",
        creation_date="2026-08-02T10:00:00Z",
        quantity=3,
        remaining_quantity=2,
    )
    second = previous_renewal_order_factory(
        adobe_order_factory,
        order_id="ADOBE-RENEWAL-2",
        external_id="ORD-2",
        creation_date="2026-08-05T10:00:00Z",
        quantity=2,
    )

    run_resolve_step(mocker, renewal_now_context, [first, second])  # act

    assert [c["quantity"] for c in renewal_now_context.renewal_return_candidates] == [2, 2]
    assert renewal_now_context.renewal_return_candidates[1]["returning_order"] is first


@freeze_time("2026-08-10 10:00:00")
def test_resolve_previous_renewal_returns_step_skips_a_returned_line(
    mocker, renewal_now_context, adobe_order_factory
):
    renewal_now_context.renewal_plan_subscriptions = [
        lapsing_renewed_plan_entry(renewed_quantity=3)
    ]
    returned = previous_renewal_order_factory(
        adobe_order_factory,
        order_id="ADOBE-RENEWAL-RETURNED",
        external_id="ORD-R",
        creation_date="2026-08-06T10:00:00Z",
        quantity=4,
        line_status=AdobeOrderStatus.CANCELLED.value,
    )
    kept = previous_renewal_order_factory(
        adobe_order_factory,
        order_id="ADOBE-RENEWAL-KEPT",
        external_id="ORD-K",
        creation_date="2026-08-02T10:00:00Z",
        quantity=3,
    )

    run_resolve_step(mocker, renewal_now_context, [returned, kept])  # act

    assert renewal_now_context.renewal_return_candidates == [
        return_candidate(returning_order=kept, returning_line=kept["lineItems"][0], quantity=3),
    ]


@freeze_time("2026-08-20 10:00:00")
def test_resolve_previous_renewal_returns_step_fails_on_an_older_line_outside_the_window(
    mocker, renewal_now_context, adobe_order_factory
):
    renewal_now_context.renewal_plan_subscriptions = [
        lapsing_renewed_plan_entry(renewed_quantity=5)
    ]
    recent = previous_renewal_order_factory(
        adobe_order_factory,
        order_id="ADOBE-RENEWAL-RECENT",
        external_id="ORD-RECENT",
        creation_date="2026-08-18T10:00:00Z",
        quantity=2,
    )
    old = previous_renewal_order_factory(
        adobe_order_factory,
        order_id="ADOBE-RENEWAL-OLD",
        external_id="ORD-OLD",
        creation_date="2026-08-01T10:00:00Z",
        quantity=3,
    )

    switch_to_failed, next_step = run_resolve_step(
        mocker, renewal_now_context, [recent, old]
    )  # act

    error = switch_to_failed.mock_calls[0].args[2]
    assert error["id"] == "VIPM0053"
    assert "ADOBE-RENEWAL-OLD" in error["message"]
    assert "2026-08-01" in error["message"]
    next_step.assert_not_called()


@freeze_time("2026-08-10 10:00:00")
def test_resolve_previous_renewal_returns_step_fails_when_the_seats_do_not_add_up(
    mocker, renewal_now_context, adobe_order_factory
):
    renewal_now_context.renewal_plan_subscriptions = [
        lapsing_renewed_plan_entry(renewed_quantity=5)
    ]
    only = previous_renewal_order_factory(adobe_order_factory, quantity=3)

    switch_to_failed, next_step = run_resolve_step(mocker, renewal_now_context, [only])  # act

    message = switch_to_failed.mock_calls[0].args[2]["message"]
    assert "lapsing-sub-id" in message
    assert "3 of its 5 early-renewed seats" in message
    assert renewal_now_context.renewal_return_candidates == []
    next_step.assert_not_called()


@freeze_time("2026-08-10 10:00:00")
def test_resolve_previous_renewal_returns_step_retry_returns_only_the_other_line(
    mocker, renewal_now_context, adobe_order_factory
):
    # A previous attempt returned the first RENEWAL's 3 seats (completed, so the line
    # is 1008 and renewedQuantity dropped from 5 to 2); only the second remains.
    renewal_now_context.renewal_plan_subscriptions = [
        lapsing_renewed_plan_entry(renewed_quantity=2)
    ]
    first = previous_renewal_order_factory(
        adobe_order_factory,
        order_id="ADOBE-RENEWAL-1",
        external_id="ORD-1",
        creation_date="2026-08-02T10:00:00Z",
        quantity=3,
        line_status=AdobeOrderStatus.CANCELLED.value,
    )
    second = previous_renewal_order_factory(
        adobe_order_factory,
        order_id="ADOBE-RENEWAL-2",
        external_id="ORD-2",
        creation_date="2026-08-05T10:00:00Z",
        quantity=2,
    )
    done = this_order_return_factory(
        adobe_order_factory, reference_order_id="ADOBE-RENEWAL-1", quantity=3
    )

    switch_to_failed, next_step = run_resolve_step(
        mocker, renewal_now_context, [first, second], {"77777777CA": [done]}
    )  # act

    assert renewal_now_context.renewal_return_candidates == [
        return_candidate(return_order=done),
        return_candidate(returning_order=second, returning_line=second["lineItems"][0], quantity=2),
    ]
    switch_to_failed.assert_not_called()
    next_step.assert_called_once()


@freeze_time("2026-08-10 10:00:00")
def test_resolve_previous_renewal_returns_step_leaves_the_anniversary_renewal_alone(
    mocker, renewal_now_context, adobe_order_factory
):
    # Last year's automatic anniversary RENEWAL also lists the subscription, but this
    # term's early renewal already holds every renewed seat, so it is never reached.
    renewal_now_context.renewal_plan_subscriptions = [
        lapsing_renewed_plan_entry(renewed_quantity=4)
    ]
    anniversary = previous_renewal_order_factory(
        adobe_order_factory,
        order_id="ADOBE-RENEWAL-ANNIVERSARY",
        external_id="",
        creation_date="2025-09-01T00:00:00Z",
        quantity=10,
    )
    early = previous_renewal_order_factory(
        adobe_order_factory,
        order_id="ADOBE-RENEWAL-EARLY",
        external_id="ORD-EARLY",
        creation_date="2026-08-05T10:00:00Z",
        quantity=4,
    )

    switch_to_failed, _ = run_resolve_step(mocker, renewal_now_context, [anniversary, early])  # act

    assert renewal_now_context.renewal_return_candidates == [
        return_candidate(returning_order=early, returning_line=early["lineItems"][0], quantity=4),
    ]
    switch_to_failed.assert_not_called()


def test_resolve_previous_renewal_returns_step_zero_renewed_quantity_is_a_plain_lapse(
    mocker, mock_adobe_client, mock_mpt_client, renewal_now_context
):
    # Every early-renewed seat was already returned: Adobe keeps renewedQuantity at 0.
    renewal_now_context.renewal_plan_subscriptions = [
        lapsing_renewed_plan_entry(renewed_quantity=0)
    ]
    mocked_next_step = mocker.MagicMock()

    ResolvePreviousRenewalReturns()(mock_mpt_client, renewal_now_context, mocked_next_step)  # act

    assert renewal_now_context.renewal_return_candidates == []
    mock_adobe_client.get_orders.assert_not_called()
    mocked_next_step.assert_called_once_with(mock_mpt_client, renewal_now_context)


def test_return_previous_renewal_orders_step_no_candidates(
    mocker, mock_adobe_client, mock_mpt_client, renewal_now_context
):
    renewal_now_context.renewal_return_candidates = []
    mocked_next_step = mocker.MagicMock()
    step = ReturnPreviousRenewalOrders()

    step(mock_mpt_client, renewal_now_context, mocked_next_step)  # act

    mock_adobe_client.create_return_order.assert_not_called()
    mocked_next_step.assert_called_once_with(mock_mpt_client, renewal_now_context)


def test_return_previous_renewal_orders_step_creates_return(
    mocker, mock_adobe_client, mock_mpt_client, renewal_now_context, adobe_order_factory
):
    previous_renewal = previous_renewal_order_factory(adobe_order_factory)
    renewal_now_context.renewal_return_candidates = [
        return_candidate(
            returning_order=previous_renewal,
            returning_line=previous_renewal["lineItems"][0],
            quantity=4,
        )
    ]
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

    mock_adobe_client.create_return_order.assert_called_once_with(
        renewal_now_context.authorization_id,
        renewal_now_context.adobe_customer_id,
        previous_renewal,
        previous_renewal["lineItems"][0],
        renewal_now_context.order_id,
        None,
        quantity=4,
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
    existing_return = adobe_order_factory(
        order_type="RETURN",
        status=AdobeOrderStatus.COMPLETE.value,
        order_id="ADOBE-RETURN-EXISTING",
    )
    renewal_now_context.renewal_return_candidates = [return_candidate(return_order=existing_return)]
    mocked_next_step = mocker.MagicMock()
    step = ReturnPreviousRenewalOrders()

    step(mock_mpt_client, renewal_now_context, mocked_next_step)  # act

    mock_adobe_client.create_return_order.assert_not_called()
    mocked_next_step.assert_called_once_with(mock_mpt_client, renewal_now_context)


def test_return_previous_renewal_orders_step_pending_return(
    mocker, mock_adobe_client, mock_mpt_client, renewal_now_context, adobe_order_factory
):
    previous_renewal = previous_renewal_order_factory(adobe_order_factory)
    renewal_now_context.renewal_return_candidates = [
        return_candidate(
            returning_order=previous_renewal,
            returning_line=previous_renewal["lineItems"][0],
        )
    ]
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


def _two_return_candidates(adobe_order_factory, first_return=None, second_return=None):
    older = previous_renewal_order_factory(
        adobe_order_factory, order_id="ADOBE-RENEWAL-OLDER", quantity=3
    )
    newer = previous_renewal_order_factory(
        adobe_order_factory, order_id="ADOBE-RENEWAL-NEWER", quantity=2
    )
    return [
        return_candidate(
            returning_order=newer,
            returning_line=newer["lineItems"][0],
            return_order=first_return,
            quantity=2,
        ),
        return_candidate(
            returning_order=older,
            returning_line=older["lineItems"][0],
            return_order=second_return,
            quantity=3,
        ),
    ]


def test_return_previous_renewal_orders_step_places_the_next_return_only_once_one_completes(
    mocker, mock_adobe_client, mock_mpt_client, renewal_now_context, adobe_order_factory
):
    """Two RETURNs in flight at once can lose a renewedQuantity decrement."""
    renewal_now_context.renewal_return_candidates = _two_return_candidates(adobe_order_factory)
    mock_adobe_client.create_return_order.return_value = adobe_order_factory(
        order_type="RETURN", status=AdobeOrderStatus.OPEN.value, order_id="ADOBE-RETURN-NEWER"
    )
    mocker.patch("adobe_vipm.flows.fulfillment.renewal_now.update_order")
    mocked_next_step = mocker.MagicMock()

    ReturnPreviousRenewalOrders()(mock_mpt_client, renewal_now_context, mocked_next_step)  # act

    mock_adobe_client.create_return_order.assert_called_once()
    assert mock_adobe_client.create_return_order.mock_calls[0].args[2]["orderId"] == (
        "ADOBE-RENEWAL-NEWER"
    )
    mocked_next_step.assert_not_called()


def test_return_previous_renewal_orders_step_waits_on_an_open_return_from_a_previous_attempt(
    mocker, mock_adobe_client, mock_mpt_client, renewal_now_context, adobe_order_factory
):
    open_return = adobe_order_factory(
        order_type="RETURN", status=AdobeOrderStatus.OPEN.value, order_id="ADOBE-RETURN-NEWER"
    )
    renewal_now_context.renewal_return_candidates = _two_return_candidates(
        adobe_order_factory, first_return=open_return
    )
    mocked_next_step = mocker.MagicMock()

    ReturnPreviousRenewalOrders()(mock_mpt_client, renewal_now_context, mocked_next_step)  # act

    mock_adobe_client.create_return_order.assert_not_called()
    mocked_next_step.assert_not_called()


def test_return_previous_renewal_orders_step_places_the_next_return_after_a_completed_one(
    mocker, mock_adobe_client, mock_mpt_client, renewal_now_context, adobe_order_factory
):
    completed_return = adobe_order_factory(
        order_type="RETURN", status=AdobeOrderStatus.COMPLETE.value, order_id="ADOBE-RETURN-NEWER"
    )
    renewal_now_context.renewal_return_candidates = _two_return_candidates(
        adobe_order_factory, first_return=completed_return
    )
    mock_adobe_client.create_return_order.return_value = adobe_order_factory(
        order_type="RETURN", status=AdobeOrderStatus.OPEN.value, order_id="ADOBE-RETURN-OLDER"
    )
    mocker.patch("adobe_vipm.flows.fulfillment.renewal_now.update_order")
    mocked_next_step = mocker.MagicMock()

    ReturnPreviousRenewalOrders()(mock_mpt_client, renewal_now_context, mocked_next_step)  # act

    mock_adobe_client.create_return_order.assert_called_once()
    assert mock_adobe_client.create_return_order.mock_calls[0].args[2]["orderId"] == (
        "ADOBE-RENEWAL-OLDER"
    )
    assert mock_adobe_client.create_return_order.mock_calls[0].kwargs == {"quantity": 3}
    mocked_next_step.assert_not_called()


def test_return_previous_renewal_orders_step_continues_once_every_return_completed(
    mocker, mock_adobe_client, mock_mpt_client, renewal_now_context, adobe_order_factory
):
    renewal_now_context.renewal_return_candidates = _two_return_candidates(
        adobe_order_factory,
        first_return=adobe_order_factory(
            order_type="RETURN", status=AdobeOrderStatus.COMPLETE.value, order_id="R-NEWER"
        ),
        second_return=adobe_order_factory(
            order_type="RETURN", status=AdobeOrderStatus.COMPLETE.value, order_id="R-OLDER"
        ),
    )
    mocked_next_step = mocker.MagicMock()

    ReturnPreviousRenewalOrders()(mock_mpt_client, renewal_now_context, mocked_next_step)  # act

    mock_adobe_client.create_return_order.assert_not_called()
    mocked_next_step.assert_called_once_with(mock_mpt_client, renewal_now_context)


def test_return_previous_renewal_orders_step_return_failed(
    mocker,
    mock_adobe_client,
    mock_mpt_client,
    renewal_now_context,
    adobe_order_factory,
    adobe_api_error_factory,
):
    previous_renewal = previous_renewal_order_factory(adobe_order_factory)
    renewal_now_context.renewal_return_candidates = [
        return_candidate(
            returning_order=previous_renewal,
            returning_line=previous_renewal["lineItems"][0],
        )
    ]
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


@freeze_time("2026-08-28 10:00:00")
def test_record_discount_redemptions_step_renew_now(
    mocker, mock_mpt_client, renewal_now_context, adobe_order_factory
):
    renewal_now_context.renewal_plan_subscriptions = [
        plan_entry(
            subscription_id="9d6f8c818d4ae8807910f889cbab8fNA",
            offer_id="65304520CA01A12",
            renewal_quantity=5,
            flex_discount_codes=["SB7U6WLG8R4N0IGODRZ191ZD"],
        ),
        plan_entry(
            subscription_id="424d33184346eabbdd0dfce7294cf2NA",
            offer_id="65324861CA01A12",
            renewal_quantity=7,
            flex_discount_codes=["HOU3BNCONXV7WOTAQ4032KSM"],
        ),
        plan_entry(
            subscription_id="e4b0e7332a4b82b81f4d897c1b9816NA",
            offer_id="65324819CA01A12",
            renew=False,
            renewal_quantity=0,
        ),
    ]
    # Both requested codes were confirmed on the committed RENEWAL order, so both
    # are recorded.
    renewal_now_context.adobe_renewal_order = adobe_order_factory(
        order_type="RENEWAL",
        status=AdobeOrderStatus.COMPLETE.value,
        order_id="ADOBE-RENEWAL-001",
        items=[
            {
                "extLineItemNumber": 1,
                "offerId": "65304520CA01A12",
                "quantity": 5,
                "flexDiscounts": [{"code": "SB7U6WLG8R4N0IGODRZ191ZD", "result": "SUCCESS"}],
            },
            {
                "extLineItemNumber": 2,
                "offerId": "65324861CA01A12",
                "quantity": 7,
                "flexDiscounts": [{"code": "HOU3BNCONXV7WOTAQ4032KSM", "result": "SUCCESS"}],
            },
        ],
    )
    mocked_create_redemptions = mocker.patch(
        "adobe_vipm.flows.fulfillment.renewal.create_discount_redemptions",
    )
    mocked_next_step = mocker.MagicMock()
    step = RecordDiscountRedemptions()

    step(mock_mpt_client, renewal_now_context, mocked_next_step)  # act

    redeemed_at = dt.datetime(2026, 8, 28, 10, 0, tzinfo=dt.UTC)
    mocked_create_redemptions.assert_called_once_with([
        {
            "code": "SB7U6WLG8R4N0IGODRZ191ZD",
            "customer_id": "customer-id",
            "order_id": renewal_now_context.order_id,
            "redeemed_at": redeemed_at,
        },
        {
            "code": "HOU3BNCONXV7WOTAQ4032KSM",
            "customer_id": "customer-id",
            "order_id": renewal_now_context.order_id,
            "redeemed_at": redeemed_at,
        },
    ])
    mocked_next_step.assert_called_once_with(mock_mpt_client, renewal_now_context)


@freeze_time("2026-08-28 10:00:00")
def test_record_discount_redemptions_step_renew_now_skips_unconfirmed_code(
    mocker, mock_mpt_client, renewal_now_context, adobe_order_factory
):
    renewal_now_context.renewal_plan_subscriptions = [
        plan_entry(
            subscription_id="9d6f8c818d4ae8807910f889cbab8fNA",
            offer_id="65304520CA01A12",
            renewal_quantity=5,
            flex_discount_codes=["CONFIRMED-CODE"],
        ),
        # The preview did not confirm this code, so the renew-now flow dropped it from
        # the committed order (result != SUCCESS): it must not be recorded as redeemed.
        plan_entry(
            subscription_id="424d33184346eabbdd0dfce7294cf2NA",
            offer_id="65324861CA01A12",
            renewal_quantity=7,
            flex_discount_codes=["DROPPED-CODE"],
        ),
    ]
    renewal_now_context.adobe_renewal_order = adobe_order_factory(
        order_type="RENEWAL",
        status=AdobeOrderStatus.COMPLETE.value,
        order_id="ADOBE-RENEWAL-001",
        items=[
            {
                "extLineItemNumber": 1,
                "offerId": "65304520CA01A12",
                "quantity": 5,
                "flexDiscounts": [{"code": "CONFIRMED-CODE", "result": "SUCCESS"}],
            },
            {
                "extLineItemNumber": 2,
                "offerId": "65324861CA01A12",
                "quantity": 7,
                "flexDiscounts": [{"code": "DROPPED-CODE", "result": "FAILURE"}],
            },
        ],
    )
    mocked_create_redemptions = mocker.patch(
        "adobe_vipm.flows.fulfillment.renewal.create_discount_redemptions",
    )
    mocked_next_step = mocker.MagicMock()
    step = RecordDiscountRedemptions()

    step(mock_mpt_client, renewal_now_context, mocked_next_step)  # act

    mocked_create_redemptions.assert_called_once_with([
        {
            "code": "CONFIRMED-CODE",
            "customer_id": "customer-id",
            "order_id": renewal_now_context.order_id,
            "redeemed_at": dt.datetime(2026, 8, 28, 10, 0, tzinfo=dt.UTC),
        },
    ])
    mocked_next_step.assert_called_once_with(mock_mpt_client, renewal_now_context)


def test_record_discount_redemptions_step_renew_now_requires_explicit_success(
    mocker, mock_mpt_client, renewal_now_context, adobe_order_factory
):
    renewal_now_context.renewal_plan_subscriptions = [
        plan_entry(
            subscription_id="9d6f8c818d4ae8807910f889cbab8fNA",
            offer_id="65304520CA01A12",
            renewal_quantity=5,
            flex_discount_codes=["AMBIGUOUS-CODE"],
        ),
    ]
    # A discount object carrying a code but no result is not an explicit confirmation, so
    # it must not be recorded (and must not consume once-per-customer eligibility).
    renewal_now_context.adobe_renewal_order = adobe_order_factory(
        order_type="RENEWAL",
        status=AdobeOrderStatus.COMPLETE.value,
        order_id="ADOBE-RENEWAL-001",
        items=[
            {
                "extLineItemNumber": 1,
                "offerId": "65304520CA01A12",
                "quantity": 5,
                "flexDiscounts": [{"code": "AMBIGUOUS-CODE"}],
            },
        ],
    )
    mocked_create_redemptions = mocker.patch(
        "adobe_vipm.flows.fulfillment.renewal.create_discount_redemptions",
    )
    mocked_next_step = mocker.MagicMock()
    step = RecordDiscountRedemptions()

    step(mock_mpt_client, renewal_now_context, mocked_next_step)  # act

    mocked_create_redemptions.assert_not_called()
    mocked_next_step.assert_called_once_with(mock_mpt_client, renewal_now_context)


def test_record_discount_redemptions_step_renew_now_skips_unconfirmed_net_new_code(
    mocker, mock_mpt_client, renewal_now_context_net_new, adobe_order_factory
):
    renewal_now_context_net_new.renewal_plan_subscriptions = [
        plan_entry(flex_discount_codes=["CONFIRMED-CODE"]),
    ]
    # The net-new item's code (CODE-3, from the net_new_item fixture) was omitted from
    # the committed order (the line carries no flexDiscounts at all), so it must not be
    # recorded as redeemed.
    renewal_now_context_net_new.adobe_renewal_order = adobe_order_factory(
        order_type="RENEWAL",
        status=AdobeOrderStatus.COMPLETE.value,
        order_id="ADOBE-RENEWAL-001",
        items=[
            {
                "extLineItemNumber": 1,
                "offerId": "65304578CA01A12",
                "quantity": 15,
                "flexDiscounts": [{"code": "CONFIRMED-CODE", "result": "SUCCESS"}],
            },
            {
                "extLineItemNumber": 2,
                "offerId": "65322651CA01A12",
                "quantity": 5,
            },
        ],
    )
    mocked_create_redemptions = mocker.patch(
        "adobe_vipm.flows.fulfillment.renewal.create_discount_redemptions",
    )
    mocked_next_step = mocker.MagicMock()
    step = RecordDiscountRedemptions()

    step(mock_mpt_client, renewal_now_context_net_new, mocked_next_step)  # act

    recorded_codes = {
        redemption["code"] for redemption in mocked_create_redemptions.mock_calls[0].args[0]
    }
    assert recorded_codes == {"CONFIRMED-CODE"}
    mocked_next_step.assert_called_once_with(mock_mpt_client, renewal_now_context_net_new)


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
        ValidateNetNewOrderLines,
        Validate3YCRenewalFloor,
        ResolvePreviousRenewalReturns,
        PreviewRenewalNowOrder,
        SubmitRenewalNowOrder,
        ReturnPreviousRenewalOrders,
        ResolveNetNewRenewedSubscriptions,
        CreateNetNewMptSubscriptions,
        NormalizeRenewedSubscriptions,
        DisableLapsingSubscriptions,
        CompleteOrder,
        RecordClientDiscountCodes,
        RecordDiscountRedemptions,
        SetSubscriptionTemplate,
        SyncAgreement,
    ]
    pipeline_args = mocked_pipeline_ctor.mock_calls[0].args
    assert len(pipeline_args) == len(expected_steps)
    actual_steps = [type(step) for step in pipeline_args]
    assert actual_steps == expected_steps
    assert pipeline_args[1].template_name == TEMPLATE_NAME_CHANGE
    assert pipeline_args[9].include_net_new_items is True
    assert pipeline_args[18].template_name == TEMPLATE_NAME_CHANGE
    mocked_context_ctor.assert_called_once_with(order=mocked_order)
    mocked_pipeline_instance.run.assert_called_once_with(mocked_client, mocked_context)


def test_preview_renewal_now_order_step_appends_net_new_line(
    mocker, mock_adobe_client, mock_mpt_client, renewal_now_context_net_new, adobe_order_factory
):
    """A net-new item is appended after the renewing lines with no subscriptionId."""
    renewal_now_context_net_new.renewal_plan_subscriptions = [
        plan_entry(flex_discount_codes=["CODE-1"])
    ]
    mock_adobe_client.get_orders.return_value = []
    mock_adobe_client.create_renewal_order.return_value = adobe_order_factory(
        order_type="PREVIEW_RENEWAL",
        status=AdobeOrderStatus.COMPLETE.value,
        items=[
            {
                "extLineItemNumber": 1,
                "offerId": "65304578CA01A12",
                "quantity": 15,
                "flexDiscounts": [{"code": "CODE-1", "result": "SUCCESS"}],
            },
            {
                "extLineItemNumber": 2,
                "offerId": "65322651CA01A12",
                "quantity": 5,
                "flexDiscounts": [{"code": "CODE-3", "result": "SUCCESS"}],
            },
        ],
    )
    mocked_next_step = mocker.MagicMock()
    step = PreviewRenewalNowOrder()

    step(mock_mpt_client, renewal_now_context_net_new, mocked_next_step)  # act

    line_items = mock_adobe_client.create_renewal_order.mock_calls[0].args[3]
    assert line_items == [
        {
            "extLineItemNumber": 1,
            "offerId": "65304578CA01A12",
            "subscriptionId": "renewing-sub-id",
            "quantity": 15,
            "flexDiscountCodes": ["CODE-1"],
        },
        {
            "extLineItemNumber": 2,
            "offerId": "65322651CA01A12",
            "quantity": 5,
            "flexDiscountCodes": ["CODE-3"],
        },
    ]
    mocked_next_step.assert_called_once_with(mock_mpt_client, renewal_now_context_net_new)


def test_preview_renewal_now_order_step_net_new_only(
    mocker, mock_adobe_client, mock_mpt_client, renewal_now_context_net_new, adobe_order_factory
):
    """A net-new-only plan (no renewing subscriptions) still previews and submits."""
    renewal_now_context_net_new.renewal_plan_subscriptions = []
    mock_adobe_client.get_orders.return_value = []
    mock_adobe_client.create_renewal_order.return_value = adobe_order_factory(
        order_type="PREVIEW_RENEWAL",
        status=AdobeOrderStatus.COMPLETE.value,
        items=[
            {
                "extLineItemNumber": 1,
                "offerId": "65322651CA01A12",
                "quantity": 5,
                "flexDiscounts": [{"code": "CODE-3", "result": "SUCCESS"}],
            },
        ],
    )
    mocked_next_step = mocker.MagicMock()
    step = PreviewRenewalNowOrder()

    step(mock_mpt_client, renewal_now_context_net_new, mocked_next_step)  # act

    line_items = mock_adobe_client.create_renewal_order.mock_calls[0].args[3]
    assert line_items == [
        {
            "extLineItemNumber": 1,
            "offerId": "65322651CA01A12",
            "quantity": 5,
            "flexDiscountCodes": ["CODE-3"],
        },
    ]
    mocked_next_step.assert_called_once_with(mock_mpt_client, renewal_now_context_net_new)


def test_submit_renewal_now_order_step_commits_net_new_line(
    mocker, mock_adobe_client, mock_mpt_client, renewal_now_context_net_new, adobe_order_factory
):
    """The committed order carries the net-new line keyed by extLineItemNumber.

    A net-new line has no subscriptionId, and matching by extLineItemNumber keeps the
    CA->EA offer shift and the confirmed flex code intact.
    """
    renewal_now_context_net_new.renewal_plan_subscriptions = [plan_entry()]
    renewal_now_context_net_new.preview_renewal_order = adobe_order_factory(
        order_type="PREVIEW_RENEWAL",
        status=AdobeOrderStatus.COMPLETE.value,
        items=[
            {
                "extLineItemNumber": 1,
                "offerId": "65304578CA01A12",
                "subscriptionId": "renewing-sub-id",
                "quantity": 15,
            },
            {
                "extLineItemNumber": 2,
                "offerId": "65322651EA01A12",
                "quantity": 5,
                "flexDiscounts": [{"code": "CODE-3", "result": "SUCCESS"}],
            },
        ],
    )
    mocker.patch("adobe_vipm.flows.fulfillment.renewal_now.update_order")
    mock_adobe_client.get_orders.return_value = []
    mock_adobe_client.create_renewal_order.return_value = adobe_order_factory(
        order_type="RENEWAL", status=AdobeOrderStatus.COMPLETE.value, order_id="ADOBE-RENEWAL-001"
    )
    mocked_next_step = mocker.MagicMock()
    step = SubmitRenewalNowOrder()

    step(mock_mpt_client, renewal_now_context_net_new, mocked_next_step)  # act

    committed = mock_adobe_client.create_renewal_order.mock_calls[0].args[3]
    assert committed == [
        {
            "extLineItemNumber": 1,
            "offerId": "65304578CA01A12",
            "quantity": 15,
            "subscriptionId": "renewing-sub-id",
        },
        {
            "extLineItemNumber": 2,
            "offerId": "65322651EA01A12",
            "quantity": 5,
            "flexDiscountCodes": ["CODE-3"],
        },
    ]
    mocked_next_step.assert_called_once_with(mock_mpt_client, renewal_now_context_net_new)


def test_resolve_net_new_renewed_subscriptions_step(
    mocker,
    mock_adobe_client,
    mock_mpt_client,
    renewal_now_context_net_new,
    adobe_order_factory,
    adobe_subscription_factory,
):
    """The committed net-new line is matched by extLineItemNumber and stored by payload offerId."""
    renewal_now_context_net_new.renewal_plan_subscriptions = [plan_entry()]
    renewal_now_context_net_new.adobe_renewal_order = adobe_order_factory(
        order_type="RENEWAL",
        status=AdobeOrderStatus.COMPLETE.value,
        order_id="ADOBE-RENEWAL-001",
        items=[
            {
                "extLineItemNumber": 1,
                "offerId": "65304578CA01A12",
                "subscriptionId": "renewing-sub-id",
                "quantity": 15,
            },
            {
                "extLineItemNumber": 2,
                "offerId": "65322651EA01A12",
                "subscriptionId": "net-new-sub-id",
                "quantity": 5,
            },
        ],
    )
    adobe_sub = adobe_subscription_factory(
        subscription_id="net-new-sub-id", offer_id="65322651EA01A12"
    )
    mock_adobe_client.get_subscription.return_value = adobe_sub
    mocked_next_step = mocker.MagicMock()
    step = ResolveNetNewRenewedSubscriptions()

    step(mock_mpt_client, renewal_now_context_net_new, mocked_next_step)  # act

    mock_adobe_client.get_subscription.assert_called_once_with(
        renewal_now_context_net_new.authorization_id,
        renewal_now_context_net_new.adobe_customer_id,
        "net-new-sub-id",
    )
    assert renewal_now_context_net_new.renewal_net_new_subscriptions == {
        "65322651CA01A12": adobe_sub
    }
    mocked_next_step.assert_called_once_with(mock_mpt_client, renewal_now_context_net_new)


def test_resolve_net_new_renewed_subscriptions_step_no_net_new(
    mocker, mock_adobe_client, mock_mpt_client, renewal_now_context
):
    """No net-new items (or no committed order): the step is a no-op."""
    renewal_now_context.adobe_renewal_order = None
    mocked_next_step = mocker.MagicMock()
    step = ResolveNetNewRenewedSubscriptions()

    step(mock_mpt_client, renewal_now_context, mocked_next_step)  # act

    mock_adobe_client.get_subscription.assert_not_called()
    mocked_next_step.assert_called_once_with(mock_mpt_client, renewal_now_context)


def test_resolve_net_new_renewed_subscriptions_step_adobe_error(
    mocker,
    mock_adobe_client,
    mock_mpt_client,
    renewal_now_context_net_new,
    adobe_order_factory,
    adobe_api_error_factory,
):
    """A get_subscription failure fails the order and stops the pipeline."""
    renewal_now_context_net_new.renewal_plan_subscriptions = [plan_entry()]
    renewal_now_context_net_new.adobe_renewal_order = adobe_order_factory(
        order_type="RENEWAL",
        status=AdobeOrderStatus.COMPLETE.value,
        order_id="ADOBE-RENEWAL-001",
        items=[
            {
                "extLineItemNumber": 2,
                "offerId": "65322651EA01A12",
                "subscriptionId": "net-new-sub-id",
                "quantity": 5,
            },
        ],
    )
    mock_adobe_client.get_subscription.side_effect = AdobeAPIError(
        400, adobe_api_error_factory(code="9999", message="boom")
    )
    mocked_switch_to_failed = mocker.patch(
        "adobe_vipm.flows.fulfillment.renewal_now.switch_order_to_failed"
    )
    mocked_next_step = mocker.MagicMock()
    step = ResolveNetNewRenewedSubscriptions()

    step(mock_mpt_client, renewal_now_context_net_new, mocked_next_step)  # act

    mocked_switch_to_failed.assert_called_once()
    mocked_next_step.assert_not_called()


def test_preview_renewal_now_order_step_net_new_deployment_and_no_flex(
    mocker, mock_adobe_client, mock_mpt_client, renewal_now_context_net_new, adobe_order_factory
):
    """A net-new line with no flex code carries the order's deploymentId when present."""
    renewal_now_context_net_new.renewal_plan_subscriptions = []
    renewal_now_context_net_new.renewal_payload["netNewItems"] = [
        {"offerId": "65322651CA01A12", "quantity": 5},
    ]
    mocker.patch(
        "adobe_vipm.flows.fulfillment.renewal_now.get_deployment_id",
        return_value="deployment-123",
    )
    mock_adobe_client.get_orders.return_value = []
    mock_adobe_client.create_renewal_order.return_value = adobe_order_factory(
        order_type="PREVIEW_RENEWAL",
        status=AdobeOrderStatus.COMPLETE.value,
        items=[{"extLineItemNumber": 1, "offerId": "65322651CA01A12", "quantity": 5}],
    )
    mocked_next_step = mocker.MagicMock()
    step = PreviewRenewalNowOrder()

    step(mock_mpt_client, renewal_now_context_net_new, mocked_next_step)  # act

    line_items = mock_adobe_client.create_renewal_order.mock_calls[0].args[3]
    assert line_items == [
        {
            "extLineItemNumber": 1,
            "offerId": "65322651CA01A12",
            "quantity": 5,
            "deploymentId": "deployment-123",
        },
    ]
    mocked_next_step.assert_called_once_with(mock_mpt_client, renewal_now_context_net_new)


def test_preview_renewal_now_order_step_fails_when_net_new_missing_from_preview(
    mocker, mock_adobe_client, mock_mpt_client, renewal_now_context_net_new, adobe_order_factory
):
    """A preview that omits a requested net-new line fails the order before commit."""
    renewal_now_context_net_new.renewal_plan_subscriptions = [plan_entry()]
    mock_adobe_client.get_orders.return_value = []
    # The preview echoes only the renewing line; the net-new line (2) is absent.
    mock_adobe_client.create_renewal_order.return_value = adobe_order_factory(
        order_type="PREVIEW_RENEWAL",
        status=AdobeOrderStatus.COMPLETE.value,
        items=[
            {
                "extLineItemNumber": 1,
                "offerId": "65304578CA01A12",
                "subscriptionId": "renewing-sub-id",
                "quantity": 15,
            },
        ],
    )
    mocked_switch_to_failed = mocker.patch(
        "adobe_vipm.flows.fulfillment.renewal_now.switch_order_to_failed"
    )
    mocked_next_step = mocker.MagicMock()
    step = PreviewRenewalNowOrder()

    step(mock_mpt_client, renewal_now_context_net_new, mocked_next_step)  # act

    mocked_switch_to_failed.assert_called_once()
    assert "65322651CA01A12" in mocked_switch_to_failed.mock_calls[0].args[2]["message"]
    mocked_next_step.assert_not_called()


def test_resolve_net_new_renewed_subscriptions_step_missing_line(
    mocker,
    mock_adobe_client,
    mock_mpt_client,
    renewal_now_context_net_new,
    adobe_order_factory,
):
    """A committed order that omits a requested net-new line fails the MPT order."""
    renewal_now_context_net_new.renewal_plan_subscriptions = [plan_entry()]
    # Committed order carries only the renewing line; the net-new line (extLineItemNumber 2)
    # is absent.
    renewal_now_context_net_new.adobe_renewal_order = adobe_order_factory(
        order_type="RENEWAL",
        status=AdobeOrderStatus.COMPLETE.value,
        order_id="ADOBE-RENEWAL-001",
        items=[
            {
                "extLineItemNumber": 1,
                "offerId": "65304578CA01A12",
                "subscriptionId": "renewing-sub-id",
                "quantity": 15,
            },
        ],
    )
    mocked_switch_to_failed = mocker.patch(
        "adobe_vipm.flows.fulfillment.renewal_now.switch_order_to_failed"
    )
    mocked_next_step = mocker.MagicMock()
    step = ResolveNetNewRenewedSubscriptions()

    step(mock_mpt_client, renewal_now_context_net_new, mocked_next_step)  # act

    mock_adobe_client.get_subscription.assert_not_called()
    mocked_switch_to_failed.assert_called_once()
    assert "65322651CA01A12" in mocked_switch_to_failed.mock_calls[0].args[2]["message"]
    mocked_next_step.assert_not_called()


def test_resolve_net_new_renewed_subscriptions_step_numbering_stable_on_retry(
    mocker,
    mock_adobe_client,
    mock_mpt_client,
    renewal_now_context_net_new,
    adobe_order_factory,
    adobe_subscription_factory,
):
    """Net-new numbering counts every renew=True entry so retries keep the line stable."""
    renewal_now_context_net_new.renewal_plan_subscriptions = [
        plan_entry(),
        # renew=True but already committed by this order's first attempt (renewedQuantity
        # populated), so _get_renewing_plans now excludes it — but it still occupied a line.
        plan_entry(
            subscription_id="already-renewed-sub-id",
            offer_id="77777777CA01A12",
            renewal_quantity=0,
            snapshot_renewed_quantity=9,
        ),
    ]
    renewal_now_context_net_new.adobe_renewal_order = adobe_order_factory(
        order_type="RENEWAL",
        status=AdobeOrderStatus.COMPLETE.value,
        order_id="ADOBE-RENEWAL-001",
        items=[
            {
                "extLineItemNumber": 1,
                "offerId": "65304578CA01A12",
                "subscriptionId": "renewing-sub-id",
                "quantity": 15,
            },
            {
                "extLineItemNumber": 2,
                "offerId": "77777777CA01A12",
                "subscriptionId": "already-renewed-sub-id",
                "quantity": 9,
            },
            {
                "extLineItemNumber": 3,
                "offerId": "65322651EA01A12",
                "subscriptionId": "net-new-sub-id",
                "quantity": 5,
            },
        ],
    )
    adobe_sub = adobe_subscription_factory(
        subscription_id="net-new-sub-id", offer_id="65322651EA01A12"
    )
    mock_adobe_client.get_subscription.return_value = adobe_sub
    mocked_next_step = mocker.MagicMock()
    step = ResolveNetNewRenewedSubscriptions()

    step(mock_mpt_client, renewal_now_context_net_new, mocked_next_step)  # act

    # The net-new line is number 3 (two renew=True entries + 1), so the net-new
    # subscription is resolved — not the already-renewed line 2.
    mock_adobe_client.get_subscription.assert_called_once_with(
        renewal_now_context_net_new.authorization_id,
        renewal_now_context_net_new.adobe_customer_id,
        "net-new-sub-id",
    )
    assert renewal_now_context_net_new.renewal_net_new_subscriptions == {
        "65322651CA01A12": adobe_sub
    }
    mocked_next_step.assert_called_once_with(mock_mpt_client, renewal_now_context_net_new)


def test_resolve_net_new_renewed_subscriptions_step_missing_subscription_id(
    mocker,
    mock_adobe_client,
    mock_mpt_client,
    renewal_now_context_net_new,
    adobe_order_factory,
):
    """A committed net-new line without a subscriptionId fails the order (no KeyError)."""
    renewal_now_context_net_new.renewal_plan_subscriptions = [plan_entry()]
    renewal_now_context_net_new.adobe_renewal_order = adobe_order_factory(
        order_type="RENEWAL",
        status=AdobeOrderStatus.COMPLETE.value,
        order_id="ADOBE-RENEWAL-001",
        items=[
            {
                "extLineItemNumber": 1,
                "offerId": "65304578CA01A12",
                "subscriptionId": "renewing-sub-id",
                "quantity": 15,
            },
            {"extLineItemNumber": 2, "offerId": "65322651EA01A12", "quantity": 5},
        ],
    )
    mocked_switch_to_failed = mocker.patch(
        "adobe_vipm.flows.fulfillment.renewal_now.switch_order_to_failed"
    )
    mocked_next_step = mocker.MagicMock()
    step = ResolveNetNewRenewedSubscriptions()

    step(mock_mpt_client, renewal_now_context_net_new, mocked_next_step)  # act

    mock_adobe_client.get_subscription.assert_not_called()
    mocked_switch_to_failed.assert_called_once()
    assert "65322651CA01A12" in mocked_switch_to_failed.mock_calls[0].args[2]["message"]
    mocked_next_step.assert_not_called()
