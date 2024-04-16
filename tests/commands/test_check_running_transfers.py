from django.core.management import call_command


def test_check_running_transfers(mocker):
    mocked = mocker.patch("adobe_vipm.flows.migration.check_running_transfers")

    call_command("check_running_transfers")

    mocked.assert_called()
