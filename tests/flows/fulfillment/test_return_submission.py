import pytest

from adobe_vipm.adobe.constants import AdobeOrderStatus
from adobe_vipm.adobe.errors import AdobeAPIError, AdobeError
from adobe_vipm.flows.constants import (
    ERR_PARTIAL_RETURN_INCOMPLETE,
    ERR_RETURN_VIOLATES_3YC,
)
from adobe_vipm.flows.context import Context
from adobe_vipm.flows.fulfillment.return_submission import ReturnSubmission
from adobe_vipm.flows.utils.returns import DownsizeOutcome, DownsizePlan

SKU = "65304578CA"
SUBSCRIPTION_ID = "6158e1cf0e4414a9b3a06d123969fdNA"


@pytest.fixture
def downsize_context(order_factory, lines_factory, adobe_customer_factory):
    def _context(old_quantity, quantity, return_orders=None, deployment_id=""):
        order = order_factory(
            lines=lines_factory(old_quantity=old_quantity, quantity=quantity),
            deployment_id=deployment_id,
        )
        adobe_customer = adobe_customer_factory(coterm_date="2025-10-09")
        return Context(
            order=order,
            order_id=order["id"],
            authorization_id=order["authorization"]["id"],
            downsize_lines=order["lines"],
            adobe_customer_id=adobe_customer["customerId"],
            adobe_customer=adobe_customer,
            adobe_return_orders={SKU: return_orders} if return_orders else {},
        )

    return _context


@pytest.fixture
def return_plan_factory():
    def _plan(allocations, returned_quantity=0, downsize_quantity=None):
        allocated = sum(allocation.quantity for allocation in allocations)
        return DownsizePlan(
            sku=SKU,
            subscription_id=SUBSCRIPTION_ID,
            target_quantity=5,
            downsize_quantity=downsize_quantity or allocated + returned_quantity,
            returned_quantity=returned_quantity,
            outcome=DownsizeOutcome.RETURN,
            allocations=tuple(allocations),
        )

    return _plan


@pytest.fixture
def mock_downsize_update_order(mocker):
    return mocker.patch("adobe_vipm.flows.fulfillment.return_submission.update_order")


@pytest.fixture
def mock_downsize_switch_order_to_failed(mocker):
    return mocker.patch("adobe_vipm.flows.fulfillment.return_submission.switch_order_to_failed")


@pytest.fixture(autouse=True)
def remaining_quantity_covers_allocations(mock_adobe_client):
    mock_adobe_client.get_remaining_quantity.return_value = 1000


def _run(mocker, mock_adobe_client, context, client=None):
    return ReturnSubmission(client or mocker.MagicMock(), mock_adobe_client, context).run()


def test_return_submission_submits_each_allocation(
    mocker,
    mock_adobe_client,
    adobe_subscription_factory,
    downsize_context,
    returnable_order_factory,
    return_plan_factory,
    adobe_order_factory,
    mock_downsize_update_order,
):
    allocation_a = returnable_order_factory("order_a", "2024-11-01T00:00:00Z", 20)
    allocation_b = returnable_order_factory("order_b", "2024-11-05T00:00:00Z", 10)
    mock_adobe_client.create_return_order.side_effect = [
        adobe_order_factory(
            order_type="RETURN", order_id="return-a", status=AdobeOrderStatus.COMPLETE.value
        ),
        adobe_order_factory(
            order_type="RETURN", order_id="return-b", status=AdobeOrderStatus.COMPLETE.value
        ),
    ]
    mock_adobe_client.get_subscription.return_value = adobe_subscription_factory(
        current_quantity=15, renewal_quantity=15
    )
    context = downsize_context(old_quantity=45, quantity=15)
    context.downsize_plans = {SKU: return_plan_factory([allocation_a, allocation_b])}

    result = _run(mocker, mock_adobe_client, context)

    assert mock_adobe_client.create_return_order.call_args_list == [
        mocker.call(
            context.authorization_id,
            context.adobe_customer_id,
            allocation.order,
            allocation.line,
            context.order_id,
            "",
            quantity=allocation.quantity,
        )
        for allocation in (allocation_a, allocation_b)
    ]
    assert mock_downsize_update_order.call_count == 2
    assert result is True


def test_return_submission_stops_on_pending_return(
    mocker,
    mock_adobe_client,
    downsize_context,
    returnable_order_factory,
    return_plan_factory,
    adobe_order_factory,
    mock_downsize_update_order,
):
    allocation_a = returnable_order_factory("order_a", "2024-11-01T00:00:00Z", 20)
    allocation_b = returnable_order_factory("order_b", "2024-11-05T00:00:00Z", 10)
    mock_adobe_client.create_return_order.return_value = adobe_order_factory(
        order_type="RETURN", order_id="return-a", status=AdobeOrderStatus.OPEN.value
    )
    context = downsize_context(old_quantity=45, quantity=15)
    context.downsize_plans = {SKU: return_plan_factory([allocation_a, allocation_b])}

    result = _run(mocker, mock_adobe_client, context)

    mock_adobe_client.create_return_order.assert_called_once()
    assert result is False


def test_return_submission_waits_for_previous_pending_return(
    mocker,
    mock_adobe_client,
    downsize_context,
    returnable_order_factory,
    return_plan_factory,
    adobe_order_factory,
):
    pending_return = adobe_order_factory(
        order_type="RETURN",
        order_id="return-a",
        reference_order_id="order_a",
        status=AdobeOrderStatus.OPEN.value,
    )
    context = downsize_context(old_quantity=45, quantity=15, return_orders=[pending_return])
    context.downsize_plans = {
        SKU: return_plan_factory(
            [returnable_order_factory("order_b", "2024-11-05T00:00:00Z", 10)],
            returned_quantity=20,
        )
    }

    result = _run(mocker, mock_adobe_client, context)

    mock_adobe_client.create_return_order.assert_not_called()
    assert result is False


def test_return_submission_skips_deferred_lines(mocker, mock_adobe_client, downsize_context):
    context = downsize_context(old_quantity=50, quantity=20)
    context.downsize_plans = {
        SKU: DownsizePlan(
            sku=SKU,
            subscription_id=SUBSCRIPTION_ID,
            target_quantity=20,
            downsize_quantity=30,
            returned_quantity=0,
            outcome=DownsizeOutcome.DEFER,
        )
    }

    result = _run(mocker, mock_adobe_client, context)

    mock_adobe_client.create_return_order.assert_not_called()
    assert result is True


def test_return_submission_reconciles_after_each_return(
    mocker,
    mock_adobe_client,
    downsize_context,
    returnable_order_factory,
    return_plan_factory,
    adobe_order_factory,
    adobe_subscription_factory,
    mock_downsize_update_order,
):
    mock_adobe_client.create_return_order.side_effect = [
        adobe_order_factory(
            order_type="RETURN", order_id="return-a", status=AdobeOrderStatus.COMPLETE.value
        ),
        adobe_order_factory(
            order_type="RETURN", order_id="return-b", status=AdobeOrderStatus.COMPLETE.value
        ),
    ]
    mock_adobe_client.get_subscription.side_effect = [
        adobe_subscription_factory(current_quantity=25, renewal_quantity=45),
        adobe_subscription_factory(current_quantity=15, renewal_quantity=25),
    ]
    context = downsize_context(old_quantity=45, quantity=15)
    context.downsize_plans = {
        SKU: return_plan_factory([
            returnable_order_factory("order_a", "2024-11-01T00:00:00Z", 20),
            returnable_order_factory("order_b", "2024-11-05T00:00:00Z", 10),
        ])
    }

    _run(mocker, mock_adobe_client, context)  # act

    assert mock_adobe_client.update_subscription.call_args_list == [
        mocker.call(
            context.authorization_id,
            context.adobe_customer_id,
            SUBSCRIPTION_ID,
            auto_renewal=True,
            quantity=quantity,
        )
        for quantity in (25, 15)
    ]


def test_return_submission_keeps_lower_deferred_renewal_quantity(
    mocker,
    mock_adobe_client,
    downsize_context,
    returnable_order_factory,
    return_plan_factory,
    adobe_order_factory,
    adobe_subscription_factory,
    mock_downsize_update_order,
):
    mock_adobe_client.create_return_order.return_value = adobe_order_factory(
        order_type="RETURN", order_id="return-a", status=AdobeOrderStatus.COMPLETE.value
    )
    mock_adobe_client.get_subscription.return_value = adobe_subscription_factory(
        current_quantity=15, renewal_quantity=10
    )
    context = downsize_context(old_quantity=10, quantity=5)
    context.downsize_plans = {
        SKU: return_plan_factory([returnable_order_factory("order_a", "2024-11-01T00:00:00Z", 5)])
    }

    result = _run(mocker, mock_adobe_client, context)

    mock_adobe_client.update_subscription.assert_not_called()
    assert result is True


def test_return_submission_reconciles_previous_returns_first(
    mocker,
    mock_adobe_client,
    downsize_context,
    returnable_order_factory,
    return_plan_factory,
    adobe_order_factory,
    adobe_subscription_factory,
    mock_downsize_update_order,
):
    completed_return = adobe_order_factory(
        order_type="RETURN",
        order_id="return-a",
        reference_order_id="order_a",
        status=AdobeOrderStatus.COMPLETE.value,
    )
    mock_adobe_client.get_subscription.return_value = adobe_subscription_factory(
        current_quantity=25, renewal_quantity=45
    )
    mock_adobe_client.update_subscription.side_effect = AdobeAPIError(
        400, {"code": "3120", "message": "Invalid renewal state"}
    )
    context = downsize_context(old_quantity=45, quantity=15, return_orders=[completed_return])
    context.downsize_plans = {
        SKU: return_plan_factory(
            [returnable_order_factory("order_b", "2024-11-05T00:00:00Z", 10)],
            returned_quantity=20,
        )
    }

    result = _run(mocker, mock_adobe_client, context)

    mock_adobe_client.update_subscription.assert_called_once()
    mock_adobe_client.create_return_order.assert_not_called()
    assert result is False


@pytest.mark.parametrize(
    ("error_code", "expected_notifications"),
    [
        ("3120", 0),
        ("1117", 1),
    ],
)
def test_return_submission_reconcile_error_stops_the_run(
    mocker,
    mock_adobe_client,
    downsize_context,
    returnable_order_factory,
    return_plan_factory,
    adobe_order_factory,
    adobe_subscription_factory,
    mock_downsize_update_order,
    error_code,
    expected_notifications,
):
    mock_notify = mocker.patch(
        "adobe_vipm.flows.fulfillment.return_submission.notify_not_updated_subscriptions"
    )
    mock_adobe_client.create_return_order.return_value = adobe_order_factory(
        order_type="RETURN", order_id="return-a", status=AdobeOrderStatus.COMPLETE.value
    )
    mock_adobe_client.get_subscription.return_value = adobe_subscription_factory(
        current_quantity=15, renewal_quantity=20
    )
    mock_adobe_client.update_subscription.side_effect = AdobeAPIError(
        400, {"code": error_code, "message": "An error"}
    )
    context = downsize_context(old_quantity=20, quantity=15)
    context.downsize_plans = {
        SKU: return_plan_factory([returnable_order_factory("order_a", "2024-11-01T00:00:00Z", 5)])
    }

    result = _run(mocker, mock_adobe_client, context)

    assert (mock_notify.call_count, result) == (expected_notifications, False)


@pytest.fixture
def mock_submission_sync(mocker):
    return mocker.patch(
        "adobe_vipm.flows.fulfillment.return_submission.sync_agreements_by_agreement_ids"
    )


@pytest.fixture
def mock_submission_send_exception(mocker):
    return mocker.patch("adobe_vipm.flows.fulfillment.return_submission.send_exception")


@pytest.fixture
def single_allocation_context(downsize_context, returnable_order_factory, return_plan_factory):
    context = downsize_context(old_quantity=20, quantity=15)
    context.downsize_plans = {
        SKU: return_plan_factory([returnable_order_factory("order_a", "2024-11-01T00:00:00Z", 5)])
    }
    return context


def _adobe_error(code, status_code=422):
    return AdobeAPIError(status_code, {"code": code, "message": f"{code} message"})


def test_return_submission_fails_with_report_when_outstanding_not_covered(
    mocker,
    mock_adobe_client,
    downsize_context,
    return_plan_factory,
    adobe_order_factory,
    adobe_subscription_factory,
    mock_downsize_switch_order_to_failed,
    mock_submission_sync,
    mock_submission_send_exception,
):
    previous_return = adobe_order_factory(
        order_type="RETURN",
        order_id="return-a",
        reference_order_id="order_a",
        status=AdobeOrderStatus.COMPLETE.value,
    )
    previous_return["lineItems"][0]["quantity"] = 20
    mock_adobe_client.get_subscription.return_value = adobe_subscription_factory(
        current_quantity=25, renewal_quantity=25
    )
    context = downsize_context(old_quantity=45, quantity=15, return_orders=[previous_return])
    context.downsize_plans = {
        SKU: return_plan_factory([], returned_quantity=20, downsize_quantity=30)
    }
    mocked_client = mocker.MagicMock()

    result = _run(mocker, mock_adobe_client, context, mocked_client)

    assert (result, mock_downsize_switch_order_to_failed.call_args) == (
        False,
        mocker.call(
            mocked_client,
            context.order,
            ERR_PARTIAL_RETURN_INCOMPLETE.to_dict(
                details=f"{SKU}: PARTIAL 20/30 (return-a)",
                error=f"the returnable orders no longer cover {SKU}",
            ),
        ),
    )
    mock_submission_sync.assert_called_once_with(
        mocked_client, mock_adobe_client, [context.agreement_id], dry_run=False, sync_prices=False
    )
    mock_submission_send_exception.assert_called_once()


def test_return_submission_defers_line_rejected_before_any_credit(
    mocker, mock_adobe_client, single_allocation_context
):
    mock_adobe_client.create_return_order.side_effect = _adobe_error("RETURN_NOT_SUPPORTED_MOQ_SKU")
    context = single_allocation_context

    result = _run(mocker, mock_adobe_client, context)

    assert (
        result,
        context.downsize_plans[SKU].outcome,
        context.downsize_plans[SKU].allocations,
    ) == (
        True,
        DownsizeOutcome.DEFER,
        (),
    )


@pytest.mark.parametrize(
    "error",
    [
        AdobeAPIError(500, {"code": "1124", "message": "Internal server error"}),
        AdobeError("connection reset"),
    ],
)
def test_return_submission_transient_error_is_retried(
    mocker,
    mock_adobe_client,
    single_allocation_context,
    mock_submission_send_exception,
    error,
):
    mock_adobe_client.create_return_order.side_effect = error

    with pytest.raises(AdobeError):
        _run(mocker, mock_adobe_client, single_allocation_context)

    mock_submission_send_exception.assert_called_once()


def test_return_submission_replans_once_on_quantity_drop(
    mocker,
    mock_adobe_client,
    returnable_order_factory,
    single_allocation_context,
    adobe_order_factory,
    adobe_subscription_factory,
    mock_downsize_update_order,
):
    mock_adobe_client.get_returnable_orders_by_subscription_id.return_value = [
        returnable_order_factory("order_c", "2024-11-08T00:00:00Z", 10),
    ]
    mock_adobe_client.create_return_order.side_effect = [
        _adobe_error("RETURN_QTY_EXCEEDS_REMAINING"),
        adobe_order_factory(
            order_type="RETURN", order_id="return-c", status=AdobeOrderStatus.COMPLETE.value
        ),
    ]
    mock_adobe_client.get_subscription.return_value = adobe_subscription_factory(
        current_quantity=15, renewal_quantity=15
    )

    result = _run(mocker, mock_adobe_client, single_allocation_context)

    assert (
        result,
        [call.args[2]["orderId"] for call in mock_adobe_client.create_return_order.call_args_list],
    ) == (True, ["order_a", "order_c"])


def test_return_submission_fails_when_replan_cannot_cover_credited_line(
    mocker,
    mock_adobe_client,
    downsize_context,
    returnable_order_factory,
    return_plan_factory,
    adobe_order_factory,
    adobe_subscription_factory,
    mock_downsize_update_order,
    mock_downsize_switch_order_to_failed,
    mock_submission_sync,
    mock_submission_send_exception,
):
    mock_adobe_client.get_returnable_orders_by_subscription_id.return_value = []
    mock_adobe_client.create_return_order.side_effect = [
        adobe_order_factory(
            order_type="RETURN", order_id="return-a", status=AdobeOrderStatus.COMPLETE.value
        ),
        _adobe_error("RETURN_QTY_EXCEEDS_REMAINING"),
    ]
    mock_adobe_client.get_subscription.return_value = adobe_subscription_factory(
        current_quantity=25, renewal_quantity=25
    )
    context = downsize_context(old_quantity=45, quantity=15)
    context.downsize_plans = {
        SKU: return_plan_factory([
            returnable_order_factory("order_a", "2024-11-01T00:00:00Z", 20),
            returnable_order_factory("order_b", "2024-11-05T00:00:00Z", 10),
        ])
    }

    result = _run(mocker, mock_adobe_client, context)

    failure = mock_downsize_switch_order_to_failed.call_args.args[2]
    assert (result, failure["id"], f"{SKU}: PARTIAL 20/30 (return-a)" in failure["message"]) == (
        False,
        ERR_PARTIAL_RETURN_INCOMPLETE.id,
        True,
    )
    mock_submission_sync.assert_called_once()


def test_return_submission_3yc_rejection_without_credit_fails(
    mocker,
    mock_adobe_client,
    single_allocation_context,
    mock_downsize_switch_order_to_failed,
    mock_submission_sync,
):
    mock_adobe_client.create_return_order.side_effect = _adobe_error("RETURN_VIOLATES_3YC_MCQ")

    result = _run(mocker, mock_adobe_client, single_allocation_context)

    assert (result, mock_downsize_switch_order_to_failed.call_args.args[2]["id"]) == (
        False,
        ERR_RETURN_VIOLATES_3YC.id,
    )
    mock_submission_sync.assert_not_called()


def test_return_submission_second_quantity_drop_without_credit_defers(
    mocker, mock_adobe_client, returnable_order_factory, single_allocation_context
):
    mock_adobe_client.get_returnable_orders_by_subscription_id.return_value = [
        returnable_order_factory("order_c", "2024-11-08T00:00:00Z", 10),
    ]
    mock_adobe_client.create_return_order.side_effect = _adobe_error("RETURN_QTY_EXCEEDS_REMAINING")

    result = _run(mocker, mock_adobe_client, single_allocation_context)

    assert (
        result,
        mock_adobe_client.create_return_order.call_count,
        single_allocation_context.downsize_plans[SKU].outcome,
    ) == (True, 2, DownsizeOutcome.DEFER)


def test_return_submission_replans_before_submitting_when_pool_shrank(
    mocker, mock_adobe_client, returnable_order_factory, single_allocation_context
):
    mock_adobe_client.get_remaining_quantity.return_value = 2
    mock_adobe_client.get_returnable_orders_by_subscription_id.return_value = [
        returnable_order_factory("order_a", "2024-11-01T00:00:00Z", 2),
    ]

    result = _run(mocker, mock_adobe_client, single_allocation_context)

    assert (result, single_allocation_context.downsize_plans[SKU].outcome) == (
        True,
        DownsizeOutcome.DEFER,
    )
    mock_adobe_client.create_return_order.assert_not_called()


def test_return_submission_failed_return_order_is_replanned(
    mocker,
    mock_adobe_client,
    single_allocation_context,
    adobe_order_factory,
    mock_downsize_update_order,
):
    mock_adobe_client.get_returnable_orders_by_subscription_id.return_value = []
    mock_adobe_client.create_return_order.return_value = adobe_order_factory(
        order_type="RETURN", order_id="return-a", status=AdobeOrderStatus.FAILED.value
    )

    result = _run(mocker, mock_adobe_client, single_allocation_context)

    assert (result, single_allocation_context.downsize_plans[SKU].outcome) == (
        True,
        DownsizeOutcome.DEFER,
    )


def test_return_submission_submits_multi_source_lines_first(
    mocker,
    mock_adobe_client,
    downsize_context,
    returnable_order_factory,
    adobe_order_factory,
    adobe_subscription_factory,
    mock_downsize_update_order,
):
    single = returnable_order_factory("single", "2024-11-01T00:00:00Z", 5)
    multi_a = returnable_order_factory("multi_a", "2024-11-02T00:00:00Z", 5)
    multi_b = returnable_order_factory("multi_b", "2024-11-03T00:00:00Z", 5)
    mock_adobe_client.create_return_order.return_value = adobe_order_factory(
        order_type="RETURN", order_id="return", status=AdobeOrderStatus.COMPLETE.value
    )
    mock_adobe_client.get_subscription.return_value = adobe_subscription_factory()
    context = downsize_context(old_quantity=20, quantity=15)
    context.downsize_plans = {
        "SKU-SINGLE": DownsizePlan(
            "SKU-SINGLE", "SUB-1", 0, 5, 0, DownsizeOutcome.RETURN, (single,)
        ),
        "SKU-MULTI": DownsizePlan(
            "SKU-MULTI", "SUB-2", 0, 10, 0, DownsizeOutcome.RETURN, (multi_a, multi_b)
        ),
    }

    _run(mocker, mock_adobe_client, context)  # act

    assert [
        call.args[2]["orderId"] for call in mock_adobe_client.create_return_order.call_args_list
    ] == ["multi_a", "multi_b", "single"]


def test_return_submission_failure_survives_agreement_sync_error(
    mocker,
    mock_adobe_client,
    downsize_context,
    return_plan_factory,
    adobe_order_factory,
    adobe_subscription_factory,
    mock_downsize_switch_order_to_failed,
    mock_submission_sync,
    mock_submission_send_exception,
):
    previous_return = adobe_order_factory(
        order_type="RETURN",
        order_id="return-a",
        reference_order_id="order_a",
        status=AdobeOrderStatus.COMPLETE.value,
    )
    mock_adobe_client.get_subscription.return_value = adobe_subscription_factory(
        current_quantity=25, renewal_quantity=25
    )
    mock_submission_sync.side_effect = RuntimeError("sync failed")
    context = downsize_context(old_quantity=45, quantity=15, return_orders=[previous_return])
    context.downsize_plans = {
        SKU: return_plan_factory([], returned_quantity=20, downsize_quantity=30),
    }

    result = _run(mocker, mock_adobe_client, context)

    assert (result, mock_downsize_switch_order_to_failed.called) == (False, True)
