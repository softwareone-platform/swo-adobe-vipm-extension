from datetime import date, timedelta

import pytest
from freezegun import freeze_time

from adobe_vipm.adobe.constants import STATUS_3YC_ACCEPTED
from adobe_vipm.adobe.dataclasses import ReturnableOrderInfo
from adobe_vipm.adobe.errors import AdobeAPIError
from adobe_vipm.flows.constants import (
    ERR_DOWNSIZE_MINIMUM_3YC_CONSUMABLES,
    ERR_DOWNSIZE_MINIMUM_3YC_GENERIC,
    ERR_DOWNSIZE_MINIMUM_3YC_LICENSES,
    ERR_DOWNSIZE_MINIMUM_3YC_VALIDATION,
    ERR_INVALID_RENEWAL_STATE,
    ERR_NO_RETURABLE_ERRORS_FOUND,
    TEMPLATE_NAME_CHANGE,
)
from adobe_vipm.flows.context import Context
from adobe_vipm.flows.fulfillment.change import (
    GetReturnableOrders,
    UpdateRenewalQuantities,
    ValidateDuplicateLines,
    ValidateReturnableOrders,
    fulfill_change_order,
)
from adobe_vipm.flows.fulfillment.shared import (
    CompleteOrder,
    CreateOrUpdateSubscriptions,
    GetPreviewOrder,
    GetReturnOrders,
    SetOrUpdateCotermNextSyncDates,
    SetupDueDate,
    StartOrderProcessing,
    SubmitNewOrder,
    SubmitReturnOrders,
    SyncAgreement,
    UpdatePrices,
    ValidateRenewalWindow,
)
from adobe_vipm.flows.helpers import SetupContext, ValidateDownsizes3YC


@pytest.mark.parametrize(
    "return_orders",
    [
        None,
        [{"orderId": "a"}, {"orderId": "b"}],
    ],
)
@freeze_time("2024-11-09 12:30:00")
def test_get_returnable_orders_step(
    mocker,
    order_factory,
    lines_factory,
    adobe_customer_factory,
    adobe_order_factory,
    adobe_items_factory,
    return_orders,
):
    """
    Tests the computation of the map of returnable orders by sku/quantity.
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
        "adobe_vipm.flows.fulfillment.change.get_adobe_client",
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
        adobe_return_orders={sku: return_orders},
    )

    step = GetReturnableOrders()
    step(mocked_client, context, mocked_next_step)

    assert context.adobe_returnable_orders[sku] == (ret_info_3,)
    mocked_adobe_client.get_returnable_orders_by_sku.assert_called_once_with(
        context.authorization_id,
        context.adobe_customer_id,
        sku,
        context.adobe_customer["cotermDate"],
        return_orders=return_orders,
    )
    mocked_next_step.assert_called_once_with(mocked_client, context)


@freeze_time("2024-11-09 12:30:00")
def test_get_returnable_orders_step_no_returnable_order(
    mocker,
    order_factory,
    lines_factory,
    adobe_customer_factory,
    adobe_order_factory,
    adobe_items_factory,
):
    """
    Tests the computation of the map of returnable orders by sku/quantity
    when no returnable orders are found for a given sku.
    """
    order = order_factory(
        lines=lines_factory(
            quantity=3,
            old_quantity=7,
        )
    )
    adobe_customer = adobe_customer_factory(coterm_date="2025-10-09")

    sku = order["lines"][0]["item"]["externalIds"]["vendor"]

    mocked_adobe_client = mocker.MagicMock()
    mocked_adobe_client.get_returnable_orders_by_sku.return_value = []

    mocker.patch(
        "adobe_vipm.flows.fulfillment.change.get_adobe_client",
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
        adobe_return_orders={sku: []},
    )

    step = GetReturnableOrders()
    step(mocked_client, context, mocked_next_step)

    assert sku not in context.adobe_returnable_orders
    mocked_adobe_client.get_returnable_orders_by_sku.assert_called_once_with(
        context.authorization_id,
        context.adobe_customer_id,
        sku,
        context.adobe_customer["cotermDate"],
        return_orders=[],
    )
    mocked_next_step.assert_called_once_with(mocked_client, context)


@freeze_time("2024-11-09 12:30:00")
def test_get_returnable_orders_step_quantity_mismatch(
    mocker,
    order_factory,
    lines_factory,
    adobe_customer_factory,
    adobe_order_factory,
    adobe_items_factory,
):
    """
    Tests the computation of the map of returnable orders by sku/quantity.
    Since the quantity doesn't match any of the sums of the avaibale returnable
    orders for such sku the value have to be None.
    """
    order = order_factory(
        lines=lines_factory(
            quantity=7,
            old_quantity=16,
        )
    )
    adobe_customer = adobe_customer_factory(coterm_date="2025-10-09")
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
        "adobe_vipm.flows.fulfillment.change.get_adobe_client",
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
        adobe_return_orders={},
    )

    step = GetReturnableOrders()
    step(mocked_client, context, mocked_next_step)

    assert context.adobe_returnable_orders[sku] is None
    mocked_adobe_client.get_returnable_orders_by_sku.assert_called_once_with(
        context.authorization_id,
        context.adobe_customer_id,
        sku,
        context.adobe_customer["cotermDate"],
        return_orders=None,
    )
    mocked_next_step.assert_called_once_with(mocked_client, context)


@freeze_time("2025-02-14 12:30:00")
def test_get_returnable_orders_step_last_two_weeks(
    mocker,
    order_factory,
    lines_factory,
    adobe_customer_factory,
    adobe_order_factory,
    adobe_items_factory,
):
    """
    Tests the computation of the map of returnable orders by sku/quantity.
    """
    order = order_factory(
        lines=lines_factory(
            quantity=3,
            old_quantity=7,
        )
    )
    adobe_customer = adobe_customer_factory(coterm_date="2025-02-20")

    mocked_adobe_client = mocker.MagicMock()
    mocked_adobe_client.get_returnable_orders_by_sku.return_value = []

    mocker.patch(
        "adobe_vipm.flows.fulfillment.change.get_adobe_client",
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
        adobe_return_orders={},
    )

    step = GetReturnableOrders()
    step(mocked_client, context, mocked_next_step)

    assert context.adobe_returnable_orders == {}
    mocked_adobe_client.get_returnable_orders_by_sku.assert_not_called()
    mocked_next_step.assert_called_once_with(mocked_client, context)


def test_validate_returnable_orders_step(mocker, order_factory):
    """
    Tests the validate returnable orders step when all downsize SKUs
    have returnable orders. The order processing pipeline will continue.
    """
    mocked_switch_to_failed = mocker.patch(
        "adobe_vipm.flows.fulfillment.change.switch_order_to_failed",
    )

    context = Context(
        order=order_factory(),
        adobe_returnable_orders={
            "sku1": (mocker.MagicMock(),),
            "sku2": (mocker.MagicMock(),),
        },
    )
    mocked_client = mocker.MagicMock()
    mocked_next_step = mocker.MagicMock()

    step = ValidateReturnableOrders()
    step(mocked_client, context, mocked_next_step)

    mocked_switch_to_failed.assert_not_called()
    mocked_next_step.assert_called_once_with(mocked_client, context)


def test_validate_returnable_orders_step_invalid(mocker, order_factory):
    """
    Tests the validate returnable orders step when at least one downsize SKU
    have no returnable orders. The order processing pipeline will stop.
    """
    mocked_switch_to_failed = mocker.patch(
        "adobe_vipm.flows.fulfillment.change.switch_order_to_failed",
    )

    context = Context(
        order=order_factory(),
        adobe_returnable_orders={
            "sku1": (mocker.MagicMock(),),
            "sku2": None,
        },
    )
    mocked_client = mocker.MagicMock()
    mocked_next_step = mocker.MagicMock()

    step = ValidateReturnableOrders()
    step(mocked_client, context, mocked_next_step)

    mocked_switch_to_failed.assert_called_once_with(
        mocked_client,
        context.order,
        ERR_NO_RETURABLE_ERRORS_FOUND.to_dict(
            non_returnable_skus="sku2",
        ),
    )
    mocked_next_step.assert_not_called()


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
    mocked_switch_to_failed = mocker.patch(
        "adobe_vipm.flows.helpers.switch_order_to_failed",
    )
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

    step = ValidateDownsizes3YC()
    step(mocked_client, context, mocked_next_step)

    mocked_switch_to_failed.assert_called_once_with(
        mocked_client,
        context.order,
        ERR_DOWNSIZE_MINIMUM_3YC_VALIDATION.to_dict(
            error=ERR_DOWNSIZE_MINIMUM_3YC_LICENSES.format(minimum_licenses=25),
        ),
    )
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
    mocked_switch_to_failed = mocker.patch(
        "adobe_vipm.flows.helpers.switch_order_to_failed",
    )
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

    step = ValidateDownsizes3YC()
    step(mocked_client, context, mocked_next_step)

    mocked_switch_to_failed.assert_called_once_with(
        mocked_client,
        context.order,
        ERR_DOWNSIZE_MINIMUM_3YC_VALIDATION.to_dict(
            error=ERR_DOWNSIZE_MINIMUM_3YC_CONSUMABLES.format(minimum_consumables=37),
        ),
    )
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
    mocked_switch_to_failed = mocker.patch(
        "adobe_vipm.flows.helpers.switch_order_to_failed",
    )
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
        deployment_id="",
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

    step = ValidateDownsizes3YC()
    step(mocked_client, context, mocked_next_step)
    error_msg = ERR_DOWNSIZE_MINIMUM_3YC_GENERIC.format(
        minimum_consumables=37, minimum_licenses=20
    )

    mocked_switch_to_failed.assert_called_once_with(
        mocked_client,
        context.order,
        ERR_DOWNSIZE_MINIMUM_3YC_VALIDATION.to_dict(error=error_msg),
    )
    mocked_next_step.assert_not_called()


@freeze_time("2024-11-09 12:30:00")
def test_validate_downsize_3yc_orders_step_error_item_not_found(
    mocker,
    order_factory,
    adobe_subscription_factory,
    adobe_commitment_factory,
    adobe_customer_factory,
    lines_factory,
    adobe_order_factory,
    adobe_items_factory,
):
    mocked_switch_to_failed = mocker.patch(
        "adobe_vipm.flows.helpers.switch_order_to_failed",
    )
    adobe_3yc_commitment = adobe_commitment_factory(licenses=20, consumables=37)

    adobe_customer = adobe_customer_factory(commitment=adobe_3yc_commitment)
    order_lines = lines_factory(
        line_id=None,
        item_id=1,
        quantity=10,
        old_quantity=20,
        name="Awesome Expired product 1",
        external_vendor_id="999999999CA",
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

    step = ValidateDownsizes3YC()
    step(mocked_client, context, mocked_next_step)

    mocked_switch_to_failed.assert_called_once_with(
        mocked_client,
        context.order,
        ERR_DOWNSIZE_MINIMUM_3YC_VALIDATION.to_dict(
            error="Item 999999999CA not found in Adobe subscriptions",
        ),
    )
    mocked_next_step.assert_not_called()


def test_validate_downsize_3yc_orders_step_skip_commitment_expired(
    mocker,
    order_factory,
    adobe_subscription_factory,
    adobe_commitment_factory,
    adobe_customer_factory,
    lines_factory,
    adobe_order_factory,
    adobe_items_factory,
):
    adobe_3yc_commitment = adobe_commitment_factory(
        licenses=20,
        consumables=37,
        end_date=(date.today() - timedelta(days=1)).isoformat(),
    )

    adobe_customer = adobe_customer_factory(commitment=adobe_3yc_commitment)
    order_lines = lines_factory(
        line_id=None,
        item_id=1,
        quantity=10,
        old_quantity=20,
        name="Awesome Expired product 1",
        external_vendor_id="999999999CA",
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


def test_validate_downsize_3yc_orders_step_skip_commitment_accepted(
    mocker,
    order_factory,
    adobe_subscription_factory,
    adobe_commitment_factory,
    adobe_customer_factory,
    lines_factory,
    adobe_order_factory,
    adobe_items_factory,
):
    adobe_3yc_commitment = adobe_commitment_factory(
        licenses=20, consumables=37, status=STATUS_3YC_ACCEPTED
    )

    adobe_customer = adobe_customer_factory(commitment=adobe_3yc_commitment)
    order_lines = lines_factory(
        line_id=None,
        item_id=1,
        quantity=10,
        old_quantity=20,
        name="Awesome Expired product 1",
        external_vendor_id="999999999CA",
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


def test_update_renewal_quantities_step(
    mocker,
    order_factory,
    lines_factory,
    subscriptions_factory,
    adobe_subscription_factory,
):
    subscriptions = subscriptions_factory()
    order = order_factory(
        lines=lines_factory(quantity=5)
        + lines_factory(line_id=2, item_id=2, external_vendor_id="99999999CA"),
        subscriptions=subscriptions,
    )

    adobe_sub = adobe_subscription_factory(
        renewal_quantity=10,
    )

    mocked_adobe_client = mocker.MagicMock()
    mocked_adobe_client.get_subscription.return_value = adobe_sub
    mocker.patch(
        "adobe_vipm.flows.fulfillment.change.get_adobe_client",
        return_value=mocked_adobe_client,
    )

    mocked_client = mocker.MagicMock()
    mocked_next_step = mocker.MagicMock()

    context = Context(
        order=order,
        order_id=order["id"],
        upsize_lines=order["lines"],
        authorization_id="auth-id",
        adobe_customer_id="adobe-customer-id",
    )

    step = UpdateRenewalQuantities()
    step(mocked_client, context, mocked_next_step)

    mocked_adobe_client.get_subscription.assert_called_once_with(
        context.authorization_id,
        context.adobe_customer_id,
        adobe_sub["subscriptionId"],
    )
    mocked_adobe_client.update_subscription.assert_called_once_with(
        context.authorization_id,
        context.adobe_customer_id,
        adobe_sub["subscriptionId"],
        quantity=5,
    )
    mocked_next_step.assert_called_once_with(mocked_client, context)


def test_update_renewal_quantities_step_quantity_match(
    mocker,
    order_factory,
    lines_factory,
    subscriptions_factory,
    adobe_subscription_factory,
):
    subscriptions = subscriptions_factory()
    order = order_factory(
        lines=lines_factory(quantity=10),
        subscriptions=subscriptions,
    )

    adobe_sub = adobe_subscription_factory(
        renewal_quantity=10,
    )

    mocked_adobe_client = mocker.MagicMock()
    mocked_adobe_client.get_subscription.return_value = adobe_sub
    mocker.patch(
        "adobe_vipm.flows.fulfillment.change.get_adobe_client",
        return_value=mocked_adobe_client,
    )

    mocked_client = mocker.MagicMock()
    mocked_next_step = mocker.MagicMock()

    context = Context(
        order=order,
        order_id=order["id"],
        upsize_lines=order["lines"],
        authorization_id="auth-id",
        adobe_customer_id="adobe-customer-id",
    )

    step = UpdateRenewalQuantities()
    step(mocked_client, context, mocked_next_step)

    mocked_adobe_client.get_subscription.assert_called_once_with(
        context.authorization_id,
        context.adobe_customer_id,
        adobe_sub["subscriptionId"],
    )
    mocked_adobe_client.update_subscription.assert_not_called()
    mocked_next_step.assert_called_once_with(mocked_client, context)


def test_fulfill_change_order(mocker):
    """
    Tests the change order pipeline is created with the
    expected steps and executed.
    """
    mocked_pipeline_instance = mocker.MagicMock()

    mocked_pipeline_ctor = mocker.patch(
        "adobe_vipm.flows.fulfillment.change.Pipeline",
        return_value=mocked_pipeline_instance,
    )
    mocked_context = mocker.MagicMock()
    mocked_context_ctor = mocker.patch(
        "adobe_vipm.flows.fulfillment.change.Context", return_value=mocked_context
    )
    mocked_client = mocker.MagicMock()
    mocked_order = mocker.MagicMock()

    fulfill_change_order(mocked_client, mocked_order)
    assert len(mocked_pipeline_ctor.mock_calls[0].args) == 18

    assert isinstance(mocked_pipeline_ctor.mock_calls[0].args[0], SetupContext)
    assert isinstance(mocked_pipeline_ctor.mock_calls[0].args[1], SetupDueDate)
    assert isinstance(
        mocked_pipeline_ctor.mock_calls[0].args[2], ValidateDuplicateLines
    )
    assert isinstance(
        mocked_pipeline_ctor.mock_calls[0].args[3], SetOrUpdateCotermNextSyncDates
    )
    assert isinstance(mocked_pipeline_ctor.mock_calls[0].args[4], StartOrderProcessing)
    assert (
        mocked_pipeline_ctor.mock_calls[0].args[4].template_name == TEMPLATE_NAME_CHANGE
    )
    assert isinstance(mocked_pipeline_ctor.mock_calls[0].args[5], ValidateRenewalWindow)
    assert isinstance(mocked_pipeline_ctor.mock_calls[0].args[6], GetReturnOrders)
    assert isinstance(mocked_pipeline_ctor.mock_calls[0].args[7], GetReturnableOrders)
    assert isinstance(
        mocked_pipeline_ctor.mock_calls[0].args[8], ValidateReturnableOrders
    )
    assert isinstance(mocked_pipeline_ctor.mock_calls[0].args[9], ValidateDownsizes3YC)
    assert isinstance(mocked_pipeline_ctor.mock_calls[0].args[10], GetPreviewOrder)
    assert isinstance(mocked_pipeline_ctor.mock_calls[0].args[11], SubmitReturnOrders)
    assert isinstance(mocked_pipeline_ctor.mock_calls[0].args[12], SubmitNewOrder)
    assert isinstance(
        mocked_pipeline_ctor.mock_calls[0].args[13], UpdateRenewalQuantities
    )
    assert isinstance(
        mocked_pipeline_ctor.mock_calls[0].args[14], CreateOrUpdateSubscriptions
    )
    assert isinstance(mocked_pipeline_ctor.mock_calls[0].args[15], UpdatePrices)
    assert isinstance(mocked_pipeline_ctor.mock_calls[0].args[16], CompleteOrder)
    assert (
        mocked_pipeline_ctor.mock_calls[0].args[16].template_name
        == TEMPLATE_NAME_CHANGE
    )
    assert isinstance(mocked_pipeline_ctor.mock_calls[0].args[17], SyncAgreement)
    mocked_context_ctor.assert_called_once_with(order=mocked_order)
    mocked_pipeline_instance.run.assert_called_once_with(
        mocked_client,
        mocked_context,
    )


def test_validate_update_renewal_quantity_invalid_renewal_state(
    mocker,
    order_factory,
    adobe_subscription_factory,
    adobe_api_error_factory,
    subscriptions_factory,
    lines_factory,
):
    """
    Tests the validate update renewal quantity step when the renewal state is invalid.
    """
    mocked_switch_to_failed = mocker.patch(
        "adobe_vipm.flows.fulfillment.change.switch_order_to_failed",
    )
    subscriptions = subscriptions_factory()
    order = order_factory(
        lines=lines_factory(quantity=5)
        + lines_factory(line_id=2, item_id=2, external_vendor_id="99999999CA"),
        subscriptions=subscriptions,
    )
    context = Context(
        order=order,
        order_id=order["id"],
        upsize_lines=order["lines"],
        authorization_id="auth-id",
        adobe_customer_id="adobe-customer-id",
    )
    mocked_client = mocker.MagicMock()
    mocked_next_step = mocker.MagicMock()
    adobe_sub = adobe_subscription_factory(
        renewal_quantity=10,
    )

    mocked_adobe_client = mocker.MagicMock()
    mocker.patch(
        "adobe_vipm.flows.fulfillment.change.get_adobe_client",
        return_value=mocked_adobe_client,
    )
    mocked_adobe_client.get_subscription.return_value = adobe_sub
    mocked_adobe_client.update_subscription.side_effect = AdobeAPIError(
        400,
        adobe_api_error_factory(
            "3120",
            "Update could not be performed because it would create an invalid renewal state",
        ),
    )

    step = UpdateRenewalQuantities()
    step(mocked_client, context, mocked_next_step)

    mocked_switch_to_failed.assert_called_once_with(
        mocked_client,
        context.order,
        ERR_INVALID_RENEWAL_STATE.to_dict(
            error="Update could not be performed because it would create an invalid renewal state",
        ),
    )
    mocked_next_step.assert_not_called()


def test_validate_update_renewal_quantity_error(
    mocker,
    order_factory,
    adobe_subscription_factory,
    adobe_api_error_factory,
    subscriptions_factory,
    lines_factory,
):
    """
    Tests the validate update renewal quantity step when the renewal state is invalid.
    """
    mocked_switch_to_failed = mocker.patch(
        "adobe_vipm.flows.fulfillment.change.switch_order_to_failed",
    )
    subscriptions = subscriptions_factory()
    order = order_factory(
        lines=lines_factory(quantity=5)
        + lines_factory(line_id=2, item_id=2, external_vendor_id="99999999CA"),
        subscriptions=subscriptions,
    )
    context = Context(
        order=order,
        order_id=order["id"],
        upsize_lines=order["lines"],
        authorization_id="auth-id",
        adobe_customer_id="adobe-customer-id",
    )
    mocked_client = mocker.MagicMock()
    mocked_next_step = mocker.MagicMock()
    adobe_sub = adobe_subscription_factory(
        renewal_quantity=10,
    )

    mocked_adobe_client = mocker.MagicMock()
    mocker.patch(
        "adobe_vipm.flows.fulfillment.change.get_adobe_client",
        return_value=mocked_adobe_client,
    )
    mocked_adobe_client.get_subscription.return_value = adobe_sub
    mocked_adobe_client.update_subscription.side_effect = AdobeAPIError(
        400,
        adobe_api_error_factory(
            "1000",
            "Error updating autorenewal quantity",
        ),
    )

    step = UpdateRenewalQuantities()
    step(mocked_client, context, mocked_next_step)

    mocked_switch_to_failed.assert_not_called()
    mocked_next_step.assert_not_called()
