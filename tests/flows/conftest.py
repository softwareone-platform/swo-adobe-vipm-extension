import pytest
from mpt_extension_sdk.mpt_http.mpt import get_agreements_by_query


@pytest.fixture
def mock_get_agreements_by_query(mocker):
    mock = mocker.MagicMock(spec=get_agreements_by_query)
    mocker.patch("adobe_vipm.flows.mpt.get_agreements_by_query", new=mock)
    mocker.patch("adobe_vipm.flows.sync.get_agreements_by_query", new=mock)
    return mock


@pytest.fixture
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


@pytest.fixture
def mock_terminate_subscription(mocker):
    return mocker.patch("adobe_vipm.flows.sync.terminate_subscription", spec=True)


@pytest.fixture
def mock_notify_processing_lost_customer(mocker):
    return mocker.patch("adobe_vipm.notifications.send_notification", spec=True)


@pytest.fixture
def mock_get_adobe_client(mocker, mock_adobe_client):
    mock = mocker.MagicMock(
        return_value=mock_adobe_client, spec="adobe_vipm.adobe.client.get_adobe_client"
    )
    mocker.patch("adobe_vipm.flows.sync.get_adobe_client", new=mock)
    mocker.patch("adobe_vipm.flows.fulfillment.change.get_adobe_client", new=mock)

    return mock


@pytest.fixture
def mock_get_agreement_subscription(mocker, subscriptions_factory):
    return mocker.patch(
        "adobe_vipm.flows.sync.get_agreement_subscription",
        return_value=subscriptions_factory()[0],
        spec=True,
    )


@pytest.fixture
def mock_update_agreement_subscription(mocker):
    return mocker.patch("adobe_vipm.flows.sync.update_agreement_subscription", spec=True)


@pytest.fixture
def mock_send_exception(mocker):
    return mocker.patch("adobe_vipm.flows.sync.send_exception", spec=True)


@pytest.fixture
def mock_get_prices_for_skus(mocker):
    return mocker.patch("adobe_vipm.airtable.models.get_prices_for_skus", spec=True)


@pytest.fixture
def mock_sync_agreements_by_agreement_ids(mocker):
    mock = mocker.MagicMock(spec="adobe_vipm.flows.sync.sync_agreements_by_agreement_ids")
    return mocker.patch(
        "adobe_vipm.flows.fulfillment.shared.sync_agreements_by_agreement_ids", new=mock
    )


@pytest.fixture
def mock_get_customer_or_process_lost_customer(mocker):
    return mocker.patch(
        "adobe_vipm.flows.sync._get_customer_or_process_lost_customer", autospec=True
    )


@pytest.fixture
def mock_update_last_sync_date(mocker):
    return mocker.patch("adobe_vipm.flows.sync._update_last_sync_date", spec=True)


@pytest.fixture
def mock_switch_order_to_failed(mocker):
    return mocker.patch("adobe_vipm.flows.fulfillment.change.switch_order_to_failed", spec=True)


@pytest.fixture
def mock_notify_not_updated_subscriptions(mocker):
    return mocker.patch(
        "adobe_vipm.flows.fulfillment.change.notify_not_updated_subscriptions", spec=True
    )


@pytest.fixture
def mock_next_step(mocker):
    return mocker.MagicMock()
