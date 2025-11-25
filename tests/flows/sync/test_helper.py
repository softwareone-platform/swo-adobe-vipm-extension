import pytest
from freezegun import freeze_time

from adobe_vipm.adobe import constants
from adobe_vipm.adobe.constants import THREE_YC_TEMP_3YC_STATUSES, AdobeStatus
from adobe_vipm.adobe.errors import AdobeAPIError, AuthorizationNotFoundError
from adobe_vipm.flows.errors import MPTAPIError
from adobe_vipm.flows.sync.helper import (
    get_customer_or_process_lost_customer,
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
    mock_mpt_client,
    agreement_factory,
    dry_run,
    mock_mpt_get_agreements_by_query,
    mock_sync_agreement,
    mock_agreement,
    mock_adobe_client,
):
    mock_mpt_get_agreements_by_query.return_value = [mock_agreement]

    sync_agreements_by_3yc_end_date(mock_mpt_client, mock_adobe_client, dry_run=dry_run)  # act

    mock_sync_agreement.assert_called_once_with(
        mock_mpt_client, mock_adobe_client, mock_agreement, dry_run=dry_run, sync_prices=True
    )
    mock_mpt_get_agreements_by_query.assert_called_once_with(
        mock_mpt_client,
        "eq(status,Active)&"
        "any(parameters.fulfillment,and(eq(externalId,3YCEndDate),eq(displayValue,2024-11-08)))&"
        "any(parameters.fulfillment,and(eq(externalId,lastSyncDate),ne(displayValue,2024-11-09)))&"
        "select=lines,parameters,assets,subscriptions,product,listing",
    )


@freeze_time("2025-06-16")
@pytest.mark.parametrize("dry_run", [True, False])
def test_sync_agreements_by_coterm_date(
    mocker,
    mock_mpt_client,
    agreement_factory,
    dry_run,
    mock_mpt_get_agreements_by_query,
    mock_sync_agreement,
    mock_agreement,
    mock_adobe_client,
):
    mock_mpt_get_agreements_by_query.return_value = [mock_agreement]

    sync_agreements_by_coterm_date(mock_mpt_client, mock_adobe_client, dry_run=dry_run)  # act

    mock_sync_agreement.assert_called_once_with(
        mock_mpt_client, mock_adobe_client, mock_agreement, dry_run=dry_run, sync_prices=True
    )
    mock_mpt_get_agreements_by_query.assert_called_once_with(
        mock_mpt_client,
        "eq(status,Active)&"
        "any(parameters.fulfillment,and(eq(externalId,cotermDate),eq(displayValue,2025-06-15)))&"
        "any(parameters.fulfillment,and(eq(externalId,lastSyncDate),ne(displayValue,2025-06-16)))&"
        "select=lines,parameters,assets,subscriptions,product,listing",
    )


@freeze_time("2025-07-16")
@pytest.mark.parametrize("dry_run", [True, False])
def test_sync_agreements_by_renewal_date(
    mock_mpt_client,
    agreement_factory,
    dry_run,
    mock_mpt_get_agreements_by_query,
    mock_sync_agreement,
    mock_adobe_client,
    mock_agreement,
):
    mock_mpt_get_agreements_by_query.return_value = [mock_agreement]

    sync_agreements_by_renewal_date(mock_mpt_client, mock_adobe_client, dry_run=dry_run)  # act

    mock_sync_agreement.assert_called_once_with(
        mock_mpt_client, mock_adobe_client, mock_agreement, dry_run=dry_run, sync_prices=True
    )
    mock_mpt_get_agreements_by_query.assert_called_once_with(
        mock_mpt_client,
        "eq(status,Active)&"
        "any(subscriptions,any(parameters.fulfillment,and(eq(externalId,renewalDate),in(displayValue,(2026-07-15,2026-06-15,2026-05-15,2026-04-15,2026-03-15,2026-02-15,2026-01-15,2025-12-15,2025-11-15,2025-10-15,2025-09-15,2025-08-15,2025-07-15,2025-06-15,2025-05-15,2025-04-15,2025-03-15,2025-02-15,2025-01-15,2024-12-15,2024-11-15,2024-10-15,2024-09-15,2024-08-15))))&"
        "any(parameters.fulfillment,and(eq(externalId,lastSyncDate),ne(displayValue,2025-07-16)))&"
        "select=lines,parameters,assets,subscriptions,product,listing",
    )


@pytest.mark.parametrize(
    "status",
    [
        constants.ThreeYearCommitmentStatus.ACCEPTED,
        constants.ThreeYearCommitmentStatus.REQUESTED,
    ],
)
def test_sync_agreements_by_3yc_enroll_status_status(
    mock_mpt_client,
    mock_adobe_client,
    adobe_customer_factory,
    adobe_commitment_factory,
    agreement_factory,
    status,
    mock_sync_agreement,
    mock_agreement,
    mock_get_agreements_by_3yc_commitment_request_invitation,
):
    mock_adobe_client.get_customer.return_value = adobe_customer_factory(
        commitment=adobe_commitment_factory(status=status)
    )

    sync_agreements_by_3yc_enroll_status(mock_mpt_client, mock_adobe_client, dry_run=False)  # act

    mock_get_agreements_by_3yc_commitment_request_invitation.assert_called_once_with(
        mock_mpt_client, THREE_YC_TEMP_3YC_STATUSES
    )
    mock_sync_agreement.assert_called_once_with(
        mock_mpt_client, mock_adobe_client, mock_agreement, dry_run=False, sync_prices=True
    )


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
    mock_mpt_update_agreement,
    mock_sync_agreement,
    mock_agreement,
    mock_get_agreements_by_3yc_commitment_request_invitation,
):
    mock_get_agreements_by_3yc_commitment_request_invitation.return_value = [mock_agreement]
    mock_adobe_client.get_customer.return_value = adobe_customer_factory(
        commitment=adobe_commitment_factory(status=status)
    )

    sync_agreements_by_3yc_enroll_status(mock_mpt_client, mock_adobe_client, dry_run=False)  # act

    mock_get_agreements_by_3yc_commitment_request_invitation.assert_called_once_with(
        mock_mpt_client, THREE_YC_TEMP_3YC_STATUSES
    )
    mock_mpt_update_agreement.assert_not_called()
    mock_sync_agreement.assert_called_once_with(
        mock_mpt_client, mock_adobe_client, mock_agreement, dry_run=False, sync_prices=True
    )


def test_sync_agreements_by_3yc_enroll_status_status_error(
    mocker,
    mock_mpt_client,
    mock_adobe_client,
    adobe_customer_factory,
    adobe_commitment_factory,
    agreement_factory,
    caplog,
    mock_sync_agreement,
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
    mock_sync_agreement.assert_not_called()


def test_sync_agreements_by_3yc_enroll_status_error_sync(
    mock_mpt_client,
    mock_adobe_client,
    adobe_customer_factory,
    adobe_commitment_factory,
    agreement_factory,
    caplog,
    mock_mpt_update_agreement,
    mock_sync_agreement,
    mock_agreement,
    mock_get_agreements_by_3yc_commitment_request_invitation,
):
    mock_get_agreements_by_3yc_commitment_request_invitation.return_value = [mock_agreement]
    mock_adobe_client.get_customer.return_value = adobe_customer_factory(
        commitment=adobe_commitment_factory(status=constants.ThreeYearCommitmentStatus.COMMITTED)
    )
    mock_sync_agreement.side_effect = AuthorizationNotFoundError(
        "Authorization with uk/id ID not found."
    )

    sync_agreements_by_3yc_enroll_status(mock_mpt_client, mock_adobe_client, dry_run=False)  # act

    mock_get_agreements_by_3yc_commitment_request_invitation.assert_called_once_with(
        mock_mpt_client, THREE_YC_TEMP_3YC_STATUSES
    )
    mock_mpt_update_agreement.assert_not_called()
    mock_sync_agreement.assert_called_once_with(
        mock_mpt_client, mock_adobe_client, mock_agreement, dry_run=False, sync_prices=True
    )
    assert "Authorization with uk/id ID not found." in caplog.text


def test_sync_agreements_by_3yc_enroll_status_error_sync_unkn(
    mocker,
    mock_mpt_client,
    mock_adobe_client,
    adobe_customer_factory,
    adobe_commitment_factory,
    agreement_factory,
    caplog,
    mock_mpt_update_agreement,
    mock_sync_agreement,
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
    mock_sync_agreement.side_effect = Exception(
        "Unknown exception getting agreements by 3YC enroll status"
    )

    sync_agreements_by_3yc_enroll_status(mock_mpt_client, mock_adobe_client, dry_run=False)  # act

    mock_get_agreements_by_3yc_commitment_request_invitation.assert_called_once_with(
        mock_mpt_client, THREE_YC_TEMP_3YC_STATUSES
    )
    mock_mpt_update_agreement.assert_not_called()
    mock_sync_agreement.assert_has_calls([
        mocker.call(
            mock_mpt_client, mock_adobe_client, mock_agreement, dry_run=False, sync_prices=True
        ),
        mocker.call(
            mock_mpt_client, mock_adobe_client, mock_agreement, dry_run=False, sync_prices=True
        ),
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
    mock_sync_agreement,
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
    )  # act

    mock_sync_agreement.assert_called_once_with(
        mock_mpt_client, mock_adobe_client, mock_agreement, dry_run=dry_run, sync_prices=False
    )


@pytest.mark.parametrize("dry_run", [True, False])
def test_sync_all_agreements(
    mocker,
    mock_mpt_client,
    agreement_factory,
    mock_sync_agreement,
    mock_adobe_client,
    mock_agreement,
    dry_run,
):
    mocker.patch("mpt_extension_sdk.mpt_http.mpt.get_all_agreements", return_value=[mock_agreement])

    sync_all_agreements(mock_mpt_client, mock_adobe_client, dry_run=dry_run)  # act

    mock_sync_agreement.assert_called_once_with(
        mock_mpt_client, mock_adobe_client, mock_agreement, dry_run=dry_run, sync_prices=False
    )


def test_get_customer_or_process_lost_customer(
    mock_mpt_client, mock_adobe_client, agreement, adobe_customer_factory
):
    mock_adobe_customer = adobe_customer_factory()
    mock_adobe_client.get_customer.return_value = mock_adobe_customer

    result = get_customer_or_process_lost_customer(
        mock_mpt_client, mock_adobe_client, agreement, "fake_customer_id", dry_run=False
    )

    assert result == mock_adobe_customer
    mock_adobe_client.get_customer.assert_called_once_with("AUT-4785-7184", "fake_customer_id")


def test_get_customer_or_process_lost_customer_error(
    mocker,
    mock_mpt_client,
    mock_adobe_client,
    mock_send_warning,
    mock_mpt_terminate_subscription,
    mock_get_agreements_by_customer_deployments,
    agreement,
    adobe_customer_factory,
):
    mock_adobe_client.get_customer.side_effect = [
        AdobeAPIError(400, {"code": AdobeStatus.INVALID_CUSTOMER, "message": "Test error"})
    ]
    mock_adobe_client.get_customer_deployments_active_status.return_value = [
        {
            "deploymentId": "deployment-id",
            "status": "1000",
            "companyProfile": {"address": {"country": "DE"}},
        }
    ]

    result = get_customer_or_process_lost_customer(
        mock_mpt_client, mock_adobe_client, agreement, "fake_customer_id", dry_run=False
    )

    assert result is None
    mock_adobe_client.get_customer.assert_called_once_with("AUT-4785-7184", "fake_customer_id")
    mock_send_warning.assert_called_once()
    mock_mpt_terminate_subscription.assert_has_calls([
        mocker.call(mock_mpt_client, "SUB-1000-2000-3000", "Suspected Lost Customer"),
        mocker.call(mock_mpt_client, "SUB-1000-2000-3000", "Suspected Lost Customer"),
    ])
    mock_get_agreements_by_customer_deployments.assert_called_once()


def test_get_customer_or_process_lost_customer_dry_run(
    mock_mpt_client,
    mock_adobe_client,
    mock_send_exception,
    mock_mpt_terminate_subscription,
    mock_get_agreements_by_customer_deployments,
    agreement,
    adobe_customer_factory,
):
    mock_adobe_client.get_customer.side_effect = [
        AdobeAPIError(400, {"code": AdobeStatus.INVALID_CUSTOMER, "message": "Test error"})
    ]
    mock_adobe_client.get_customer_deployments_active_status.return_value = [
        {
            "deploymentId": "deployment-id",
            "status": "1000",
            "companyProfile": {"address": {"country": "DE"}},
        }
    ]

    result = get_customer_or_process_lost_customer(
        mock_mpt_client, mock_adobe_client, agreement, "fake_customer_id", dry_run=True
    )

    assert result is None
    mock_adobe_client.get_customer.assert_called_once_with("AUT-4785-7184", "fake_customer_id")
    mock_send_exception.assert_not_called()
    mock_mpt_terminate_subscription.assert_not_called()
