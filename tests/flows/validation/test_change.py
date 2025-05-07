from datetime import datetime, timedelta

from freezegun import freeze_time

from adobe_vipm.adobe.constants import STATUS_PROCESSED
from adobe_vipm.adobe.dataclasses import ReturnableOrderInfo
from adobe_vipm.flows.constants import (
    ERR_DOWNSIZE_MINIMUM_3YC_CONSUMABLES,
    ERR_DOWNSIZE_MINIMUM_3YC_GENERIC,
    ERR_DOWNSIZE_MINIMUM_3YC_LICENSES,
    ERR_DOWNSIZE_MINIMUM_3YC_VALIDATION,
)
from adobe_vipm.flows.context import Context
from adobe_vipm.flows.helpers import SetupContext, ValidateDownsizes3YC
from adobe_vipm.flows.validation.change import (
    GetPreviewOrder,
    ValidateDownsizes,
    validate_change_order,
)
from adobe_vipm.flows.validation.shared import (
    ValidateDuplicateLines,
)


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
    adobe_customer = adobe_customer_factory(
        coterm_date=coterm_date.strftime("%Y-%m-%d")
    )
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
    adobe_customer = adobe_customer_factory(
        coterm_date=coterm_date.strftime("%Y-%m-%d")
    )
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
    adobe_customer = adobe_customer_factory(
        coterm_date=coterm_date.strftime("%Y-%m-%d")
    )
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
    adobe_customer = adobe_customer_factory(
        coterm_date=coterm_date.strftime("%Y-%m-%d")
    )

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
    adobe_customer = adobe_customer_factory(
        coterm_date=coterm_date.strftime("%Y-%m-%d")
    )
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

    assert len(mocked_pipeline_ctor.mock_calls[0].args) == 5

    assert isinstance(mocked_pipeline_ctor.mock_calls[0].args[0], SetupContext)
    assert isinstance(
        mocked_pipeline_ctor.mock_calls[0].args[1], ValidateDuplicateLines
    )
    assert isinstance(mocked_pipeline_ctor.mock_calls[0].args[2], ValidateDownsizes)
    assert isinstance(
        mocked_pipeline_ctor.mock_calls[0].args[3],
        ValidateDownsizes3YC,
    )
    assert isinstance(
        mocked_pipeline_ctor.mock_calls[0].args[4],
        GetPreviewOrder,
    )

    mocked_context_ctor.assert_called_once_with(order=mocked_order)
    mocked_pipeline_instance.run.assert_called_once_with(
        mocked_client,
        mocked_context,
    )


@freeze_time("2024-11-09 12:30:00")
def test_validate_downsize_3yc_orders_step_error_minimum_license_quantity(
    mocker,
    order_factory,
    adobe_subscription_factory,
    adobe_commitment_factory,
    adobe_customer_factory,
    lines_factory,
):
    """
    Tests the validate returnable orders step when the user has 3YC commitment benefits and
    the resulting number of licenses after the return is greater or equal to the minimum 3YC
    quantity.
    """
    adobe_3yc_commitment = adobe_commitment_factory(licenses=25, consumables=0)

    adobe_customer = adobe_customer_factory(commitment=adobe_3yc_commitment)
    order_lines = lines_factory(
        line_id=None,
        item_id=1,
        quantity=10,
        old_quantity=20,
        name="Awesome Expired product 1",
        external_vendor_id="65304990CA",
        unit_purchase_price=33.04,
    )
    order_lines.extend(
        lines_factory(
            line_id=None,
            item_id=2,
            quantity=20,
            old_quantity=25,
            name="Awesome Expired product 2",
            external_vendor_id="65304991CA",
            unit_purchase_price=35.09,
        )
    )

    order = order_factory(lines=order_lines)
    context = Context(
        order=order,
        downsize_lines=order["lines"],
        adobe_returnable_orders={
            "sku1": (mocker.MagicMock(),),
            "sku2": (mocker.MagicMock(),),
        },
        adobe_customer_id="adobe-customer-id",
        adobe_customer=adobe_customer,
    )
    mocked_client = mocker.MagicMock()
    mocked_next_step = mocker.MagicMock()

    adobe_subscription = adobe_subscription_factory(offer_id="65304990CA01A12")
    adobe_subscription_2 = adobe_subscription_factory(offer_id="65304991CA01A12")

    mocked_adobe_client = mocker.MagicMock()
    mocked_adobe_client.get_subscriptions.return_value = {
        "items": [adobe_subscription, adobe_subscription_2],
    }

    mocker.patch(
        "adobe_vipm.flows.helpers.get_adobe_client",
        return_value=mocked_adobe_client,
    )

    step = ValidateDownsizes3YC(True)
    step(mocked_client, context, mocked_next_step)

    assert context.order["error"][
        "message"
    ] == ERR_DOWNSIZE_MINIMUM_3YC_LICENSES.format(minimum_licenses=25)
    mocked_next_step.assert_not_called()


@freeze_time("2024-11-09 12:30:00")
def test_validate_downsize_3yc_orders_step_error_minimum_license_consumables(
    mocker,
    order_factory,
    adobe_subscription_factory,
    adobe_commitment_factory,
    adobe_customer_factory,
    lines_factory,
    adobe_order_factory,
    adobe_items_factory,
):
    adobe_3yc_commitment = adobe_commitment_factory(licenses=0, consumables=37)

    adobe_customer = adobe_customer_factory(commitment=adobe_3yc_commitment)
    order_lines = lines_factory(
        line_id=None,
        item_id=1,
        quantity=10,
        old_quantity=20,
        name="Awesome Expired product 1",
        external_vendor_id="65304990CA",
        unit_purchase_price=33.04,
    )
    order_lines.extend(
        lines_factory(
            line_id=None,
            item_id=2,
            quantity=20,
            old_quantity=25,
            name="Awesome Expired product 2",
            external_vendor_id="65304991CA",
            unit_purchase_price=35.09,
        )
    )

    order = order_factory(lines=order_lines)

    context = Context(
        order=order,
        authorization_id=order["authorization"]["id"],
        downsize_lines=order["lines"],
        adobe_customer_id=adobe_customer["customerId"],
        adobe_customer=adobe_customer,
        adobe_return_orders={},
    )
    mocked_client = mocker.MagicMock()
    mocked_next_step = mocker.MagicMock()

    adobe_subscription = adobe_subscription_factory(offer_id="65304990CAT1A12")
    adobe_subscription_2 = adobe_subscription_factory(offer_id="65304991CAT1A12")

    mocked_adobe_client = mocker.MagicMock()
    mocked_adobe_client.get_subscriptions.return_value = {
        "items": [adobe_subscription, adobe_subscription_2],
    }

    mocker.patch(
        "adobe_vipm.flows.helpers.get_adobe_client",
        return_value=mocked_adobe_client,
    )

    step = ValidateDownsizes3YC(True)
    step(mocked_client, context, mocked_next_step)
    error = ERR_DOWNSIZE_MINIMUM_3YC_VALIDATION.to_dict(
        error=ERR_DOWNSIZE_MINIMUM_3YC_CONSUMABLES.format(minimum_consumables=37),
    )
    assert context.order["error"] == error
    mocked_next_step.assert_not_called()


@freeze_time("2024-11-09 12:30:00")
def test_validate_downsize_3yc_orders_step_error_minimum_quantity_generic(
    mocker,
    order_factory,
    adobe_subscription_factory,
    adobe_commitment_factory,
    adobe_customer_factory,
    lines_factory,
    adobe_order_factory,
    adobe_items_factory,
):
    adobe_3yc_commitment = adobe_commitment_factory(licenses=20, consumables=37)

    adobe_customer = adobe_customer_factory(commitment=adobe_3yc_commitment)
    order_lines = lines_factory(
        line_id=None,
        item_id=1,
        quantity=10,
        old_quantity=20,
        name="Awesome Expired product 1",
        external_vendor_id="65304990CA",
        unit_purchase_price=33.04,
    )
    order_lines.extend(
        lines_factory(
            line_id=None,
            item_id=2,
            quantity=20,
            old_quantity=37,
            name="Awesome Expired product 2",
            external_vendor_id="65304991CA",
            unit_purchase_price=35.09,
        )
    )

    order = order_factory(lines=order_lines)
    context = Context(
        order=order,
        authorization_id=order["authorization"]["id"],
        downsize_lines=order["lines"],
        adobe_customer_id=adobe_customer["customerId"],
        adobe_customer=adobe_customer,
        adobe_return_orders={},
    )
    mocked_client = mocker.MagicMock()
    mocked_next_step = mocker.MagicMock()

    adobe_subscription = adobe_subscription_factory(offer_id="65304990CA01A12")
    adobe_subscription_2 = adobe_subscription_factory(offer_id="65304991CAT1A12")

    mocked_adobe_client = mocker.MagicMock()
    mocked_adobe_client.get_subscriptions.return_value = {
        "items": [adobe_subscription, adobe_subscription_2],
    }

    mocker.patch(
        "adobe_vipm.flows.helpers.get_adobe_client",
        return_value=mocked_adobe_client,
    )

    step = ValidateDownsizes3YC(True)
    step(mocked_client, context, mocked_next_step)

    assert context.order["error"]["message"] == ERR_DOWNSIZE_MINIMUM_3YC_GENERIC.format(
        minimum_consumables=37, minimum_licenses=20
    )
    mocked_next_step.assert_not_called()


def test_validate_downsize_3yc_orders_step_not_commitment(
    mocker,
    order_factory,
    adobe_subscription_factory,
    adobe_commitment_factory,
    adobe_customer_factory,
    lines_factory,
    adobe_order_factory,
    adobe_items_factory,
):
    adobe_customer = adobe_customer_factory()
    order_lines = lines_factory(
        line_id=None,
        item_id=1,
        quantity=10,
        old_quantity=20,
        name="Awesome Expired product 1",
        external_vendor_id="65304990CA",
        unit_purchase_price=33.04,
    )
    order_lines.extend(
        lines_factory(
            line_id=None,
            item_id=2,
            quantity=20,
            old_quantity=37,
            name="Awesome Expired product 2",
            external_vendor_id="65304991CA",
            unit_purchase_price=35.09,
        )
    )

    order = order_factory(lines=order_lines)
    context = Context(
        order=order,
        authorization_id=order["authorization"]["id"],
        downsize_lines=order["lines"],
        adobe_customer_id=adobe_customer["customerId"],
        adobe_customer=adobe_customer,
        adobe_return_orders={},
    )
    mocked_client = mocker.MagicMock()
    mocked_next_step = mocker.MagicMock()

    step = ValidateDownsizes3YC()
    step(mocked_client, context, mocked_next_step)
    mocked_next_step.assert_called_once_with(mocked_client, context)


def test_validate_downsize_3yc_orders_return_order_created(
    mocker,
    order_factory,
    adobe_subscription_factory,
    adobe_commitment_factory,
    adobe_customer_factory,
    lines_factory,
    adobe_order_factory,
    adobe_items_factory,
):
    adobe_3yc_commitment = adobe_commitment_factory(licenses=20, consumables=37)
    adobe_customer = adobe_customer_factory(commitment=adobe_3yc_commitment)
    order_lines = lines_factory(
        line_id=None,
        item_id=1,
        quantity=10,
        old_quantity=20,
        name="Awesome Expired product 1",
        external_vendor_id="65304990CA",
        unit_purchase_price=33.04,
    )
    order_lines.extend(
        lines_factory(
            line_id=None,
            item_id=2,
            quantity=20,
            old_quantity=37,
            name="Awesome Expired product 2",
            external_vendor_id="65304991CA",
            unit_purchase_price=35.09,
        )
    )

    order = order_factory(lines=order_lines)
    adobe_order_1 = adobe_order_factory(
        order_type="NEW",
        items=adobe_items_factory(quantity=1),
        status=STATUS_PROCESSED,
    )
    ret_info_1 = ReturnableOrderInfo(
        adobe_order_1,
        adobe_order_1["lineItems"][0],
        adobe_order_1["lineItems"][0]["quantity"],
    )
    sku = adobe_order_1["lineItems"][0]["offerId"][:10]

    return_order = adobe_order_factory(
        order_type="RETURN",
        status=STATUS_PROCESSED,
        reference_order_id=adobe_order_1["orderId"],
    )
    context = Context(
        order=order,
        authorization_id=order["authorization"]["id"],
        downsize_lines=order["lines"],
        adobe_customer_id=adobe_customer["customerId"],
        adobe_customer=adobe_customer,
        adobe_returnable_orders={sku: (ret_info_1,)},
        adobe_return_orders={sku: [return_order]},
    )
    mocked_client = mocker.MagicMock()
    mocked_next_step = mocker.MagicMock()

    step = ValidateDownsizes3YC()
    step(mocked_client, context, mocked_next_step)
    mocked_next_step.assert_called_once_with(mocked_client, context)
