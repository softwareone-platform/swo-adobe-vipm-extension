import pytest
from mpt_extension_sdk.mpt_http.mpt import get_agreements_by_query

from adobe_vipm.flows.sync.agreement import AgreementsSyncer


@pytest.fixture
def mock_get_agreements_by_query(mocker):
    mock = mocker.MagicMock(spec=get_agreements_by_query)
    mocker.patch("adobe_vipm.flows.mpt.get_agreements_by_query", new=mock)
    mocker.patch("mpt_extension_sdk.mpt_http.mpt.get_agreements_by_query", new=mock)
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
        "mpt_extension_sdk.mpt_http.mpt.get_agreements_by_customer_deployments",
        spec=True,
        return_value=deployment_agreements,
    )


@pytest.fixture
def mock_terminate_subscription(mocker):
    return mocker.patch("mpt_extension_sdk.mpt_http.mpt.terminate_subscription", spec=True)


@pytest.fixture
def mock_send_notification(mocker):
    mock = mocker.MagicMock(spec="adobe_vipm.notifications.send_notification")
    mocker.patch("adobe_vipm.flows.sync.helper.send_notification", new=mock)
    mocker.patch("adobe_vipm.flows.sync.agreement.send_notification", new=mock)
    mocker.patch("adobe_vipm.notifications.send_notification", new=mock)

    return mock


@pytest.fixture
def mock_get_adobe_client(mocker, mock_adobe_client):
    mock = mocker.MagicMock(
        return_value=mock_adobe_client, spec="adobe_vipm.adobe.client.get_adobe_client"
    )
    mocker.patch("adobe_vipm.flows.fulfillment.change.get_adobe_client", new=mock)

    return mock


@pytest.fixture
def mock_get_agreement_subscription(mocker, subscriptions_factory):
    return mocker.patch(
        "mpt_extension_sdk.mpt_http.mpt.get_agreement_subscription",
        return_value=subscriptions_factory()[0],
        spec=True,
    )


@pytest.fixture
def mock_update_agreement_subscription(mocker):
    return mocker.patch("mpt_extension_sdk.mpt_http.mpt.update_agreement_subscription", spec=True)


@pytest.fixture
def mock_send_exception(mocker):
    return mocker.patch("adobe_vipm.flows.sync.agreement.send_exception", spec=True)


@pytest.fixture
def mock_get_prices_for_skus(mocker):
    return mocker.patch("adobe_vipm.airtable.models.get_prices_for_skus", spec=True)


@pytest.fixture
def mock_sync_agreements_by_agreement_ids(mocker):
    mock = mocker.MagicMock(spec="adobe_vipm.flows.sync.helper.sync_agreements_by_agreement_ids")
    return mocker.patch(
        "adobe_vipm.flows.fulfillment.shared.sync_agreements_by_agreement_ids", new=mock
    )


@pytest.fixture
def mock_update_last_sync_date(mocker, mocked_agreement_syncer):
    return mocker.patch.object(mocked_agreement_syncer, "_update_last_sync_date", spec=True)


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


@pytest.fixture
def mock_airtable_base_info(mocker):
    return mocker.patch(
        "adobe_vipm.airtable.models.AirTableBaseInfo",
        spec=True,
    )


@pytest.fixture
def mock_get_gc_agreement_deployments_by_main_agreement(mocker):
    return mocker.patch(
        "adobe_vipm.airtable.models.get_gc_agreement_deployments_by_main_agreement",
        spec=True,
    )


@pytest.fixture
def mock_create_gc_agreement_deployments(mocker):
    return mocker.patch(
        "adobe_vipm.airtable.models.create_gc_agreement_deployments",
        spec=True,
    )


@pytest.fixture
def mock_get_gc_agreement_deployment_model(mocker):
    return mocker.patch(
        "adobe_vipm.airtable.models.get_gc_agreement_deployment_model",
        spec=True,
    )


@pytest.fixture
def mock_get_subscriptions_for_update(mocker, mocked_agreement_syncer):
    return mocker.patch.object(AgreementsSyncer, "_get_subscriptions_for_update", spec=True)


@pytest.fixture
def mock_update_subscriptions(mocker, mocked_agreement_syncer):
    return mocker.patch.object(AgreementsSyncer, "_update_subscriptions", spec=True)


@pytest.fixture
def mock_add_missing_subscriptions(mocker):
    return mocker.patch.object(AgreementsSyncer, "_add_missing_subscriptions", spec=True)


@pytest.fixture
def mock_check_update_airtable_missing_deployments(mocker, mocked_agreement_syncer):
    return mocker.patch.object(
        AgreementsSyncer, "_check_update_airtable_missing_deployments", spec=True
    )


@pytest.fixture
def mock_get_product_items_by_period(mocker):
    return mocker.patch("mpt_extension_sdk.mpt_http.mpt.get_product_items_by_period", spec=True)


@pytest.fixture
def mock_agreement(agreement_factory):
    return agreement_factory()


@pytest.fixture
def mock_sync_agreement(mocker):
    return mocker.patch("adobe_vipm.flows.sync.helper.sync_agreement", spec=True)


@pytest.fixture
def mocked_agreement_syncer(
    mock_mpt_client,
    mock_adobe_client,
    agreement_factory,
    adobe_customer_factory,
    adobe_subscription_factory,
):
    adobe_subscriptions = [
        adobe_subscription_factory(subscription_id="a-sub-id", offer_id="65327701CA01A12"),
        adobe_subscription_factory(
            subscription_id="55feb5038045e0b1ebf026e7522e17NA", offer_id="65304578CA01A12"
        ),
        adobe_subscription_factory(
            subscription_id="1e5b9c974c4ea1bcabdb0fe697a2f1NA", offer_id="65304578CA01A12"
        ),
    ]
    return AgreementsSyncer(
        mock_mpt_client,
        mock_adobe_client,
        agreement_factory(),
        adobe_customer_factory(),
        adobe_subscriptions,
    )


@pytest.fixture
def mock_notify_agreement_unhandled_exception_in_teams(mocker):
    return mocker.patch(
        "adobe_vipm.flows.sync.agreement.notify_agreement_unhandled_exception_in_teams", spec=True
    )


@pytest.fixture
def mock_update_asset(mocker):
    return mocker.patch("mpt_extension_sdk.mpt_http.mpt.update_asset", autospec=True)


@pytest.fixture
def mock_get_agreement(mocker, mock_agreement):
    return mocker.patch(
        "mpt_extension_sdk.mpt_http.mpt.get_agreement", return_value=mock_agreement, autospec=True
    )


@pytest.fixture
def mock_get_agreements_by_3yc_commitment_request_invitation(mocker, mock_agreement):
    return mocker.patch(
        "adobe_vipm.flows.sync.helper.get_agreements_by_3yc_commitment_request_invitation",
        return_value=[mock_agreement],
        autospec=True,
    )
