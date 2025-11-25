from django.core.management import call_command


def test_process_transfers(mocker):
    mocked = mocker.patch("adobe_vipm.flows.migration.process_transfers")

    call_command("process_transfers")  # act

    mocked.assert_called()
