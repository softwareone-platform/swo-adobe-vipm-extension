import pytest

from adobe_vipm.flows.sync.agreement import AgreementsSyncer


@pytest.fixture
def mock_check_update_airtable_missing_deployments(mocker, mocked_agreement_syncer):
    return mocker.patch.object(
        AgreementsSyncer, "_check_update_airtable_missing_deployments", spec=True
    )


@pytest.fixture
def mock_process_orphaned_deployment_subscriptions(mocker, mocked_agreement_syncer):
    return mocker.patch.object(
        AgreementsSyncer, "_process_orphaned_deployment_subscriptions", spec=True
    )


@pytest.fixture
def mock_get_transfer_by_authorization_membership_or_customer(mocker, mocked_agreement_syncer):
    return mocker.patch(
        "adobe_vipm.airtable.models.get_transfer_by_authorization_membership_or_customer", spec=True
    )
