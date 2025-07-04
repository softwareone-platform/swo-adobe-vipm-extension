from freezegun import freeze_time

from adobe_vipm.adobe.client import AdobeClient
from adobe_vipm.adobe.dataclasses import ReturnableOrderInfo
from adobe_vipm.flows.constants import ERR_INVALID_TERMINATION_ORDER_QUANTITY
from adobe_vipm.flows.context import Context
from adobe_vipm.flows.fulfillment.shared import (
    SetOrUpdateCotermNextSyncDates,
    ValidateRenewalWindow,
)
from adobe_vipm.flows.helpers import SetupContext, Validate3YCCommitment
from adobe_vipm.flows.validation.shared import ValidateDuplicateLines
from adobe_vipm.flows.validation.termination import (
    ValidateDownsizes,
    validate_termination_order,
)


@freeze_time("2024-11-09 12:30:00")
def test_validate_downsizes_step_success(
    mocker,
    order_factory,
    lines_factory,
    adobe_customer_factory,
    adobe_order_factory,
    adobe_items_factory,
):
    """
    Tests the validate downsizes step when all validations pass.
    """
    order = order_factory(
        lines=lines_factory(
            quantity=3,
            old_quantity=7,
        )
    )
    adobe_customer = adobe_customer_factory(coterm_date="2025-10-09")
    adobe_order_1 = adobe_order_factory(
        order_type="NEW",
        items=adobe_items_factory(
            quantity=1,
            subscription_id="6158e1cf0e4414a9b3a06d123969fdNA",
        ),
    )
    adobe_order_2 = adobe_order_factory(
        order_type="NEW",
        items=adobe_items_factory(
            quantity=2,
            subscription_id="6158e1cf0e4414a9b3a06d123969fdNA",
        ),
    )
    adobe_order_3 = adobe_order_factory(
        order_type="NEW",
        items=adobe_items_factory(
            quantity=1,
            subscription_id="6158e1cf0e4414a9b3a06d123969fdNA",
        ),
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

    mocked_adobe_client = mocker.MagicMock(spec=AdobeClient)
    mocked_adobe_client.get_returnable_orders_by_subscription_id.return_value = [
        ret_info_1,
        ret_info_2,
        ret_info_3,
    ]
    mocked_adobe_client.get_subscriptions.return_value = {
        "items": [{"status": "1000", "offerId": sku}]
    }

    mocker.patch(
        "adobe_vipm.flows.validation.termination.get_adobe_client",
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

    mocked_adobe_client.get_subscriptions.assert_called_once_with(
        context.authorization_id,
        context.adobe_customer_id,
    )
    mocked_adobe_client.get_returnable_orders_by_subscription_id.assert_called_once_with(
        context.authorization_id,
        context.adobe_customer_id,
        "6158e1cf0e4414a9b3a06d123969fdNA",
        context.adobe_customer["cotermDate"],
        return_orders=None,
    )
    mocked_next_step.assert_called_once_with(mocked_client, context)


@freeze_time("2024-11-09 12:30:00")
def test_validate_downsizes_step_no_returnable_orders(
    mocker,
    order_factory,
    lines_factory,
    adobe_customer_factory,
):
    """
    Tests the validate downsizes step when no returnable orders are found.
    """
    order = order_factory(
        lines=lines_factory(
            quantity=3,
            old_quantity=7,
        )
    )
    adobe_customer = adobe_customer_factory(coterm_date="2025-10-09")

    mocked_adobe_client = mocker.MagicMock(spec=AdobeClient)
    mocked_adobe_client.get_returnable_orders_by_subscription_id.return_value = []

    sku = order["lines"][0]["item"]["externalIds"]["vendor"]

    mocker.patch(
        "adobe_vipm.flows.validation.termination.get_adobe_client",
        return_value=mocked_adobe_client,
    )
    mocked_client = mocker.MagicMock()
    mocked_next_step = mocker.MagicMock()

    mocked_adobe_client.get_subscriptions.return_value = {
        "items": [{"status": "1000", "offerId": sku}]
    }

    context = Context(
        order=order,
        authorization_id=order["authorization"]["id"],
        downsize_lines=order["lines"],
        adobe_customer_id=adobe_customer["customerId"],
        adobe_customer=adobe_customer,
    )

    step = ValidateDownsizes()
    step(mocked_client, context, mocked_next_step)

    mocked_adobe_client.get_subscriptions.assert_called_once_with(
        context.authorization_id,
        context.adobe_customer_id,
    )

    assert not context.validation_succeeded
    assert context.order["error"] == ERR_INVALID_TERMINATION_ORDER_QUANTITY.to_dict()
    mocked_next_step.assert_not_called()


@freeze_time("2024-11-09 12:30:00")
def test_validate_downsizes_step_quantity_mismatch(
    mocker,
    order_factory,
    lines_factory,
    adobe_customer_factory,
    adobe_order_factory,
    adobe_items_factory,
):
    """
    Tests the validate downsizes step when the quantity doesn't match the returnable orders.
    """
    order = order_factory(
        lines=lines_factory(
            quantity=3,
            old_quantity=7,
        )
    )
    adobe_customer = adobe_customer_factory(coterm_date="2025-10-09")
    adobe_order_1 = adobe_order_factory(
        order_type="NEW",
        items=adobe_items_factory(
            quantity=1,
            subscription_id="6158e1cf0e4414a9b3a06d123969fdNA",
        ),
    )
    adobe_order_2 = adobe_order_factory(
        order_type="NEW",
        items=adobe_items_factory(
            quantity=2,
            subscription_id="6158e1cf0e4414a9b3a06d123969fdNA",
        ),
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

    sku = order["lines"][0]["item"]["externalIds"]["vendor"]

    mocked_adobe_client = mocker.MagicMock(spec=AdobeClient)
    mocked_adobe_client.get_returnable_orders_by_subscription_id.return_value = [
        ret_info_1,
        ret_info_2,
    ]

    mocked_adobe_client.get_subscriptions.return_value = {
        "items": [{"status": "1000", "offerId": sku}]
    }

    mocker.patch(
        "adobe_vipm.flows.validation.termination.get_adobe_client",
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

    mocked_adobe_client.get_subscriptions.assert_called_once_with(
        context.authorization_id,
        context.adobe_customer_id,
    )
    assert not context.validation_succeeded
    assert context.order["error"] == ERR_INVALID_TERMINATION_ORDER_QUANTITY.to_dict()
    mocked_next_step.assert_not_called()


@freeze_time("2024-11-09 12:30:00")
def test_validate_downsizes_step_inactive_subscription(
    mocker,
    order_factory,
    lines_factory,
    adobe_customer_factory,
):
    """
    Tests the validate downsizes step when the subscription is inactive.
    """
    order = order_factory(
        lines=lines_factory(
            quantity=3,
            old_quantity=7,
        )
    )
    adobe_customer = adobe_customer_factory(coterm_date="2025-10-09")
    sku = order["lines"][0]["item"]["externalIds"]["vendor"]

    mocked_adobe_client = mocker.MagicMock(spec=AdobeClient)
    mocked_adobe_client.get_subscriptions.return_value = {
        "items": [{"status": "1004", "offerId": sku}]
    }

    mocker.patch(
        "adobe_vipm.flows.validation.termination.get_adobe_client",
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
    mocked_adobe_client.get_subscriptions.assert_called_once_with(
        context.authorization_id,
        context.adobe_customer_id,
    )

    mocked_adobe_client.get_returnable_orders_by_subscription_id.assert_not_called()
    mocked_next_step.assert_called_once_with(mocked_client, context)


def test_validate_termination_order(mocker):
    """
    Tests the termination order validation pipeline is created with the
    expected steps and executed.
    """
    mocked_pipeline_instance = mocker.MagicMock()

    mocked_pipeline_ctor = mocker.patch(
        "adobe_vipm.flows.validation.termination.Pipeline",
        return_value=mocked_pipeline_instance,
    )
    mocked_context = mocker.MagicMock()
    mocked_context_ctor = mocker.patch(
        "adobe_vipm.flows.validation.termination.Context", return_value=mocked_context
    )
    mocked_client = mocker.MagicMock()
    mocked_order = mocker.MagicMock()

    validate_termination_order(mocked_client, mocked_order)

    assert len(mocked_pipeline_ctor.mock_calls[0].args) == 6

    expected_steps = [
        SetupContext,
        ValidateDuplicateLines,
        SetOrUpdateCotermNextSyncDates,
        ValidateRenewalWindow,
        ValidateDownsizes,
        Validate3YCCommitment,
    ]

    actual_steps = [type(step) for step in mocked_pipeline_ctor.mock_calls[0].args]
    assert actual_steps == expected_steps

    mocked_context_ctor.assert_called_once_with(order=mocked_order)
    mocked_pipeline_instance.run.assert_called_once_with(
        mocked_client,
        mocked_context,
    )
