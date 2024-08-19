import logging

import pytest

from adobe_vipm.flows.fulfillment.shared import (
    send_email_notification,
    set_customer_coterm_date_if_null,
    start_processing_attempt,
    update_order_actual_price,
)
from adobe_vipm.flows.utils import get_coterm_date, get_notifications_recipient


@pytest.mark.parametrize(
    ("status", "subject"),
    [
        (
            "Processing",
            "Order status update ORD-1234 for A buyer",
        ),
        (
            "Querying",
            "This order need your attention ORD-1234 for A buyer",
        ),
        (
            "Completed",
            "Order status update ORD-1234 for A buyer",
        ),
        (
            "Failed",
            "Order status update ORD-1234 for A buyer",
        ),
    ],
)
def test_send_email_notification(mocker, settings, order_factory, status, subject):
    settings.EXTENSION_CONFIG = {
        "EMAIL_NOTIFICATIONS_ENABLED": "1",
    }
    mocked_mpt_client = mocker.MagicMock()

    mocked_get_rendered_template = mocker.patch(
        "adobe_vipm.flows.fulfillment.shared.get_rendered_template",
        return_value="rendered-template",
    )

    mocked_send_email = mocker.patch("adobe_vipm.flows.fulfillment.shared.send_email")

    order = order_factory(order_id="ORD-1234", status=status)

    send_email_notification(mocked_mpt_client, order)
    mocked_get_rendered_template.assert_called_once_with(mocked_mpt_client, order["id"])

    mocked_send_email.assert_called_once_with(
        get_notifications_recipient(order),
        subject,
        "email",
        {
            "order": order,
            "activation_template": "<p>rendered-template</p>\n",
            "api_base_url": settings.MPT_API_BASE_URL,
            "portal_base_url": settings.MPT_PORTAL_BASE_URL,
        },
    )


def test_send_email_notification_no_recipient(mocker, settings, order_factory, caplog):
    settings.EXTENSION_CONFIG = {
        "EMAIL_NOTIFICATIONS_ENABLED": "1",
    }
    mocked_mpt_client = mocker.MagicMock()
    mocker.patch(
        "adobe_vipm.flows.fulfillment.shared.get_notifications_recipient",
        return_value=None,
    )

    mocked_get_rendered_template = mocker.patch(
        "adobe_vipm.flows.fulfillment.shared.get_rendered_template",
    )

    mocked_send_email = mocker.patch("adobe_vipm.flows.fulfillment.shared.send_email")

    order = order_factory(order_id="ORD-1234")

    with caplog.at_level(logging.WARNING):
        send_email_notification(mocked_mpt_client, order)

    assert (
        "Cannot send email notifications "
        f"for order {order['id']}: no recipient found"
    ) in caplog.text

    mocked_get_rendered_template.assert_not_called()
    mocked_send_email.assert_not_called()


def test_start_processing_attempt_first_attempt(
    mocker, order_factory, fulfillment_parameters_factory
):
    order = order_factory()
    updated_order = order_factory(
        fulfillment_parameters=fulfillment_parameters_factory(
            retry_count="1",
        ),
    )
    mocked_send = mocker.patch(
        "adobe_vipm.flows.fulfillment.shared.send_email_notification"
    )
    mocked_update = mocker.patch(
        "adobe_vipm.flows.fulfillment.shared.update_order",
        return_value=updated_order,
    )

    mocked_client = mocker.MagicMock()

    start_processing_attempt(mocked_client, order)

    mocked_send.assert_called_once_with(mocked_client, updated_order)
    mocked_update.assert_called_once_with(
        mocked_client,
        updated_order["id"],
        parameters=updated_order["parameters"],
    )


def test_start_processing_attempt_other_attempts(
    mocker, order_factory, fulfillment_parameters_factory
):
    mocked_send = mocker.patch(
        "adobe_vipm.flows.fulfillment.shared.send_email_notification"
    )

    mocked_client = mocker.MagicMock()

    order = order_factory(
        fulfillment_parameters=fulfillment_parameters_factory(
            retry_count="1",
        )
    )

    start_processing_attempt(mocked_client, order)

    mocked_send.assert_not_called()


def test_set_customer_coterm_date_if_null(
    mocker, order_factory, adobe_customer_factory, fulfillment_parameters_factory
):
    mocked_mpt_client = mocker.MagicMock()
    mocked_adobe_client = mocker.MagicMock()
    customer = adobe_customer_factory()
    mocked_adobe_client.get_customer.return_value = customer
    mocked_update_order = mocker.patch(
        "adobe_vipm.flows.fulfillment.shared.update_order",
    )
    order = order_factory()
    order = set_customer_coterm_date_if_null(
        mocked_mpt_client, mocked_adobe_client, order
    )
    assert get_coterm_date(order) == customer["cotermDate"]
    mocked_update_order.assert_called_once_with(
        mocked_mpt_client,
        order["id"],
        parameters={
            "ordering": order["parameters"]["ordering"],
            "fulfillment": fulfillment_parameters_factory(
                coterm_date=customer["cotermDate"],
            ),
        },
    )


def test_set_customer_coterm_date_if_null_already_set(
    mocker, order_factory, fulfillment_parameters_factory
):
    mocked_mpt_client = mocker.MagicMock()
    mocked_adobe_client = mocker.MagicMock()
    mocked_update_order = mocker.patch(
        "adobe_vipm.flows.fulfillment.shared.update_order",
    )
    order = order_factory(
        fulfillment_parameters=fulfillment_parameters_factory(
            coterm_date="whatever"
        )
    )
    assert set_customer_coterm_date_if_null(
        mocked_mpt_client, mocked_adobe_client, order
    ) == order

    mocked_update_order.assert_not_called()
    mocked_adobe_client.get_customer_assert_not_called()


def test_update_order_actual_price(
    mocker,
    order_factory,
    fulfillment_parameters_factory,
    adobe_customer_factory,
    adobe_items_factory,
):
    mpt_client = mocker.MagicMock()
    adobe_client = mocker.MagicMock()
    adobe_client.get_customer.return_value = adobe_customer_factory()

    order = order_factory(
        fulfillment_parameters=fulfillment_parameters_factory(
            customer_id="a-customer-id",
        )
    )
    adobe_items = adobe_items_factory()
    mocked_update_order = mocker.patch(
        "adobe_vipm.flows.fulfillment.shared.update_order",
    )
    mocker.patch(
        "adobe_vipm.flows.fulfillment.shared.get_prices_for_skus",
        return_value={adobe_items[0]["offerId"]: 10.12},
    )

    update_order_actual_price(mpt_client, adobe_client, order, order["lines"], adobe_items)

    mocked_update_order.assert_called_once_with(
        mpt_client,
        order["id"],
        lines=[{'id': 'ALI-2119-4550-8674-5962-0001', 'price': {'unitPP': 10.12}}],
    )


def test_update_order_actual_price_3yc(
    mocker,
    order_factory,
    fulfillment_parameters_factory,
    lines_factory,
    adobe_customer_factory,
    adobe_commitment_factory,
    adobe_items_factory,
):
    mpt_client = mocker.MagicMock()
    adobe_client = mocker.MagicMock()
    adobe_client.get_customer.return_value = adobe_customer_factory(
        commitment=adobe_commitment_factory(),
    )

    order = order_factory(
        fulfillment_parameters=fulfillment_parameters_factory(
            customer_id="a-customer-id",
        ),
        lines=lines_factory() + lines_factory(line_id=2, item_id=2),
    )
    adobe_items = adobe_items_factory()
    mocked_update_order = mocker.patch(
        "adobe_vipm.flows.fulfillment.shared.update_order",
    )
    mocker.patch(
        "adobe_vipm.flows.fulfillment.shared.get_prices_for_3yc_skus",
        return_value={adobe_items[0]["offerId"]: 10.12},
    )

    update_order_actual_price(mpt_client, adobe_client, order, [order["lines"][0]], adobe_items)

    mocked_update_order.assert_called_once_with(
        mpt_client,
        order["id"],
        lines=[
            {'id': 'ALI-2119-4550-8674-5962-0001', 'price': {'unitPP': 10.12}},
            {'id': 'ALI-2119-4550-8674-5962-0002', 'price': {'unitPP': 1234.55}}
        ],
    )
