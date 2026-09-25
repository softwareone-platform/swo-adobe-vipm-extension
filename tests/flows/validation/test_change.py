import pytest

from adobe_vipm.adobe.dataclasses import ReturnableOrderInfo
from adobe_vipm.flows.context import Context
from adobe_vipm.flows.fulfillment.shared import (
    SelectFlexDiscounts,
    SetOrUpdateCotermDate,
    ValidateRenewalWindow,
)
from adobe_vipm.flows.helpers import SetupContext, Validate3YCCommitment, ValidateSkuAvailability
from adobe_vipm.flows.utils.returns import DownsizeOutcome
from adobe_vipm.flows.validation.change import (
    GetPreviewOrder,
    ValidateDownsizes,
    validate_change_order,
)
from adobe_vipm.flows.validation.shared import (
    ValidateDuplicateLines,
    ValidateNoEarlyRenewal,
    ValidateNoStagedRenewal,
)


@pytest.fixture
def draft_downsize_context(order_factory, lines_factory, adobe_customer_factory):
    def _context(old_quantity, quantity):
        order = order_factory(lines=lines_factory(quantity=quantity, old_quantity=old_quantity))
        adobe_customer = adobe_customer_factory(coterm_date="2025-10-09")
        return Context(
            order=order,
            authorization_id=order["authorization"]["id"],
            downsize_lines=order["lines"],
            adobe_customer_id=adobe_customer["customerId"],
            adobe_customer=adobe_customer,
        )

    return _context


@pytest.fixture
def returnable_orders_factory(adobe_order_factory, adobe_items_factory):
    def _returnable(quantities):
        returnable_orders = []
        for index, quantity in enumerate(quantities):
            order = adobe_order_factory(
                order_type="NEW",
                order_id=f"order-{index}",
                items=adobe_items_factory(
                    subscription_id="6158e1cf0e4414a9b3a06d123969fdNA",
                    quantity=quantity,
                    remaining_quantity=quantity,
                ),
                creation_date=f"2024-11-0{index + 1}T00:00:00Z",
            )
            returnable_orders.append(ReturnableOrderInfo(order, order["lineItems"][0], quantity))
        return returnable_orders

    return _returnable


@pytest.mark.parametrize(
    ("old_quantity", "quantity", "pool_quantities", "expected_outcome"),
    [
        (14, 7, [1, 2, 4], DownsizeOutcome.RETURN),
        (14, 9, [1, 2, 4], DownsizeOutcome.RETURN),
        (14, 7, [14], DownsizeOutcome.RETURN),
        (14, 2, [1, 2, 4], DownsizeOutcome.DEFER),
        (14, 7, [], DownsizeOutcome.DEFER),
    ],
)
def test_validate_downsizes_step_never_blocks_the_draft(
    mocker,
    mock_adobe_client,
    draft_downsize_context,
    returnable_orders_factory,
    old_quantity,
    quantity,
    pool_quantities,
    expected_outcome,
):
    mock_adobe_client.get_returnable_orders_by_subscription_id.return_value = (
        returnable_orders_factory(pool_quantities)
    )
    context = draft_downsize_context(old_quantity, quantity)
    mocked_client = mocker.MagicMock()
    mocked_next_step = mocker.MagicMock()

    ValidateDownsizes()(mocked_client, context, mocked_next_step)  # act

    assert (
        context.validation_succeeded,
        context.order["error"],
        context.downsize_plans["65304578CA"].outcome,
    ) == (True, None, expected_outcome)
    mock_adobe_client.get_returnable_orders_by_subscription_id.assert_called_once_with(
        context.authorization_id,
        context.adobe_customer_id,
        "6158e1cf0e4414a9b3a06d123969fdNA",
        "2025-10-09",
    )
    mocked_next_step.assert_called_once_with(mocked_client, context)


def test_validate_change_order(mocker):
    mocked_pipeline_instance = mocker.MagicMock()
    mocked_pipeline_ctor = mocker.patch(
        "adobe_vipm.flows.validation.change.Pipeline", return_value=mocked_pipeline_instance
    )
    mocked_context = mocker.MagicMock()
    mocked_context_ctor = mocker.patch(
        "adobe_vipm.flows.validation.change.Context", return_value=mocked_context
    )
    mocked_client = mocker.MagicMock()
    mocked_order = mocker.MagicMock()

    validate_change_order(mocked_client, mocked_order)  # act

    assert len(mocked_pipeline_ctor.mock_calls[0].args) == 12
    expected_steps = [
        SetupContext,
        ValidateDuplicateLines,
        SetOrUpdateCotermDate,
        ValidateRenewalWindow,
        ValidateNoEarlyRenewal,
        ValidateNoStagedRenewal,
        ValidateSkuAvailability,
        ValidateDownsizes,
        Validate3YCCommitment,
        SelectFlexDiscounts,
        GetPreviewOrder,
    ]
    actual_steps = [type(step) for step in mocked_pipeline_ctor.mock_calls[0].args[:11]]
    assert actual_steps == expected_steps
    mocked_context_ctor.assert_called_once_with(order=mocked_order)
    mocked_pipeline_instance.run.assert_called_once_with(mocked_client, mocked_context)
