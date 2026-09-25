import pytest

from adobe_vipm.adobe.constants import AdobeOrderStatus
from adobe_vipm.adobe.dataclasses import ReturnableOrderInfo
from adobe_vipm.adobe.errors import AdobeAPIError
from adobe_vipm.flows.constants import ERR_NO_RETURABLE_ERRORS_FOUND
from adobe_vipm.flows.context import Context
from adobe_vipm.flows.fulfillment.downsize_returns import (
    PlanDownsizeReturns,
    SubmitReturnAllocations,
)
from adobe_vipm.flows.utils.returns import DownsizeOutcome, DownsizePlan

SKU = "65304578CA"
SUBSCRIPTION_ID = "6158e1cf0e4414a9b3a06d123969fdNA"


@pytest.fixture
def returnable_order_factory(adobe_order_factory, adobe_items_factory):
    def _returnable(order_id, creation_date, quantity, deployment_id=None):
        order = adobe_order_factory(
            order_type="NEW",
            order_id=order_id,
            items=adobe_items_factory(
                quantity=quantity,
                remaining_quantity=quantity,
                subscription_id=SUBSCRIPTION_ID,
                deployment_id=deployment_id,
            ),
            status=AdobeOrderStatus.COMPLETE.value,
            creation_date=creation_date,
        )
        return ReturnableOrderInfo(order=order, line=order["lineItems"][0], quantity=quantity)

    return _returnable


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
    return mocker.patch("adobe_vipm.flows.fulfillment.downsize_returns.update_order")


@pytest.fixture
def mock_downsize_switch_order_to_failed(mocker):
    return mocker.patch("adobe_vipm.flows.fulfillment.downsize_returns.switch_order_to_failed")


def test_plan_downsize_returns_worked_example(
    mocker, mock_adobe_client, downsize_context, returnable_order_factory
):
    order_a = returnable_order_factory("order_a", "2024-11-01T00:00:00Z", 20)
    order_b = returnable_order_factory("order_b", "2024-11-05T00:00:00Z", 10)
    order_c = returnable_order_factory("order_c", "2024-11-08T00:00:00Z", 10)
    mock_adobe_client.get_returnable_orders_by_subscription_id.return_value = [
        order_a,
        order_b,
        order_c,
    ]
    context = downsize_context(old_quantity=45, quantity=15)
    mocked_next_step = mocker.MagicMock()

    PlanDownsizeReturns()(mocker.MagicMock(), context, mocked_next_step)  # act

    plan = context.downsize_plans[SKU]
    assert (
        plan.outcome,
        [(allocation.order["orderId"], allocation.quantity) for allocation in plan.allocations],
    ) == (DownsizeOutcome.RETURN, [("order_a", 20), ("order_b", 10)])
    mock_adobe_client.get_returnable_orders_by_subscription_id.assert_called_once_with(
        context.authorization_id,
        context.adobe_customer_id,
        SUBSCRIPTION_ID,
        "2025-10-09",
    )
    mocked_next_step.assert_called_once()


def test_plan_downsize_returns_defers_when_pool_does_not_cover(
    mocker, mock_adobe_client, downsize_context, returnable_order_factory
):
    mock_adobe_client.get_returnable_orders_by_subscription_id.return_value = [
        returnable_order_factory("order_a", "2024-11-01T00:00:00Z", 20),
    ]
    context = downsize_context(old_quantity=50, quantity=20)

    PlanDownsizeReturns()(mocker.MagicMock(), context, mocker.MagicMock())  # act

    assert context.downsize_plans[SKU].outcome == DownsizeOutcome.DEFER


def test_plan_downsize_returns_subtracts_previous_returns(
    mocker, mock_adobe_client, downsize_context, returnable_order_factory, adobe_order_factory
):
    mock_adobe_client.get_returnable_orders_by_subscription_id.return_value = [
        returnable_order_factory("order_b", "2024-11-05T00:00:00Z", 10),
    ]
    previous_return = adobe_order_factory(
        order_type="RETURN",
        order_id="return-a",
        reference_order_id="order_a",
        status=AdobeOrderStatus.COMPLETE.value,
    )
    previous_return["lineItems"][0]["quantity"] = 20
    context = downsize_context(old_quantity=45, quantity=15, return_orders=[previous_return])

    PlanDownsizeReturns()(mocker.MagicMock(), context, mocker.MagicMock())  # act

    plan = context.downsize_plans[SKU]
    assert (plan.returned_quantity, [allocation.quantity for allocation in plan.allocations]) == (
        20,
        [10],
    )


def test_plan_downsize_returns_ignores_other_deployments(
    mocker, mock_adobe_client, downsize_context, returnable_order_factory
):
    mock_adobe_client.get_returnable_orders_by_subscription_id.return_value = [
        returnable_order_factory("order_a", "2024-11-01T00:00:00Z", 20, deployment_id="other"),
        returnable_order_factory("order_b", "2024-11-05T00:00:00Z", 10, deployment_id="dep-1"),
    ]
    context = downsize_context(old_quantity=20, quantity=15, deployment_id="dep-1")

    PlanDownsizeReturns()(mocker.MagicMock(), context, mocker.MagicMock())  # act

    plan = context.downsize_plans[SKU]
    assert [
        (allocation.order["orderId"], allocation.quantity) for allocation in plan.allocations
    ] == [("order_b", 5)]


def test_submit_return_allocations_submits_each_allocation(
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
    mocked_next_step = mocker.MagicMock()

    SubmitReturnAllocations()(mocker.MagicMock(), context, mocked_next_step)  # act

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
    mocked_next_step.assert_called_once()


def test_submit_return_allocations_stops_on_pending_return(
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
    mocked_next_step = mocker.MagicMock()

    SubmitReturnAllocations()(mocker.MagicMock(), context, mocked_next_step)  # act

    mock_adobe_client.create_return_order.assert_called_once()
    mocked_next_step.assert_not_called()


def test_submit_return_allocations_waits_for_previous_pending_return(
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
    mocked_next_step = mocker.MagicMock()

    SubmitReturnAllocations()(mocker.MagicMock(), context, mocked_next_step)  # act

    mock_adobe_client.create_return_order.assert_not_called()
    mocked_next_step.assert_not_called()


def test_submit_return_allocations_skips_deferred_lines(
    mocker, mock_adobe_client, downsize_context
):
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
    mocked_next_step = mocker.MagicMock()

    SubmitReturnAllocations()(mocker.MagicMock(), context, mocked_next_step)  # act

    mock_adobe_client.create_return_order.assert_not_called()
    mocked_next_step.assert_called_once()


def test_submit_return_allocations_fails_when_outstanding_not_covered(
    mocker,
    mock_adobe_client,
    downsize_context,
    return_plan_factory,
    adobe_subscription_factory,
    mock_downsize_switch_order_to_failed,
):
    mock_adobe_client.get_subscription.return_value = adobe_subscription_factory(
        current_quantity=25, renewal_quantity=25
    )
    context = downsize_context(old_quantity=45, quantity=15)
    context.downsize_plans = {
        SKU: return_plan_factory([], returned_quantity=20, downsize_quantity=30)
    }
    mocked_client = mocker.MagicMock()
    mocked_next_step = mocker.MagicMock()

    SubmitReturnAllocations()(mocked_client, context, mocked_next_step)  # act

    mock_downsize_switch_order_to_failed.assert_called_once_with(
        mocked_client,
        context.order,
        ERR_NO_RETURABLE_ERRORS_FOUND.to_dict(non_returnable_skus=SKU),
    )
    mocked_next_step.assert_not_called()


def test_submit_return_allocations_adobe_error(
    mocker,
    mock_adobe_client,
    downsize_context,
    returnable_order_factory,
    return_plan_factory,
    adobe_api_error_factory,
):
    mock_send_exception = mocker.patch(
        "adobe_vipm.flows.fulfillment.downsize_returns.send_exception"
    )
    mock_adobe_client.create_return_order.side_effect = AdobeAPIError(
        422, adobe_api_error_factory("RETURN_NOT_SUPPORTED_MOQ_SKU", "MOQ offer")
    )
    context = downsize_context(old_quantity=20, quantity=15)
    context.downsize_plans = {
        SKU: return_plan_factory([returnable_order_factory("order_a", "2024-11-01T00:00:00Z", 5)])
    }

    with pytest.raises(AdobeAPIError):
        SubmitReturnAllocations()(mocker.MagicMock(), context, mocker.MagicMock())

    mock_send_exception.assert_called_once()


def test_submit_return_allocations_reconciles_after_each_return(
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

    SubmitReturnAllocations()(mocker.MagicMock(), context, mocker.MagicMock())  # act

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


def test_submit_return_allocations_keeps_lower_deferred_renewal_quantity(
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
    mocked_next_step = mocker.MagicMock()

    SubmitReturnAllocations()(mocker.MagicMock(), context, mocked_next_step)  # act

    mock_adobe_client.update_subscription.assert_not_called()
    mocked_next_step.assert_called_once()


def test_submit_return_allocations_reconciles_previous_returns_first(
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
    mocked_next_step = mocker.MagicMock()

    SubmitReturnAllocations()(mocker.MagicMock(), context, mocked_next_step)  # act

    mock_adobe_client.update_subscription.assert_called_once()
    mock_adobe_client.create_return_order.assert_not_called()
    mocked_next_step.assert_not_called()


@pytest.mark.parametrize(
    ("error_code", "expected_notifications"),
    [
        ("3120", 0),
        ("1117", 1),
    ],
)
def test_submit_return_allocations_reconcile_error_stops_the_run(
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
        "adobe_vipm.flows.fulfillment.downsize_returns.notify_not_updated_subscriptions"
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
    mocked_next_step = mocker.MagicMock()

    SubmitReturnAllocations()(mocker.MagicMock(), context, mocked_next_step)  # act

    assert (mock_notify.call_count, mocked_next_step.called) == (expected_notifications, False)
