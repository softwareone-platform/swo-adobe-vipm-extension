from unittest.mock import DEFAULT

import pytest
from django.core.management import call_command


@pytest.mark.parametrize("dry_run", [True, False])
def test_process_sync_agreements(mocker, dry_run, mock_mpt_client):
    mocker.patch(
        "adobe_vipm.management.commands.sync_agreements.setup_client",
        return_value=mock_mpt_client,
        spec=True,
    )
    mocked = mocker.patch.multiple(
        "adobe_vipm.management.commands.sync_agreements",
        sync_agreements_by_3yc_end_date=DEFAULT,
        sync_agreements_by_coterm_date=DEFAULT,
        sync_agreements_by_renewal_date=DEFAULT,
        spec=True,
    )

    call_command("sync_agreements", dry_run=dry_run)

    for v in mocked.values():
        v.assert_called_once_with(mock_mpt_client, dry_run)


@pytest.mark.parametrize("dry_run", [True, False])
def test_process_by_agreement_ids(mocker, dry_run):
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
        dry_run=dry_run,
    )

    mocked.assert_called_once_with(mocked_client, ["AGR-0001", "AGR-0002"], dry_run)


@pytest.mark.parametrize("dry_run", [True, False])
def test_process_all(mocker, dry_run):
    mocked_client = mocker.MagicMock()
    mocker.patch(
        "adobe_vipm.management.commands.sync_agreements.setup_client",
        return_value=mocked_client,
    )
    mocked = mocker.patch("adobe_vipm.management.commands.sync_agreements.sync_all_agreements")

    call_command(
        "sync_agreements",
        all=True,
        dry_run=dry_run,
    )

    mocked.assert_called_once_with(mocked_client, dry_run)
