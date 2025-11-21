import pytest
from mpt_extension_sdk.mpt_http.mpt import get_agreements_by_query


@pytest.fixture()
def mock_get_agreements_by_query(mocker):
    mock = mocker.MagicMock(spec=get_agreements_by_query)
    mocker.patch("adobe_vipm.flows.mpt.get_agreements_by_query", new=mock)
    mocker.patch("adobe_vipm.flows.sync.get_agreements_by_query", new=mock)
    return mock


@pytest.fixture()
def mock_get_agreements_by_customer_deployments(
    agreement_factory, fulfillment_parameters_factory, mocker
):
    deployment_agreements = [
        agreement_factory(
            fulfillment_parameters=fulfillment_parameters_factory(
                global_customer="",
                deployment_id=f"deployment-{i}",
                deployments="",
            ),
        )
        for i in range(2)
    ]

    return mocker.patch(
        "adobe_vipm.flows.sync.get_agreements_by_customer_deployments",
        spec=True,
        return_value=deployment_agreements,
    )


@pytest.fixture()
def mock_terminate_subscription(mocker):
    return mocker.patch("adobe_vipm.flows.sync.terminate_subscription", spec=True)


@pytest.fixture()
def mock_send_notification(mocker):
    mock = mocker.MagicMock(spec="adobe_vipm.flows.sync.send_notification")
    mocker.patch("adobe_vipm.flows.sync.send_notification", new=mock)
    mocker.patch("adobe_vipm.notifications.send_notification", new=mock)

    return mock


@pytest.fixture()
def mock_get_adobe_client(mocker, mock_adobe_client):
    mock = mocker.MagicMock(
        return_value=mock_adobe_client, spec="adobe_vipm.adobe.client.get_adobe_client"
    )
    mocker.patch("adobe_vipm.flows.sync.get_adobe_client", new=mock)
    mocker.patch("adobe_vipm.flows.fulfillment.change.get_adobe_client", new=mock)

    return mock


@pytest.fixture()
def mock_get_agreement_subscription(mocker, subscriptions_factory):
    return mocker.patch(
        "adobe_vipm.flows.sync.get_agreement_subscription",
        return_value=subscriptions_factory()[0],
        spec=True,
    )


@pytest.fixture()
def mock_update_agreement_subscription(mocker):
    return mocker.patch("adobe_vipm.flows.sync.update_agreement_subscription", spec=True)


@pytest.fixture()
def mock_get_prices_for_skus(mocker):
    return mocker.patch("adobe_vipm.airtable.models.get_prices_for_skus", spec=True)


@pytest.fixture()
def mock_sync_agreements_by_agreement_ids(mocker):
    mock = mocker.MagicMock(spec="adobe_vipm.flows.sync.sync_agreements_by_agreement_ids")
    return mocker.patch(
        "adobe_vipm.flows.fulfillment.shared.sync_agreements_by_agreement_ids", new=mock
    )


@pytest.fixture()
def mock_get_customer_or_process_lost_customer(mocker):
    return mocker.patch(
        "adobe_vipm.flows.sync._get_customer_or_process_lost_customer", autospec=True
    )


@pytest.fixture()
def mock_update_last_sync_date(mocker):
    return mocker.patch("adobe_vipm.flows.sync._update_last_sync_date", spec=True)


@pytest.fixture()
def mock_switch_order_to_failed(mocker):
    return mocker.patch("adobe_vipm.flows.fulfillment.change.switch_order_to_failed", spec=True)


@pytest.fixture()
def mock_notify_not_updated_subscriptions(mocker):
    return mocker.patch(
        "adobe_vipm.flows.fulfillment.change.notify_not_updated_subscriptions", spec=True
    )


@pytest.fixture()
def mock_next_step(mocker):
    return mocker.MagicMock()


@pytest.fixture()
def mock_airtable_base_info(mocker):
    return mocker.patch(
        "adobe_vipm.airtable.models.AirTableBaseInfo",
        spec=True,
    )


@pytest.fixture()
def mock_get_gc_agreement_deployments_by_main_agreement(mocker):
    return mocker.patch(
        "adobe_vipm.airtable.models.get_gc_agreement_deployments_by_main_agreement",
        spec=True,
    )


@pytest.fixture()
def mock_create_gc_agreement_deployments(mocker):
    return mocker.patch(
        "adobe_vipm.airtable.models.create_gc_agreement_deployments",
        spec=True,
    )


@pytest.fixture()
def mock_get_gc_agreement_deployment_model(mocker):
    mock = mocker.MagicMock(name="GCAgreementDeployment")
    mocker.patch(
        "adobe_vipm.airtable.models.get_gc_agreement_deployment_model", return_value=mock, spec=True
    )
    return mock


@pytest.fixture()
def mock_get_subscriptions_for_update(mocker):
    return mocker.patch(
        "adobe_vipm.flows.sync._get_subscriptions_for_update",
        spec=True,
    )


@pytest.fixture()
def mock_sync_deployment_agreements(mocker):
    return mocker.patch(
        "adobe_vipm.flows.sync.sync_deployment_agreements",
        spec=True,
    )


@pytest.fixture()
def mock_update_subscriptions(mocker):
    return mocker.patch(
        "adobe_vipm.flows.sync._update_subscriptions",
        spec=True,
    )


@pytest.fixture()
def mock_get_product_items_by_period(mocker):
    return mocker.patch(
        "adobe_vipm.flows.sync.get_product_items_by_period",
        spec=True,
    )

@pytest.fixture()
def mock_check_update_airtable_missing_deployments(mocker):
    return mocker.patch(
        "adobe_vipm.flows.sync._check_update_airtable_missing_deployments", spec=True
    )


@pytest.fixture()
def mock_process_orphaned_deployment_subscriptions(mocker):
    return mocker.patch(
        "adobe_vipm.flows.sync._process_orphaned_deployment_subscriptions", spec=True
    )


@pytest.fixture()
def mock_get_transfer_by_authorization_membership_or_customer(mocker):
    return mocker.patch(
        "adobe_vipm.airtable.models.get_transfer_by_authorization_membership_or_customer", spec=True
    )


@pytest.fixture()
def mock_process_main_agreement(mocker):
    return mocker.patch("adobe_vipm.flows.sync._process_main_agreement", spec=True)


@pytest.fixture()
def mock_notify_agreement_unhandled_exception_in_teams(mocker):
    return mocker.patch(
        "adobe_vipm.flows.sync.notify_agreement_unhandled_exception_in_teams", spec=True
    )
