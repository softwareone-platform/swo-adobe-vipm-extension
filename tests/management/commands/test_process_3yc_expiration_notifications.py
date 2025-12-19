from django.core.management import call_command


def test_process_3yc_expiration_notifications(mocker, mock_setup_client):
    mocker.patch(
        "adobe_vipm.management.commands.process_3yc_expiration_notifications.get_agreements_by_query",
        autospec=True,
        return_value=[{"id": "123", "licensee": {"id": "456"}, "buyer": {"id": "789"}}],
    )
    mocked_send_3yc_expiration_notification = mocker.patch(
        "adobe_vipm.management.commands.process_3yc_expiration_notifications.send_3yc_expiration_notification",
        autospec=True,
    )

    call_command("process_3yc_expiration_notifications", number_of_days=30)  # act

    mocked_send_3yc_expiration_notification.assert_called_once_with(
        mock_setup_client,
        {"id": "123", "licensee": {"id": "456"}, "buyer": {"id": "789"}},
        30,
        "notification_3yc_expiring",
    )
