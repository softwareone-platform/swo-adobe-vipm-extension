from django.core.management import call_command


def test_process_sync_agreements(mocker):
    mocked_client = mocker.MagicMock()
    mocker.patch(
        "adobe_vipm.management.commands.sync_agreements.setup_client",
        return_value=mocked_client,
    )
    mocked = mocker.patch("adobe_vipm.management.commands.sync_agreements.sync_prices")

    call_command("sync_agreements")

    mocked.assert_called_once_with(mocked_client)
