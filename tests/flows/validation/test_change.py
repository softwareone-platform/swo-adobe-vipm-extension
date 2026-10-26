from types import SimpleNamespace

import pytest

from adobe_vipm.adobe.dataclasses import ReturnableOrderInfo
from adobe_vipm.flows.constants import ITEM_EXTERNAL_ID_EARLY_RENEWAL_NO_CHANGE
from adobe_vipm.flows.context import Context
from adobe_vipm.flows.fulfillment.shared import (
    CheckManualRenewalSubscriptions,
    PreviewRenewalOrders,
    SelectFlexDiscounts,
    SetOrUpdateCotermDate,
    ValidateRenewalWindow,
)
from adobe_vipm.flows.helpers import (
    SetupContext,
    UpdatePrices,
    Validate3YCCommitment,
    ValidateSkuAvailability,
)
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

    expected_steps = [
        SetupContext,
        ValidateDuplicateLines,
        SetOrUpdateCotermDate,
        ValidateRenewalWindow,
        ValidateNoEarlyRenewal,
        ValidateNoStagedRenewal,
        ValidateSkuAvailability,
        ValidateDownsizes,
        CheckManualRenewalSubscriptions,
        Validate3YCCommitment,
        SelectFlexDiscounts,
        GetPreviewOrder,
        PreviewRenewalOrders,
        UpdatePrices,
    ]
    pipeline_args = mocked_pipeline_ctor.mock_calls[0].args
    actual_steps = [type(step) for step in pipeline_args]
    assert actual_steps == expected_steps
    assert pipeline_args[8].is_validation is True
    assert pipeline_args[12].select_flex_discounts is True
    assert pipeline_args[12].is_validation is True
    mocked_context_ctor.assert_called_once_with(order=mocked_order)
    mocked_pipeline_instance.run.assert_called_once_with(mocked_client, mocked_context)


@pytest.fixture
def change_validation(mocker, agreement, mock_get_sku_adobe_mapping_model):
    mocker.patch("adobe_vipm.flows.helpers.get_agreement", return_value=agreement)
    mocker.patch("adobe_vipm.flows.helpers.get_licensee", return_value=agreement["licensee"])
    mocker.patch("adobe_vipm.flows.helpers.get_adobe_client")
    mocker.patch("adobe_vipm.flows.validation.change.get_adobe_client")
    mocker.patch("adobe_vipm.flows.helpers.get_3yc_commitment", return_value={})
    mocked_get_adobe_product = mocker.patch(
        "adobe_vipm.flows.helpers.get_adobe_product_by_marketplace_sku",
        side_effect=mock_get_sku_adobe_mapping_model.from_short_id,
    )
    mocked_get_prices = mocker.patch(
        "adobe_vipm.flows.helpers.get_skus_with_available_prices",
        side_effect=lambda product_id, currency, skus: dict.fromkeys(skus, 100.0),
    )
    reached_lines = {}

    def passthrough(step_name):
        def _step(client, context, next_step):
            reached_lines[step_name] = context.new_lines + context.upsize_lines
            next_step(client, context)

        mocker.patch(f"adobe_vipm.flows.validation.change.{step_name}", return_value=_step)

    for step_name in (
        "ValidateDuplicateLines",
        "SetOrUpdateCotermDate",
        "ValidateRenewalWindow",
        "ValidateNoEarlyRenewal",
        "ValidateNoStagedRenewal",
        "CheckManualRenewalSubscriptions",
        "Validate3YCCommitment",
        "SelectFlexDiscounts",
        "GetPreviewOrder",
        "PreviewRenewalOrders",
        "UpdatePrices",
    ):
        passthrough(step_name)

    def _run(order):
        has_errors, validated_order = validate_change_order(mocker.MagicMock(), order)
        return has_errors, validated_order, reached_lines

    return SimpleNamespace(
        run=_run, get_adobe_product=mocked_get_adobe_product, get_prices=mocked_get_prices
    )


def test_validate_change_order_accepts_a_no_change_placeholder_only_draft(
    change_validation, order_factory, lines_factory
):
    order = order_factory(
        lines=lines_factory(
            external_vendor_id=ITEM_EXTERNAL_ID_EARLY_RENEWAL_NO_CHANGE,
            old_quantity=0,
            quantity=1,
        )
    )

    has_errors, validated_order, reached_lines = change_validation.run(order)  # act

    assert (has_errors, validated_order["error"]) == (False, None)
    assert reached_lines["SelectFlexDiscounts"] == []
    assert reached_lines["GetPreviewOrder"] == []
    assert reached_lines.keys() >= {"PreviewRenewalOrders", "UpdatePrices"}


def test_validate_change_order_does_not_resolve_the_no_change_placeholder(
    change_validation, order_factory, lines_factory
):
    order = order_factory(
        lines=lines_factory(
            external_vendor_id=ITEM_EXTERNAL_ID_EARLY_RENEWAL_NO_CHANGE,
            old_quantity=0,
            quantity=1,
        )
    )

    change_validation.run(order)  # act

    change_validation.get_adobe_product.assert_not_called()
    change_validation.get_prices.assert_called_once_with(
        order["agreement"]["product"]["id"], "USD", []
    )


def test_validate_change_order_fails_a_new_line_missing_from_sku_mapping(
    change_validation, order_factory, lines_factory
):
    order = order_factory(lines=lines_factory(external_vendor_id="99999999CA", old_quantity=0))

    has_errors, validated_order, reached_lines = change_validation.run(order)  # act

    assert (has_errors, validated_order["error"]["id"]) == (True, "VIPM0041")
    assert "SelectFlexDiscounts" not in reached_lines
    assert "GetPreviewOrder" not in reached_lines


def test_validate_change_order_runs_every_step_for_a_mapped_new_line(
    change_validation, order_factory, lines_factory
):
    order = order_factory(lines=lines_factory(external_vendor_id="65304578CA", old_quantity=0))

    has_errors, validated_order, reached_lines = change_validation.run(order)  # act

    assert (has_errors, validated_order["error"]) == (False, None)
    assert reached_lines["SelectFlexDiscounts"] == order["lines"]
    assert reached_lines["GetPreviewOrder"] == order["lines"]
    assert reached_lines.keys() >= {"PreviewRenewalOrders", "UpdatePrices"}
    change_validation.get_adobe_product.assert_called_once_with("65304578CA", "COM")
