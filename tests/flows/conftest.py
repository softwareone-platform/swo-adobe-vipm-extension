import pytest
from mpt_extension_sdk.mpt_http.mpt import get_agreements_by_query

from adobe_vipm.adobe.constants import AdobeStatus
from adobe_vipm.flows.sync.agreement import AgreementSyncer
from adobe_vipm.flows.sync.price_manager import PriceManager
from adobe_vipm.flows.sync.subscription import SubscriptionSyncer


@pytest.fixture
def mock_mpt_get_agreements_by_query(mocker):
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
def mock_mpt_terminate_subscription(mocker):
    return mocker.patch("mpt_extension_sdk.mpt_http.mpt.terminate_subscription", spec=True)


@pytest.fixture
def mock_mpt_get_agreement_subscription(mocker, subscriptions_factory):
    return mocker.patch(
        "mpt_extension_sdk.mpt_http.mpt.get_agreement_subscription",
        return_value=subscriptions_factory()[0],
        spec=True,
    )


@pytest.fixture
def mock_mpt_get_item_prices_by_pricelist_id(mocker):
    return mocker.patch("mpt_extension_sdk.mpt_http.mpt.get_item_prices_by_pricelist_id", spec=True)


@pytest.fixture
def mock_mpt_update_agreement_subscription(mocker):
    return mocker.patch("mpt_extension_sdk.mpt_http.mpt.update_agreement_subscription", spec=True)


@pytest.fixture
def mock_get_prices_for_skus(mocker):
    return mocker.patch("adobe_vipm.airtable.models.get_prices_for_skus", spec=True)


@pytest.fixture
def mock_sync_agreements_by_agreement_ids(mocker):
    mock = mocker.MagicMock(spec="adobe_vipm.flows.sync.agreement.sync_agreements_by_agreement_ids")
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
    mock = mocker.MagicMock(name="GCAgreementDeployment")
    mocker.patch(
        "adobe_vipm.airtable.models.get_gc_agreement_deployment_model", return_value=mock, spec=True
    )
    return mock


@pytest.fixture
def mock_get_subscriptions_for_update(mocker, mocked_agreement_syncer):
    return mocker.patch.object(AgreementSyncer, "_get_subscriptions_for_update", spec=True)


@pytest.fixture
def mock_update_subscriptions(mocker, mocked_agreement_syncer):
    return mocker.patch.object(SubscriptionSyncer, "sync", spec=True)


@pytest.fixture
def mock_add_missing_subscriptions_and_assets(mocker):
    return mocker.patch.object(AgreementSyncer, "_add_missing_subscriptions_and_assets", spec=True)


@pytest.fixture
def mock_check_update_airtable_missing_deployments(mocker, mocked_agreement_syncer):
    return mocker.patch.object(
        AgreementSyncer, "_check_update_airtable_missing_deployments", spec=True
    )


@pytest.fixture
def mock_get_product_items_by_period(mocker):
    return mocker.patch("mpt_extension_sdk.mpt_http.mpt.get_product_items_by_period", spec=True)


@pytest.fixture
def mock_agreement(agreement_factory):
    return agreement_factory()


@pytest.fixture
def mock_sync_agreement(mocker):
    return mocker.patch("adobe_vipm.flows.sync.agreement.sync_agreement", spec=True)


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
            subscription_id="55feb5038045e0b1ebf026e7522e17NA",
            offer_id="65304578CA01A12",
            status=AdobeStatus.SUBSCRIPTION_TERMINATED,
        ),
        adobe_subscription_factory(
            subscription_id="1e5b9c974c4ea1bcabdb0fe697a2f1NA", offer_id="65304578CA01A12"
        ),
    ]
    return AgreementSyncer(
        mock_mpt_client,
        mock_adobe_client,
        agreement_factory(),
        adobe_customer_factory(),
        adobe_subscriptions,
        dry_run=False,
    )


@pytest.fixture
def mock_notify_agreement_unhandled_exception_in_teams(mocker):
    return mocker.patch(
        "adobe_vipm.flows.utils.notification.notify_agreement_unhandled_exception_in_teams",
        spec=True,
    )


@pytest.fixture
def mock_mpt_update_asset(mocker):
    return mocker.patch("mpt_extension_sdk.mpt_http.mpt.update_asset", autospec=True)


@pytest.fixture
def mock_get_agreement(mocker, mock_agreement):
    return mocker.patch(
        "mpt_extension_sdk.mpt_http.mpt.get_agreement", return_value=mock_agreement, autospec=True
    )


@pytest.fixture
def mock_get_agreements_by_3yc_commitment_request_invitation(mocker, mock_agreement):
    return mocker.patch(
        "adobe_vipm.flows.sync.agreement.get_agreements_by_3yc_commitment_request_invitation",
        return_value=[mock_agreement],
        autospec=True,
    )


@pytest.fixture
def mock_mpt_get_asset_template_by_name(mocker):
    return mocker.patch("mpt_extension_sdk.mpt_http.mpt.get_asset_template_by_name", spec=True)


@pytest.fixture
def mock_mpt_create_asset(mocker):
    return mocker.patch("mpt_extension_sdk.mpt_http.mpt.create_asset", spec=True)


@pytest.fixture
def mock_mpt_create_agreement_subscription(mocker):
    return mocker.patch("mpt_extension_sdk.mpt_http.mpt.create_agreement_subscription", spec=True)


@pytest.fixture
def mock_mpt_get_template_by_name(mocker):
    return mocker.patch("mpt_extension_sdk.mpt_http.mpt.get_template_by_name", spec=True)


@pytest.fixture
def mock_notify_missing_prices(mocker):
    return mocker.patch("adobe_vipm.flows.utils.notify_missing_prices", spec=True)


@pytest.fixture
def mock_notify_missing_discount_levels(mocker):
    return mocker.patch(
        "adobe_vipm.flows.utils.subscription.notify_discount_level_error", spec=True
    )


@pytest.fixture
def mock_get_template_data_by_adobe_subscription(mocker):
    mock = mocker.MagicMock(
        spec="adobe_vipm.flows.utils.template.get_template_data_by_adobe_subscription"
    )
    for path in (
        "adobe_vipm.flows.sync.agreement.get_template_data_by_adobe_subscription",
        "adobe_vipm.flows.sync.subscription.get_template_data_by_adobe_subscription",
        "adobe_vipm.flows.fulfillment.shared.get_template_data_by_adobe_subscription",
    ):
        mocker.patch(path, new=mock)
    return mock


@pytest.fixture
def mock_get_sku_price(mocker):
    return mocker.patch("adobe_vipm.flows.sync.price_manager.models.get_sku_price", spec=True)


@pytest.fixture
def price_manager_factory(mocker):
    def _factory(
        mpt_client=None,
        adobe_customer=None,
        lines=None,
        agreement_id="AGR-1234-5678",
        pricelist_id="PRC-1234-5678",
    ):
        mpt_client = mpt_client or mocker.MagicMock()
        adobe_customer = adobe_customer or {"customerId": "test-customer-id"}
        lines = lines or []
        return PriceManager(
            mpt_client=mpt_client,
            adobe_customer=adobe_customer,
            lines=lines,
            agreement_id=agreement_id,
            pricelist_id=pricelist_id,
        )

    return _factory
