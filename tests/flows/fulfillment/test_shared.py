import logging

import pytest

from adobe_vipm.flows.fulfillment.shared import send_email_notification
from adobe_vipm.flows.utils import get_notifications_recipient


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
    ]
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
        status.lower(),
        {
            "order": order,
            "template": "rendered-template",
            "api_base_url": settings.MPT_API_BASE_URL,
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
