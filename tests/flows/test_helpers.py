from adobe_vipm.adobe.constants import ORDER_TYPE_PREVIEW
from adobe_vipm.flows.context import Context
from adobe_vipm.flows.helpers import (
    SetupContext,
    update_purchase_prices,
)


def test_update_purchase_price(
    mocker,
    order_factory,
    adobe_order_factory,
):
    """
    Tests the update of unit purchase price based on sku with discount level
    returned in the adobe preview order looking at the pricelist.
    """
    adobe_preview_order = adobe_order_factory(ORDER_TYPE_PREVIEW)
    mocked_adobe_client = mocker.MagicMock()
    mocked_adobe_client.create_preview_order.return_value = adobe_preview_order
    order = order_factory()
    mocker.patch(
        "adobe_vipm.flows.helpers.get_prices_for_skus",
        return_value={"65304578CA01A12": 7892.11},
    )
    updated_order = update_purchase_prices(
        mocked_adobe_client,
        order,
    )

    assert updated_order["lines"][0]["price"]["unitPP"] == 7892.11


def test_initialize_step(
    mocker, agreement, order_factory, lines_factory, fulfillment_parameters_factory
):
    """
    Tests the order processing initialization step without the retrival of
    the Adobe customer.
    """
    mocked_get_agreement = mocker.patch(
        "adobe_vipm.flows.helpers.get_agreement", return_value=agreement
    )
    mocked_get_licensee = mocker.patch(
        "adobe_vipm.flows.helpers.get_licensee", return_value=agreement["licensee"]
    )
    mocker.patch(
        "adobe_vipm.flows.helpers.get_adobe_client",
    )

    downsizing_items = lines_factory(
        line_id=1,
        item_id=1,
        old_quantity=10,
        quantity=8,
    )
    upsizing_items = lines_factory(
        line_id=2,
        item_id=2,
        old_quantity=10,
        quantity=12,
    )

    order = order_factory(
        lines=downsizing_items + upsizing_items,
        fulfillment_parameters=fulfillment_parameters_factory(
            retry_count="12",
        ),
    )

    mocked_client = mocker.MagicMock()
    mocked_next_step = mocker.MagicMock()

    context = Context(order=order)

    step = SetupContext()
    step(mocked_client, context, mocked_next_step)

    assert context.order["agreement"] == agreement
    assert context.order["agreement"]["licensee"] == agreement["licensee"]
    assert context.current_attempt == 12
    assert context.downsize_lines == downsizing_items
    assert context.upsize_lines == upsizing_items
    mocked_get_agreement.assert_called_once_with(
        mocked_client,
        order["agreement"]["id"],
    )
    mocked_get_licensee.assert_called_once_with(
        mocked_client,
        order["agreement"]["licensee"]["id"],
    )
    mocked_next_step.assert_called_once_with(mocked_client, context)


def test_initialize_step_with_adobe_customer_and_order_id(
    mocker,
    agreement,
    order_factory,
    lines_factory,
    fulfillment_parameters_factory,
    adobe_customer_factory,
):
    """
    Tests the order processing initialization step with the retrival of
    the Adobe customer.
    """
    mocked_get_agreement = mocker.patch(
        "adobe_vipm.flows.helpers.get_agreement", return_value=agreement
    )
    mocked_get_licensee = mocker.patch(
        "adobe_vipm.flows.helpers.get_licensee", return_value=agreement["licensee"]
    )

    adobe_customer = adobe_customer_factory()

    mocked_adobe_client = mocker.MagicMock()
    mocked_adobe_client.get_customer.return_value = adobe_customer

    mocker.patch(
        "adobe_vipm.flows.helpers.get_adobe_client",
        return_value=mocked_adobe_client,
    )

    order = order_factory(
        fulfillment_parameters=fulfillment_parameters_factory(
            customer_id="adobe-customer-id",
        ),
        external_ids={"vendor": "adobe-order-id"},
    )

    mocked_client = mocker.MagicMock()
    mocked_next_step = mocker.MagicMock()

    context = Context(order=order)

    step = SetupContext()
    step(mocked_client, context, mocked_next_step)

    assert context.order["agreement"] == agreement
    assert context.order["agreement"]["licensee"] == agreement["licensee"]
    assert context.current_attempt == 0
    assert context.downsize_lines == []
    assert context.upsize_lines == order["lines"]
    assert context.adobe_customer_id == "adobe-customer-id"
    assert context.adobe_customer == adobe_customer
    assert context.adobe_new_order_id == "adobe-order-id"
    mocked_get_agreement.assert_called_once_with(
        mocked_client,
        order["agreement"]["id"],
    )
    mocked_get_licensee.assert_called_once_with(
        mocked_client,
        order["agreement"]["licensee"]["id"],
    )
    mocked_next_step.assert_called_once_with(mocked_client, context)
