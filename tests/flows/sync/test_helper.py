import pytest
from freezegun import freeze_time

from adobe_vipm.adobe import constants
from adobe_vipm.adobe.constants import THREE_YC_TEMP_3YC_STATUSES
from adobe_vipm.adobe.errors import AuthorizationNotFoundError
from adobe_vipm.flows.errors import MPTAPIError
from adobe_vipm.flows.sync.helper import (
    sync_agreements_by_3yc_end_date,
    sync_agreements_by_3yc_enroll_status,
    sync_agreements_by_agreement_ids,
    sync_agreements_by_coterm_date,
    sync_agreements_by_renewal_date,
    sync_all_agreements,
)


@freeze_time("2024-11-09")
@pytest.mark.parametrize("dry_run", [True, False])
def test_sync_agreements_by_3yc_end_date(
    mocker,
    mock_mpt_client,
    agreement_factory,
    dry_run,
    mock_get_agreements_by_query,
    mock_agreement_syncer,
    mock_agreement,
    mock_adobe_client,
):
    mock_get_agreements_by_query.return_value = [mock_agreement]

    sync_agreements_by_3yc_end_date(mock_mpt_client, mock_adobe_client, dry_run=dry_run)

    mock_agreement_syncer.assert_called_once_with(
        mock_mpt_client, mock_adobe_client, mock_agreement
    )
    mock_agreement_syncer.return_value.sync.assert_called_once_with(
        dry_run=dry_run, sync_prices=True
    )
    mock_get_agreements_by_query.assert_called_once_with(
        mock_mpt_client,
        "eq(status,Active)&"
        "any(parameters.fulfillment,and(eq(externalId,3YCEndDate),eq(displayValue,2024-11-08)))&"
        "any(parameters.fulfillment,and(eq(externalId,lastSyncDate),ne(displayValue,2024-11-09)))&"
        "select=lines,parameters,subscriptions,product,listing",
    )


@freeze_time("2025-06-16")
@pytest.mark.parametrize("dry_run", [True, False])
def test_sync_agreements_by_coterm_date(
    mocker,
    mock_mpt_client,
    agreement_factory,
    dry_run,
    mock_get_agreements_by_query,
    mock_agreement_syncer,
    mock_agreement,
    mock_adobe_client,
):
    mock_get_agreements_by_query.return_value = [mock_agreement]

    sync_agreements_by_coterm_date(mock_mpt_client, mock_adobe_client, dry_run=dry_run)

    mock_agreement_syncer.assert_called_once_with(
        mock_mpt_client, mock_adobe_client, mock_agreement
    )
    mock_agreement_syncer.return_value.sync.assert_called_once_with(
        dry_run=dry_run, sync_prices=True
    )
    mock_get_agreements_by_query.assert_called_once_with(
        mock_mpt_client,
        "eq(status,Active)&"
        "any(parameters.fulfillment,and(eq(externalId,cotermDate),eq(displayValue,2025-06-15)))&"
        "any(parameters.fulfillment,and(eq(externalId,lastSyncDate),ne(displayValue,2025-06-16)))&"
        "select=lines,parameters,subscriptions,product,listing",
    )


@freeze_time("2025-07-16")
@pytest.mark.parametrize("dry_run", [True, False])
def test_sync_agreements_by_renewal_date(
    mocker,
    mock_mpt_client,
    agreement_factory,
    dry_run,
    mock_get_agreements_by_query,
    mock_agreement_syncer,
    mock_adobe_client,
    mock_agreement,
):
    mock_get_agreements_by_query.return_value = [mock_agreement]

    sync_agreements_by_renewal_date(mock_mpt_client, mock_adobe_client, dry_run=dry_run)

    mock_agreement_syncer.assert_called_once_with(
        mock_mpt_client, mock_adobe_client, mock_agreement
    )
    mock_agreement_syncer.return_value.sync.assert_called_once_with(
        dry_run=dry_run, sync_prices=True
    )
    mock_get_agreements_by_query.assert_called_once_with(
        mock_mpt_client,
        "eq(status,Active)&"
        "any(subscriptions,any(parameters.fulfillment,and(eq(externalId,renewalDate),in(displayValue,(2026-07-15,2026-06-15,2026-05-15,2026-04-15,2026-03-15,2026-02-15,2026-01-15,2025-12-15,2025-11-15,2025-10-15,2025-09-15,2025-08-15,2025-07-15,2025-06-15,2025-05-15,2025-04-15,2025-03-15,2025-02-15,2025-01-15,2024-12-15,2024-11-15,2024-10-15,2024-09-15,2024-08-15))))&"
        "any(parameters.fulfillment,and(eq(externalId,lastSyncDate),ne(displayValue,2025-07-16)))&"
        "select=lines,parameters,subscriptions,product,listing",
    )


@pytest.mark.parametrize(
    "status",
    [
        constants.ThreeYearCommitmentStatus.ACCEPTED,
        constants.ThreeYearCommitmentStatus.REQUESTED,
    ],
)
def test_sync_agreements_by_3yc_enroll_status_status(
    mocker,
    mock_mpt_client,
    mock_adobe_client,
    adobe_customer_factory,
    adobe_commitment_factory,
    agreement_factory,
    status,
    mock_agreement_syncer,
    mock_agreement,
    mock_get_agreements_by_3yc_commitment_request_invitation,
):
    mock_adobe_client.get_customer.return_value = adobe_customer_factory(
        commitment=adobe_commitment_factory(status=status)
    )

    sync_agreements_by_3yc_enroll_status(mock_mpt_client, mock_adobe_client, dry_run=False)

    mock_get_agreements_by_3yc_commitment_request_invitation.assert_called_once_with(
        mock_mpt_client, THREE_YC_TEMP_3YC_STATUSES
    )
    mock_agreement_syncer.assert_called_once_with(
        mock_mpt_client, mock_adobe_client, mock_agreement
    )
    mock_agreement_syncer.return_value.sync.assert_called_once_with(dry_run=False, sync_prices=True)


@pytest.mark.parametrize(
    "status",
    [
        constants.ThreeYearCommitmentStatus.COMMITTED,
        constants.ThreeYearCommitmentStatus.ACTIVE,
        constants.ThreeYearCommitmentStatus.DECLINED,
        constants.ThreeYearCommitmentStatus.NONCOMPLIANT,
        constants.ThreeYearCommitmentStatus.EXPIRED,
    ],
)
def test_sync_agreements_by_3yc_enroll_status_full(
    mocker,
    mock_mpt_client,
    mock_adobe_client,
    adobe_customer_factory,
    adobe_commitment_factory,
    agreement_factory,
    status,
    mock_update_agreement,
    mock_agreement_syncer,
    mock_agreement,
    mock_get_agreements_by_3yc_commitment_request_invitation,
):
    mock_get_agreements_by_3yc_commitment_request_invitation.return_value = [mock_agreement]
    mock_adobe_client.get_customer.return_value = adobe_customer_factory(
        commitment=adobe_commitment_factory(status=status)
    )

    sync_agreements_by_3yc_enroll_status(mock_mpt_client, mock_adobe_client, dry_run=False)

    mock_get_agreements_by_3yc_commitment_request_invitation.assert_called_once_with(
        mock_mpt_client, THREE_YC_TEMP_3YC_STATUSES
    )
    mock_update_agreement.assert_not_called()
    mock_agreement_syncer.assert_called_once_with(
        mock_mpt_client, mock_adobe_client, mock_agreement
    )
    mock_agreement_syncer.return_value.sync.assert_called_once_with(dry_run=False, sync_prices=True)


def test_sync_agreements_by_3yc_enroll_status_status_error(
    mocker,
    mock_mpt_client,
    mock_adobe_client,
    adobe_customer_factory,
    adobe_commitment_factory,
    agreement_factory,
    caplog,
    mock_agreement_syncer,
):
    mocker.patch(
        "adobe_vipm.flows.sync.helper.get_agreements_by_3yc_commitment_request_invitation",
        side_effect=MPTAPIError(400, {"rql_validation": ["Value has to be a non empty array."]}),
        autospec=True,
    )
    mock_adobe_client.get_customer.return_value = adobe_customer_factory(
        commitment=adobe_commitment_factory(status=constants.ThreeYearCommitmentStatus.EXPIRED)
    )

    with pytest.raises(MPTAPIError):
        sync_agreements_by_3yc_enroll_status(mock_mpt_client, mock_adobe_client, dry_run=False)

    assert "Unknown exception getting agreements by 3YC enroll status" in caplog.text
    mock_agreement_syncer.assert_not_called()


def test_sync_agreements_by_3yc_enroll_status_error_sync(
    mocker,
    mock_mpt_client,
    mock_adobe_client,
    adobe_customer_factory,
    adobe_commitment_factory,
    agreement_factory,
    caplog,
    mock_update_agreement,
    mock_agreement_syncer,
    mock_agreement,
    mock_get_agreements_by_3yc_commitment_request_invitation,
):
    mock_get_agreements_by_3yc_commitment_request_invitation.return_value = [mock_agreement]
    mock_adobe_client.get_customer.return_value = adobe_customer_factory(
        commitment=adobe_commitment_factory(status=constants.ThreeYearCommitmentStatus.COMMITTED)
    )
    mock_agreement_syncer.return_value.sync.side_effect = AuthorizationNotFoundError(
        "Authorization with uk/id ID not found."
    )

    sync_agreements_by_3yc_enroll_status(mock_mpt_client, mock_adobe_client, dry_run=False)

    mock_get_agreements_by_3yc_commitment_request_invitation.assert_called_once_with(
        mock_mpt_client, THREE_YC_TEMP_3YC_STATUSES
    )
    mock_update_agreement.assert_not_called()
    mock_agreement_syncer.assert_called_once_with(
        mock_mpt_client, mock_adobe_client, mock_agreement
    )
    mock_agreement_syncer.return_value.sync.assert_called_once_with(dry_run=False, sync_prices=True)
    assert "Authorization with uk/id ID not found." in caplog.text


def test_sync_agreements_by_3yc_enroll_status_error_sync_unkn(
    mocker,
    mock_mpt_client,
    mock_adobe_client,
    adobe_customer_factory,
    adobe_commitment_factory,
    agreement_factory,
    caplog,
    mock_update_agreement,
    mock_agreement_syncer,
    mock_agreement,
    mock_get_agreements_by_3yc_commitment_request_invitation,
):
    mock_get_agreements_by_3yc_commitment_request_invitation.return_value = [
        mock_agreement,
        mock_agreement,
    ]
    mock_adobe_client.get_customer.return_value = adobe_customer_factory(
        commitment=adobe_commitment_factory(status=constants.ThreeYearCommitmentStatus.COMMITTED)
    )
    mock_agreement_syncer.return_value.sync.side_effect = Exception(
        "Unknown exception getting agreements by 3YC enroll status"
    )

    sync_agreements_by_3yc_enroll_status(mock_mpt_client, mock_adobe_client, dry_run=False)

    mock_get_agreements_by_3yc_commitment_request_invitation.assert_called_once_with(
        mock_mpt_client, THREE_YC_TEMP_3YC_STATUSES
    )
    mock_update_agreement.assert_not_called()
    mock_agreement_syncer.assert_has_calls([
        mocker.call(mock_mpt_client, mock_adobe_client, mock_agreement),
        mocker.call().sync(dry_run=False, sync_prices=True),
        mocker.call(mock_mpt_client, mock_adobe_client, mock_agreement),
        mocker.call().sync(dry_run=False, sync_prices=True),
    ])
    assert (
        "Unknown exception synchronizing 3YC enroll status for agreement AGR-2119-4550-8674-5962"
        in caplog.text
    )
    assert caplog.messages == [
        "Unknown exception synchronizing 3YC enroll status for agreement AGR-2119-4550-8674-5962",
        "Unknown exception synchronizing 3YC enroll status for agreement AGR-2119-4550-8674-5962",
    ]


@pytest.mark.parametrize("dry_run", [True, False])
def test_sync_agreements_by_agreement_ids(
    mocker,
    mock_mpt_client,
    agreement_factory,
    dry_run,
    mock_agreement_syncer,
    mock_agreement,
    mock_adobe_client,
):
    mocker.patch(
        "mpt_extension_sdk.mpt_http.mpt.get_agreements_by_ids", return_value=[mock_agreement]
    )

    sync_agreements_by_agreement_ids(
        mock_mpt_client,
        mock_adobe_client,
        [mock_agreement["id"]],
        dry_run=dry_run,
        sync_prices=False,
    )

    mock_agreement_syncer.assert_called_once_with(
        mock_mpt_client, mock_adobe_client, mock_agreement
    )
    mock_agreement_syncer.return_value.sync.assert_called_once_with(
        dry_run=dry_run, sync_prices=False
    )


@pytest.mark.parametrize("dry_run", [True, False])
def test_sync_all_agreements(
    mocker,
    mock_mpt_client,
    agreement_factory,
    mock_agreement_syncer,
    mock_adobe_client,
    mock_agreement,
    dry_run,
):
    mocker.patch("mpt_extension_sdk.mpt_http.mpt.get_all_agreements", return_value=[mock_agreement])

    sync_all_agreements(mock_mpt_client, mock_adobe_client, dry_run=dry_run)

    mock_agreement_syncer.assert_called_once_with(
        mock_mpt_client, mock_adobe_client, mock_agreement
    )
    mock_agreement_syncer.return_value.sync.assert_called_once_with(
        dry_run=dry_run, sync_prices=False
    )
