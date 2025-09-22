import pytest
from django.core.management import call_command


@pytest.mark.usefixtures("mock_setup_client")
def test_process_sync_agreements(mocker, mock_mpt_client):
    mock_sync_agreements_by_3yc_enroll_status = mocker.patch(
        "adobe_vipm.management.commands.sync_3yc_enrol.sync_agreements_by_3yc_enroll_status"
    )

    call_command("sync_3yc_enrol")

    mock_sync_agreements_by_3yc_enroll_status.assert_called_once_with(
        mock_mpt_client,
        dry_run=False,
    )
