from datetime import datetime, timedelta

from freezegun import freeze_time

from adobe_vipm.adobe.dataclasses import ReturnableOrderInfo
from adobe_vipm.flows.context import Context
from adobe_vipm.flows.fulfillment.shared import (
    SetOrUpdateCotermDate,
    ValidateRenewalWindow,
)
from adobe_vipm.flows.helpers import SetupContext, Validate3YCCommitment
from adobe_vipm.flows.validation.change import (
    GetPreviewOrder,
    ValidateDownsizes,
    validate_change_order,
)
from adobe_vipm.flows.validation.shared import ValidateDuplicateLines


@freeze_time("2024-11-09 12:30:00")
def test_validate_downsizes_step(
    mocker,
    order_factory,
    lines_factory,
    adobe_customer_factory,
    adobe_order_factory,
    adobe_items_factory,
):
    order = order_factory(
        lines=lines_factory(
            quantity=7,
            old_quantity=14,
        )
    )
    coterm_date = datetime.today() + timedelta(days=20)
    adobe_customer = adobe_customer_factory(coterm_date=coterm_date.strftime("%Y-%m-%d"))
    adobe_order_1 = adobe_order_factory(
        order_type="NEW",
        items=adobe_items_factory(quantity=1),
    )
    adobe_order_2 = adobe_order_factory(
        order_type="NEW",
        items=adobe_items_factory(quantity=2),
    )
    adobe_order_3 = adobe_order_factory(
        order_type="NEW",
        items=adobe_items_factory(quantity=4),
    )

    ret_info_1 = ReturnableOrderInfo(
        adobe_order_1,
        adobe_order_1["lineItems"][0],
        adobe_order_1["lineItems"][0]["quantity"],
    )
    ret_info_2 = ReturnableOrderInfo(
        adobe_order_2,
        adobe_order_2["lineItems"][0],
        adobe_order_2["lineItems"][0]["quantity"],
    )
    ret_info_3 = ReturnableOrderInfo(
        adobe_order_3,
        adobe_order_3["lineItems"][0],
        adobe_order_3["lineItems"][0]["quantity"],
    )

    sku = order["lines"][0]["item"]["externalIds"]["vendor"]

    mocked_adobe_client = mocker.MagicMock()
    mocked_adobe_client.get_returnable_orders_by_sku.return_value = [
        ret_info_1,
        ret_info_2,
        ret_info_3,
    ]

    mocker.patch(
        "adobe_vipm.flows.validation.change.get_adobe_client",
        return_value=mocked_adobe_client,
    )
    mocked_client = mocker.MagicMock()
    mocked_next_step = mocker.MagicMock()

    context = Context(
        order=order,
        authorization_id=order["authorization"]["id"],
        downsize_lines=order["lines"],
        adobe_customer_id=adobe_customer["customerId"],
        adobe_customer=adobe_customer,
    )

    step = ValidateDownsizes()
    step(mocked_client, context, mocked_next_step)

    assert context.validation_succeeded is True
    mocked_adobe_client.get_returnable_orders_by_sku.assert_called_once_with(
        context.authorization_id,
        context.adobe_customer_id,
        sku,
        context.adobe_customer["cotermDate"],
    )
    mocked_next_step.assert_called_once_with(mocked_client, context)


@freeze_time("2024-11-09 12:30:00")
def test_validate_downsizes_step_no_returnable_orders(
    mocker,
    order_factory,
    lines_factory,
    adobe_customer_factory,
    adobe_order_factory,
    adobe_items_factory,
):
    order = order_factory(
        lines=lines_factory(
            quantity=7,
            old_quantity=14,
        )
    )
    coterm_date = datetime.today() + timedelta(days=20)
    adobe_customer = adobe_customer_factory(coterm_date=coterm_date.strftime("%Y-%m-%d"))
    sku = order["lines"][0]["item"]["externalIds"]["vendor"]

    mocked_adobe_client = mocker.MagicMock()
    mocked_adobe_client.get_returnable_orders_by_sku.return_value = []

    mocker.patch(
        "adobe_vipm.flows.validation.change.get_adobe_client",
        return_value=mocked_adobe_client,
    )
    mocked_client = mocker.MagicMock()
    mocked_next_step = mocker.MagicMock()

    context = Context(
        order=order,
        authorization_id=order["authorization"]["id"],
        downsize_lines=order["lines"],
        adobe_customer_id=adobe_customer["customerId"],
        adobe_customer=adobe_customer,
    )

    step = ValidateDownsizes()
    step(mocked_client, context, mocked_next_step)

    assert context.validation_succeeded is True
    mocked_adobe_client.get_returnable_orders_by_sku.assert_called_once_with(
        context.authorization_id,
        context.adobe_customer_id,
        sku,
        context.adobe_customer["cotermDate"],
    )
    mocked_next_step.assert_called_once_with(mocked_client, context)


@freeze_time("2024-11-09 12:30:00")
def test_validate_downsizes_step_invalid_quantity(
    mocker,
    order_factory,
    lines_factory,
    adobe_customer_factory,
    adobe_order_factory,
    adobe_items_factory,
):
    order = order_factory(
        lines=lines_factory(
            quantity=7,
            old_quantity=16,
        )
    )
    coterm_date = datetime.today() + timedelta(days=20)
    adobe_customer = adobe_customer_factory(coterm_date=coterm_date.strftime("%Y-%m-%d"))
    adobe_order_1 = adobe_order_factory(
        order_type="NEW",
        items=adobe_items_factory(quantity=1),
        creation_date="2024-05-01",
    )
    adobe_order_2 = adobe_order_factory(
        order_type="NEW",
        items=adobe_items_factory(quantity=2),
        creation_date="2024-05-07",
    )
    adobe_order_3 = adobe_order_factory(
        order_type="NEW",
        items=adobe_items_factory(quantity=4),
        creation_date="2024-05-11",
    )

    ret_info_1 = ReturnableOrderInfo(
        adobe_order_1,
        adobe_order_1["lineItems"][0],
        adobe_order_1["lineItems"][0]["quantity"],
    )
    ret_info_2 = ReturnableOrderInfo(
        adobe_order_2,
        adobe_order_2["lineItems"][0],
        adobe_order_2["lineItems"][0]["quantity"],
    )
    ret_info_3 = ReturnableOrderInfo(
        adobe_order_3,
        adobe_order_3["lineItems"][0],
        adobe_order_3["lineItems"][0]["quantity"],
    )

    sku = order["lines"][0]["item"]["externalIds"]["vendor"]

    mocked_adobe_client = mocker.MagicMock()
    mocked_adobe_client.get_returnable_orders_by_sku.return_value = [
        ret_info_1,
        ret_info_2,
        ret_info_3,
    ]

    mocker.patch(
        "adobe_vipm.flows.validation.change.get_adobe_client",
        return_value=mocked_adobe_client,
    )
    mocked_client = mocker.MagicMock()
    mocked_next_step = mocker.MagicMock()

    context = Context(
        order=order,
        authorization_id=order["authorization"]["id"],
        downsize_lines=order["lines"],
        adobe_customer_id=adobe_customer["customerId"],
        adobe_customer=adobe_customer,
    )

    step = ValidateDownsizes()
    step(mocked_client, context, mocked_next_step)

    assert context.validation_succeeded is False
    mocked_adobe_client.get_returnable_orders_by_sku.assert_called_once_with(
        context.authorization_id,
        context.adobe_customer_id,
        sku,
        context.adobe_customer["cotermDate"],
    )
    assert context.order["error"] == {
        "id": "VIPM0019",
        "message": (
            "Could not find suitable returnable orders for all items.\nCannot reduce item "
            "`Awesome product` quantity by 9. Please reduce the quantity "
            "by 1, 2, 4, or any combination of these values, or wait until 2024-05-26 "
            "when there are no returnable "
            "orders to modify your renewal quantity."
        ),
    }
    mocked_next_step.assert_not_called()


@freeze_time("2024-11-09 12:30:00")
def test_validate_downsizes_step_invalid_quantity_last_two_weeks(
    mocker,
    order_factory,
    lines_factory,
    adobe_customer_factory,
    adobe_order_factory,
    adobe_items_factory,
):
    order = order_factory(
        lines=lines_factory(
            quantity=7,
            old_quantity=16,
        )
    )
    coterm_date = datetime.today() + timedelta(days=10)
    adobe_customer = adobe_customer_factory(coterm_date=coterm_date.strftime("%Y-%m-%d"))

    mocked_adobe_client = mocker.MagicMock()

    mocker.patch(
        "adobe_vipm.flows.validation.change.get_adobe_client",
        return_value=mocked_adobe_client,
    )
    mocked_client = mocker.MagicMock()
    mocked_next_step = mocker.MagicMock()

    context = Context(
        order=order,
        authorization_id=order["authorization"]["id"],
        downsize_lines=order["lines"],
        adobe_customer_id=adobe_customer["customerId"],
        adobe_customer=adobe_customer,
    )

    step = ValidateDownsizes()
    step(mocked_client, context, mocked_next_step)

    assert context.validation_succeeded is True
    mocked_next_step.assert_called_once_with(mocked_client, context)


@freeze_time("2024-11-09 12:30:00")
def test_validate_downsizes_step_invalid_quantity_initial_purchase_only(
    mocker,
    order_factory,
    lines_factory,
    adobe_customer_factory,
    adobe_order_factory,
    adobe_items_factory,
):
    order = order_factory(
        lines=lines_factory(
            quantity=7,
            old_quantity=16,
        )
    )
    coterm_date = datetime.today() + timedelta(days=20)
    adobe_customer = adobe_customer_factory(coterm_date=coterm_date.strftime("%Y-%m-%d"))
    adobe_order_1 = adobe_order_factory(
        order_type="NEW",
        items=adobe_items_factory(quantity=16),
        creation_date="2024-05-01",
    )

    ret_info_1 = ReturnableOrderInfo(
        adobe_order_1,
        adobe_order_1["lineItems"][0],
        adobe_order_1["lineItems"][0]["quantity"],
    )

    sku = order["lines"][0]["item"]["externalIds"]["vendor"]

    mocked_adobe_client = mocker.MagicMock()
    mocked_adobe_client.get_returnable_orders_by_sku.return_value = [
        ret_info_1,
    ]

    mocker.patch(
        "adobe_vipm.flows.validation.change.get_adobe_client",
        return_value=mocked_adobe_client,
    )
    mocked_client = mocker.MagicMock()
    mocked_next_step = mocker.MagicMock()

    context = Context(
        order=order,
        authorization_id=order["authorization"]["id"],
        downsize_lines=order["lines"],
        adobe_customer_id=adobe_customer["customerId"],
        adobe_customer=adobe_customer,
    )

    step = ValidateDownsizes()
    step(mocked_client, context, mocked_next_step)

    assert context.validation_succeeded is False
    mocked_adobe_client.get_returnable_orders_by_sku.assert_called_once_with(
        context.authorization_id,
        context.adobe_customer_id,
        sku,
        context.adobe_customer["cotermDate"],
    )
    assert context.order["error"] == {
        "id": "VIPM0019",
        "message": (
            "Could not find suitable returnable orders for all items.\nCannot reduce item "
            "`Awesome product` quantity by 9 and there is only one returnable order which would "
            "reduce the quantity to zero. Consider placing a Termination order for this "
            "subscription instead and place a new order for 7 licenses."
        ),
    }
    mocked_next_step.assert_not_called()


def test_validate_change_order(mocker):
    """Tests the validate order entrypoint function when it validates."""

    mocked_pipeline_instance = mocker.MagicMock()

    mocked_pipeline_ctor = mocker.patch(
        "adobe_vipm.flows.validation.change.Pipeline",
        return_value=mocked_pipeline_instance,
    )
    mocked_context = mocker.MagicMock()
    mocked_context_ctor = mocker.patch(
        "adobe_vipm.flows.validation.change.Context", return_value=mocked_context
    )
    mocked_client = mocker.MagicMock()
    mocked_order = mocker.MagicMock()

    validate_change_order(mocked_client, mocked_order)

    assert len(mocked_pipeline_ctor.mock_calls[0].args) == 8

    expected_steps = [
        SetupContext,
        ValidateDuplicateLines,
        SetOrUpdateCotermDate,
        ValidateRenewalWindow,
        ValidateDownsizes,
        Validate3YCCommitment,
        GetPreviewOrder,
    ]

    actual_steps = [type(step) for step in mocked_pipeline_ctor.mock_calls[0].args[:7]]
    assert actual_steps == expected_steps

    mocked_context_ctor.assert_called_once_with(order=mocked_order)
    mocked_pipeline_instance.run.assert_called_once_with(
        mocked_client,
        mocked_context,
    )
