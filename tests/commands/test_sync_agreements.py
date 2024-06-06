import pytest
from django.core.management import call_command


def test_process_sync_agreements(mocker):
    mocked_client = mocker.MagicMock()
    mocker.patch(
        "adobe_vipm.management.commands.sync_agreements.setup_client",
        return_value=mocked_client,
    )
    mocked = mocker.patch(
        "adobe_vipm.management.commands.sync_agreements.sync_agreements_by_next_sync"
    )

    call_command("sync_agreements")

    mocked.assert_called_once_with(mocked_client)


@pytest.mark.parametrize("allow_3yc", [True, False])
def test_process_by_agreement_ids(mocker, allow_3yc):
    mocked_client = mocker.MagicMock()
    mocker.patch(
        "adobe_vipm.management.commands.sync_agreements.setup_client",
        return_value=mocked_client,
    )
    mocked = mocker.patch(
        "adobe_vipm.management.commands.sync_agreements.sync_agreements_by_agreement_ids"
    )

    call_command(
        "sync_agreements",
        agreements=["AGR-0001", "AGR-0002"],
        allow_3yc=allow_3yc,
    )

    mocked.assert_called_once_with(mocked_client, ["AGR-0001", "AGR-0002"], allow_3yc)
