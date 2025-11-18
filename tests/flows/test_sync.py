import logging

import pytest
from freezegun import freeze_time

from adobe_vipm.adobe import constants
from adobe_vipm.adobe.constants import THREE_YC_TEMP_3YC_STATUSES, AdobeStatus
from adobe_vipm.adobe.errors import AdobeAPIError, AuthorizationNotFoundError
from adobe_vipm.airtable.models import AirTableBaseInfo, get_gc_agreement_deployment_model
from adobe_vipm.flows.constants import (
    TEMPLATE_ASSET_DEFAULT,
    AgreementStatus,
    ItemTermsModel,
    Param,
    TeamsColorCode,
)
from adobe_vipm.flows.errors import MPTAPIError
from adobe_vipm.flows.sync import (
    _add_missing_subscriptions,  # noqa: PLC2701
    _check_update_airtable_missing_deployments,  # noqa: PLC2701
    _get_subscriptions_for_update,  # noqa: PLC2701
    _process_orphaned_deployment_subscriptions,  # noqa: PLC2701
    sync_agreement,
    sync_agreements_by_3yc_end_date,
    sync_agreements_by_3yc_enroll_status,
    sync_agreements_by_agreement_ids,
    sync_agreements_by_coterm_date,
    sync_agreements_by_renewal_date,
    sync_all_agreements,
)

pytestmark = pytest.mark.usefixtures("mock_adobe_config")


# TODO: mocked_mpt_client = mocker.MagicMock() replace with mock_mpt_client fixture


@pytest.fixture(autouse=True)
def mock_add_missing_subscriptions(mocker):
    return mocker.patch("adobe_vipm.flows.sync._add_missing_subscriptions", spec=True)


@pytest.fixture(autouse=True)
def mock_check_update_airtable_missing_deployments(mocker):
    return mocker.patch(
        "adobe_vipm.flows.sync._check_update_airtable_missing_deployments", spec=True
    )


@pytest.fixture()
def mock_create_asset(mocker):
    return mocker.patch("adobe_vipm.flows.sync.create_asset", spec=True)


@pytest.fixture()
def mock_create_agreement_subscription(mocker):
    return mocker.patch("adobe_vipm.flows.sync.create_agreement_subscription", spec=True)


@pytest.fixture()
def mock_get_template_by_name(mocker):
    return mocker.patch("adobe_vipm.flows.sync.get_template_by_name", spec=True)


@freeze_time("2025-06-23")
def test_sync_agreement_prices(
    mocker,
    agreement_factory,
    subscriptions_factory,
    lines_factory,
    adobe_subscription_factory,
    adobe_customer_factory,
    mock_get_adobe_product_by_marketplace_sku,
    mock_adobe_client,
    mock_get_adobe_client,
    mock_get_agreement_subscription,
    mock_update_agreement_subscription,
    mock_mpt_client,
    mock_get_template_by_name,
):
    agreement = agreement_factory(
        lines=lines_factory(external_vendor_id="77777777CA", unit_purchase_price=10.11),
        subscriptions=[
            {"id": "SUB-1000-2000-3000", "status": "Active", "item": {"id": "ITM-0000-0001-0001"}},
            {"id": "SUB-1234-5678", "status": "Terminated", "item": {"id": "ITM-0000-0001-0002"}},
            {"id": "SUB-1000-2000-5000", "status": "Active", "item": {"id": "ITM-0000-0001-0003"}},
        ],
    )
    mpt_subscription = subscriptions_factory()[0]
    another_mpt_subscription = subscriptions_factory(
        adobe_sku="77777777CA01A12",
        adobe_subscription_id="b-sub-id",
        subscription_id="SUB-1000-2000-5000",
    )[0]
    adobe_subscription = adobe_subscription_factory()
    another_adobe_subscription = adobe_subscription_factory(
        subscription_id="b-sub-id",
        offer_id="77777777CA01A12",
        current_quantity=15,
        renewal_quantity=15,
    )
    mock_adobe_client.get_subscriptions.return_value = {
        "items": [adobe_subscription, another_adobe_subscription]
    }
    mock_adobe_client.get_customer.return_value = adobe_customer_factory(coterm_date="2025-04-04")
    mock_get_agreement_subscription.side_effect = [mpt_subscription, another_mpt_subscription]
    mocker.patch(
        "adobe_vipm.airtable.models.get_prices_for_skus",
        side_effect=[
            {"65304578CA01A12": 1234.55, "77777777CA01A12": 20.22},
            {"65304578CA01A12": 1234.55, "77777777CA01A12": 20.22},
        ],
    )
    mocked_update_agreement = mocker.patch("adobe_vipm.flows.sync.update_agreement")
    mock_get_template_by_name.return_value = {"id": "TPL-1234", "name": "Renewing"}

    sync_agreement(mock_mpt_client, agreement, dry_run=False, sync_prices=True)

    mock_get_agreement_subscription.assert_has_calls([
        mocker.call(mock_mpt_client, mpt_subscription["id"]),
        mocker.call(mock_mpt_client, another_mpt_subscription["id"]),
    ])
    mock_update_agreement_subscription.assert_has_calls([
        mocker.call(
            mock_mpt_client,
            mpt_subscription["id"],
            lines=[
                {"id": "ALI-2119-4550-8674-5962-0001", "price": {"unitPP": 1234.55}, "quantity": 10}
            ],
            parameters={
                "fulfillment": [
                    {"externalId": "adobeSKU", "value": "65304578CA01A12"},
                    {
                        "externalId": Param.CURRENT_QUANTITY.value,
                        "value": str(adobe_subscription[Param.CURRENT_QUANTITY.value]),
                    },
                    {
                        "externalId": Param.RENEWAL_QUANTITY.value,
                        "value": str(
                            adobe_subscription["autoRenewal"][Param.RENEWAL_QUANTITY.value]
                        ),
                    },
                    {
                        "externalId": "renewalDate",
                        "value": adobe_subscription["renewalDate"],
                    },
                    {"externalId": "lastSyncDate", "value": "2025-06-23"},
                ]
            },
            commitmentDate="2025-04-04",
            autoRenew=adobe_subscription["autoRenewal"]["enabled"],
            template={"id": "TPL-1234", "name": "Renewing"},
        ),
        mocker.call(
            mock_mpt_client,
            another_mpt_subscription["id"],
            lines=[
                {"id": "ALI-2119-4550-8674-5962-0001", "price": {"unitPP": 20.22}, "quantity": 15}
            ],
            parameters={
                "fulfillment": [
                    {
                        "externalId": "adobeSKU",
                        "value": "77777777CA01A12",
                    },
                    {
                        "externalId": Param.CURRENT_QUANTITY.value,
                        "value": str(another_adobe_subscription[Param.CURRENT_QUANTITY.value]),
                    },
                    {
                        "externalId": Param.RENEWAL_QUANTITY.value,
                        "value": str(
                            another_adobe_subscription["autoRenewal"][Param.RENEWAL_QUANTITY.value]
                        ),
                    },
                    {
                        "externalId": "renewalDate",
                        "value": another_adobe_subscription["renewalDate"],
                    },
                    {"externalId": "lastSyncDate", "value": "2025-06-23"},
                ]
            },
            commitmentDate="2025-04-04",
            autoRenew=another_adobe_subscription["autoRenewal"]["enabled"],
            template={"id": "TPL-1234", "name": "Renewing"},
        ),
    ])
    expected_lines = lines_factory(external_vendor_id="77777777CA", unit_purchase_price=20.22)
    mocked_update_agreement.assert_has_calls([
        mocker.call(
            mock_mpt_client,
            agreement["id"],
            lines=expected_lines,
            parameters={"fulfillment": [{"externalId": "cotermDate", "value": "2025-04-04"}]},
        ),
        mocker.call(
            mock_mpt_client,
            agreement["id"],
            parameters={"fulfillment": [{"externalId": "lastSyncDate", "value": "2025-06-23"}]},
        ),
    ])
    mock_adobe_client.get_subscription.assert_not_called()


@freeze_time("2025-06-23")
def test_sync_agreement_update_asset(
    mocker,
    agreement_factory,
    assets_factory,
    lines_factory,
    adobe_subscription_factory,
    adobe_customer_factory,
    mock_get_adobe_product_by_marketplace_sku,
    mock_adobe_client,
    mock_get_adobe_client,
    mock_get_agreement_subscription,
    mock_update_agreement_subscription,
    mock_mpt_client,
):
    asset_id = "AST-1111-2222-3333"
    mock_asset = assets_factory(asset_id=asset_id, adobe_subscription_id="sub-one-time-id")[0]
    mocker.patch("adobe_vipm.flows.sync.get_asset_by_id", return_value=mock_asset)
    mock_lines = lines_factory(external_vendor_id="65327701CA")
    agreement = agreement_factory(lines=mock_lines, assets=[mock_asset], subscriptions=[])
    adobe_subscription = adobe_subscription_factory(
        subscription_id="sub-one-time-id",
        offer_id="65327701CA01A12",
        used_quantity=6,
    )
    mock_adobe_client.get_subscriptions.return_value = {"items": [adobe_subscription]}
    mock_adobe_client.get_customer.return_value = adobe_customer_factory(coterm_date="2025-04-04")
    mocker.patch(
        "adobe_vipm.airtable.models.get_prices_for_skus",
        return_value=[{"65327701CA01A12": 1234.55}],
    )
    mocked_update_asset = mocker.patch("adobe_vipm.flows.sync.update_asset")
    mocked_update_agreement = mocker.patch("adobe_vipm.flows.sync.update_agreement")

    sync_agreement(mock_mpt_client, agreement, dry_run=False, sync_prices=False)

    mocked_update_asset.assert_called_once_with(
        mock_mpt_client,
        asset_id,
        parameters={
            "fulfillment": [
                {"externalId": "usedQuantity", "value": "6"},
                {"externalId": "lastSyncDate", "value": "2025-06-23"},
            ]
        },
    )
    mocked_update_agreement.assert_has_calls([
        mocker.call(
            mock_mpt_client,
            agreement["id"],
            lines=mock_lines,
            parameters={"fulfillment": [{"externalId": "cotermDate", "value": "2025-04-04"}]},
        ),
        mocker.call(
            mock_mpt_client,
            agreement["id"],
            parameters={"fulfillment": [{"externalId": "lastSyncDate", "value": "2025-06-23"}]},
        ),
    ])
    mock_adobe_client.get_subscription.assert_not_called()


@freeze_time("2025-06-23")
def test_sync_agreement_update_asset_dry_run(
    mocker,
    mock_mpt_client,
    mock_adobe_client,
    agreement_factory,
    assets_factory,
    lines_factory,
    adobe_subscription_factory,
    adobe_customer_factory,
):
    asset_id = "AST-1111-2222-3333"
    mock_asset = assets_factory(asset_id=asset_id, adobe_subscription_id="sub-one-time-id")[0]
    mocker.patch("adobe_vipm.flows.sync.get_asset_by_id", return_value=mock_asset)
    mock_lines = lines_factory(external_vendor_id="65327701CA")
    agreement = agreement_factory(lines=mock_lines, assets=[mock_asset], subscriptions=[])
    adobe_subscription = adobe_subscription_factory(
        subscription_id="sub-one-time-id",
        offer_id="65327701CA01A12",
        used_quantity=6,
    )
    mock_adobe_client.get_subscriptions.return_value = {"items": [adobe_subscription]}
    mock_adobe_client.get_customer.return_value = adobe_customer_factory(coterm_date="2025-04-04")
    mocker.patch(
        "adobe_vipm.airtable.models.get_prices_for_skus",
        return_value=[{"65327701CA01A12": 1234.55}],
    )
    mocked_update_asset = mocker.patch("adobe_vipm.flows.sync.update_asset")

    sync_agreement(mock_mpt_client, agreement, dry_run=True, sync_prices=False)

    mocked_update_asset.assert_not_called()


@freeze_time("2025-06-23")
def test_sync_agreement_prices_not(
    mocker, mock_mpt_client, mock_adobe_client, agreement_factory, adobe_customer_factory
):
    mock_adobe_client.get_customer.return_value = adobe_customer_factory(coterm_date="2025-04-04")
    mock_sync_agreement_prices = mocker.patch(
        "adobe_vipm.flows.sync.sync_agreement_prices",
    )

    sync_agreement(mock_mpt_client, agreement_factory(), dry_run=False, sync_prices=False)

    mock_sync_agreement_prices.assert_not_called()


def test_sync_agreement_prices_dry_run(
    mocker,
    agreement_factory,
    subscriptions_factory,
    lines_factory,
    adobe_subscription_factory,
    adobe_customer_factory,
    mock_get_adobe_product_by_marketplace_sku,
    mock_get_template_by_name
):
    agreement = agreement_factory(
        lines=lines_factory(
            external_vendor_id="77777777CA",
            unit_purchase_price=10.11,
        )
    )
    mpt_subscription = subscriptions_factory()[0]
    adobe_subscription = adobe_subscription_factory()
    mocked_mpt_client = mocker.MagicMock()

    mocked_adobe_client = mocker.MagicMock()
    mocked_adobe_client.get_subscription.return_value = adobe_subscription
    mocked_adobe_client.get_customer.return_value = adobe_customer_factory(coterm_date="2025-04-04")
    mock_get_template_by_name.return_value = {"id": "TPL-1234", "name": "Expired"}

    mocker.patch(
        "adobe_vipm.flows.sync.get_adobe_client",
        return_value=mocked_adobe_client,
    )
    mocked_get_agreement_subscription = mocker.patch(
        "adobe_vipm.flows.sync.get_agreement_subscription",
        return_value=mpt_subscription,
    )

    mocker.patch(
        "adobe_vipm.airtable.models.get_prices_for_skus",
        side_effect=[{"65304578CA01A12": 1234.55}, {"77777777CA01A12": 20.22}],
    )

    mocked_update_agreement_subscription = mocker.patch(
        "adobe_vipm.flows.sync.update_agreement_subscription",
    )

    mocked_update_agreement = mocker.patch(
        "adobe_vipm.flows.sync.update_agreement",
    )

    sync_agreement(mocked_mpt_client, agreement, dry_run=True, sync_prices=True)

    mocked_get_agreement_subscription.assert_called_once_with(
        mocked_mpt_client,
        mpt_subscription["id"],
    )

    mocked_update_agreement_subscription.assert_called_once_with(
        mocked_mpt_client,
        "SUB-1234-5678",
        template={"id": "TPL-1234", "name": "Expired"},
    )
    mocked_update_agreement.assert_not_called()


def test_sync_agreement_prices_exception(
    mocker,
    mock_adobe_client,
    mock_mpt_client,
    agreement_factory,
    subscriptions_factory,
    adobe_api_error_factory,
    adobe_customer_factory,
    caplog,
    mock_get_template_by_name
):
    agreement = agreement_factory()
    mpt_subscription = subscriptions_factory()[0]
    mock_adobe_client.get_customer.return_value = adobe_customer_factory()
    mock_adobe_client.get_subscription.side_effect = AdobeAPIError(
        400,
        adobe_api_error_factory(code="9999", message="Error from Adobe."),
    )
    mock_get_template_by_name.return_value = {"id": "TPL-1234", "name": "Expired"}
    mocked_get_agreement_subscription = mocker.patch(
        "adobe_vipm.flows.sync.get_agreement_subscription", return_value=mpt_subscription
    )
    mocked_update_agreement_subscription = mocker.patch(
        "adobe_vipm.flows.sync.update_agreement_subscription"
    )
    mocked_update_agreement = mocker.patch("adobe_vipm.flows.sync.update_agreement")
    mocked_notifier = mocker.patch(
        "adobe_vipm.flows.sync.notify_agreement_unhandled_exception_in_teams",
    )

    with caplog.at_level(logging.ERROR):
        sync_agreement(mock_mpt_client, agreement, dry_run=False, sync_prices=True)

    assert f"Error synchronizing agreement {agreement['id']}" in caplog.text
    mocked_get_agreement_subscription.assert_called_once_with(
        mock_mpt_client, mpt_subscription["id"]
    )

    mocked_update_agreement_subscription.assert_called_once_with(
        mock_mpt_client,
        "SUB-1234-5678",
        template={"id": "TPL-1234", "name": "Expired"},
    )
    mocked_update_agreement.assert_not_called()
    mocked_notifier.assert_called_once()
    assert mocked_notifier.call_args_list[0].args[0] == agreement["id"]


def test_sync_agreement_prices_skip_processing(
    mocker, mock_adobe_client, mock_mpt_client, agreement_factory, caplog, adobe_customer_factory
):
    agreement = agreement_factory(
        subscriptions=[
            {
                "id": "SUB-1000-2000-3000",
                "status": "Updating",
            },
            {
                "id": "SUB-1234-5678",
                "status": "Terminating",
            },
        ],
    )
    mocker.patch("adobe_vipm.flows.sync.get_adobe_client")
    mocked_update_agreement_subscription = mocker.patch(
        "adobe_vipm.flows.sync.update_agreement_subscription"
    )
    mocked_update_agreement = mocker.patch("adobe_vipm.flows.sync.update_agreement")
    customer = adobe_customer_factory()
    mock_adobe_client.get_customer.return_value = customer

    with caplog.at_level(logging.INFO):
        sync_agreement(mock_mpt_client, agreement, dry_run=False, sync_prices=False)

    assert f"Agreement {agreement['id']} has processing subscriptions, skip it" in caplog.text

    mocked_update_agreement_subscription.assert_not_called()
    mocked_update_agreement.assert_not_called()


@pytest.mark.parametrize("dry_run", [True, False])
def test_sync_agreements_by_agreement_ids(mocker, mock_mpt_client, agreement_factory, dry_run):
    agreement = agreement_factory()
    mocker.patch("adobe_vipm.flows.sync.get_agreements_by_ids", return_value=[agreement])
    mocked_sync_agreement = mocker.patch("adobe_vipm.flows.sync.sync_agreement")

    sync_agreements_by_agreement_ids(
        mock_mpt_client, [agreement["id"]], dry_run=dry_run, sync_prices=False
    )

    mocked_sync_agreement.assert_called_once_with(
        mock_mpt_client, agreement, dry_run=dry_run, sync_prices=False
    )


@pytest.mark.parametrize("dry_run", [True, False])
def test_sync_all_agreements(mocker, mock_mpt_client, agreement_factory, dry_run):
    agreement = agreement_factory()
    mocker.patch("adobe_vipm.flows.sync.get_all_agreements", return_value=[agreement])
    mocked_sync_agreement = mocker.patch("adobe_vipm.flows.sync.sync_agreement")

    sync_all_agreements(mock_mpt_client, dry_run=dry_run)
    mocked_sync_agreement.assert_called_once_with(
        mock_mpt_client, agreement, dry_run=dry_run, sync_prices=False
    )


@freeze_time("2024-11-09")
@pytest.mark.parametrize("dry_run", [True, False])
def test_sync_agreements_by_3yc_end_date(mocker, mock_mpt_client, agreement_factory, dry_run):
    agreement = agreement_factory()
    mocked_get_agreements_by_query = mocker.patch(
        "adobe_vipm.flows.sync.get_agreements_by_query", return_value=[agreement], autospec=True
    )
    mocked_sync_agreement = mocker.patch("adobe_vipm.flows.sync.sync_agreement", autospec=True)

    sync_agreements_by_3yc_end_date(mock_mpt_client, dry_run=dry_run)

    mocked_sync_agreement.assert_called_once_with(
        mock_mpt_client, agreement, dry_run=dry_run, sync_prices=True
    )
    mocked_get_agreements_by_query.assert_called_once_with(
        mock_mpt_client,
        "eq(status,Active)&"
        "any(parameters.fulfillment,and(eq(externalId,3YCEndDate),eq(displayValue,2024-11-08)))&"
        "any(parameters.fulfillment,and(eq(externalId,lastSyncDate),ne(displayValue,2024-11-09)))&"
        "select=lines,parameters,assets,subscriptions,product,listing",
    )


@freeze_time("2025-06-16")
@pytest.mark.parametrize("dry_run", [True, False])
def test_sync_agreements_by_coterm_date(mocker, agreement_factory, dry_run, mock_mpt_client):
    agreement = agreement_factory()
    mocked_get_agreements_by_query = mocker.patch(
        "adobe_vipm.flows.sync.get_agreements_by_query",
        return_value=[agreement],
        autospec=True,
    )
    mocked_sync_agreement = mocker.patch(
        "adobe_vipm.flows.sync.sync_agreement",
        autospec=True,
    )

    sync_agreements_by_coterm_date(mock_mpt_client, dry_run=dry_run)

    mocked_sync_agreement.assert_called_once_with(
        mock_mpt_client,
        agreement,
        dry_run=dry_run,
        sync_prices=True,
    )
    mocked_get_agreements_by_query.assert_called_once_with(
        mock_mpt_client,
        "eq(status,Active)&"
        "any(parameters.fulfillment,and(eq(externalId,cotermDate),eq(displayValue,2025-06-15)))&"
        "any(parameters.fulfillment,and(eq(externalId,lastSyncDate),ne(displayValue,2025-06-16)))&"
        "select=lines,parameters,assets,subscriptions,product,listing",
    )


@freeze_time("2025-07-16")
@pytest.mark.parametrize("dry_run", [True, False])
def test_sync_agreements_by_renewal_date(mocker, mock_mpt_client, agreement_factory, dry_run):
    agreement = agreement_factory()
    mocked_get_agreements_by_query = mocker.patch(
        "adobe_vipm.flows.sync.get_agreements_by_query",
        return_value=[agreement],
        autospec=True,
    )
    mocked_sync_agreement = mocker.patch(
        "adobe_vipm.flows.sync.sync_agreement",
        autospec=True,
    )

    sync_agreements_by_renewal_date(mock_mpt_client, dry_run=dry_run)

    mocked_sync_agreement.assert_called_once_with(
        mock_mpt_client, agreement, dry_run=dry_run, sync_prices=True
    )
    mocked_get_agreements_by_query.assert_called_once_with(
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
    mocker,
    mock_mpt_client,
    mock_adobe_client,
    adobe_customer_factory,
    adobe_commitment_factory,
    agreement_factory,
    status,
):
    agreement = agreement_factory()
    mock_get_agreements_by_query = mocker.patch(
        "adobe_vipm.flows.sync.get_agreements_by_3yc_commitment_request_invitation",
        return_value=[agreement],
        autospec=True,
    )
    mock_adobe_client.get_customer.return_value = adobe_customer_factory(
        commitment=adobe_commitment_factory(status=status)
    )
    mock_sync_agreement = mocker.patch("adobe_vipm.flows.sync.sync_agreement", autospec=True)

    sync_agreements_by_3yc_enroll_status(mock_mpt_client, dry_run=False)

    mock_get_agreements_by_query.assert_called_once_with(
        mock_mpt_client, THREE_YC_TEMP_3YC_STATUSES
    )
    mock_sync_agreement.assert_called_once_with(
        mock_mpt_client, agreement, dry_run=False, sync_prices=True
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
):
    agreement = agreement_factory()
    mock_get_agreements_by_3yc_commitment_request_invitation = mocker.patch(
        "adobe_vipm.flows.sync.get_agreements_by_3yc_commitment_request_invitation",
        return_value=[agreement],
        autospec=True,
    )
    mock_adobe_client.get_customer.return_value = adobe_customer_factory(
        commitment=adobe_commitment_factory(status=status)
    )
    mock_sync_agreement = mocker.patch("adobe_vipm.flows.sync.sync_agreement", autospec=True)
    mock_update_agreement = mocker.patch("adobe_vipm.flows.sync.update_agreement", autospec=True)

    sync_agreements_by_3yc_enroll_status(mock_mpt_client, dry_run=False)

    mock_get_agreements_by_3yc_commitment_request_invitation.assert_called_once_with(
        mock_mpt_client, THREE_YC_TEMP_3YC_STATUSES
    )
    mock_update_agreement.assert_not_called()
    mock_sync_agreement.assert_called_once_with(
        mock_mpt_client, agreement, dry_run=False, sync_prices=True
    )


def test_sync_agreements_by_3yc_enroll_status_status_error(
    mocker,
    mock_mpt_client,
    mock_adobe_client,
    adobe_customer_factory,
    adobe_commitment_factory,
    agreement_factory,
    caplog,
):
    mocker.patch(
        "adobe_vipm.flows.sync.get_agreements_by_3yc_commitment_request_invitation",
        side_effect=MPTAPIError(400, {"rql_validation": ["Value has to be a non empty array."]}),
        autospec=True,
    )
    mock_adobe_client.get_customer.return_value = adobe_customer_factory(
        commitment=adobe_commitment_factory(status=constants.ThreeYearCommitmentStatus.EXPIRED)
    )
    mock_sync_agreement = mocker.patch("adobe_vipm.flows.sync.sync_agreement", autospec=True)
    mock_update_agreement = mocker.patch("adobe_vipm.flows.sync.update_agreement", autospec=True)

    with pytest.raises(MPTAPIError):
        sync_agreements_by_3yc_enroll_status(mock_mpt_client, dry_run=False)

    assert "Unknown exception getting agreements by 3YC enroll status" in caplog.text
    mock_update_agreement.assert_not_called()
    mock_sync_agreement.assert_not_called()


def test_sync_agreements_by_3yc_enroll_status_error_sync(
    mocker,
    mock_mpt_client,
    mock_adobe_client,
    adobe_customer_factory,
    adobe_commitment_factory,
    agreement_factory,
    caplog,
):
    agreement = agreement_factory()
    mock_get_agreements_by_3yc_commitment_request_invitation = mocker.patch(
        "adobe_vipm.flows.sync.get_agreements_by_3yc_commitment_request_invitation",
        return_value=[agreement],
        autospec=True,
    )
    mock_adobe_client.get_customer.return_value = adobe_customer_factory(
        commitment=adobe_commitment_factory(status=constants.ThreeYearCommitmentStatus.COMMITTED)
    )
    mock_sync_agreement = mocker.patch(
        "adobe_vipm.flows.sync.sync_agreement",
        autospec=True,
        side_effect=AuthorizationNotFoundError("Authorization with uk/id ID not found."),
    )
    mock_update_agreement = mocker.patch("adobe_vipm.flows.sync.update_agreement", autospec=True)

    sync_agreements_by_3yc_enroll_status(mock_mpt_client, dry_run=False)

    mock_get_agreements_by_3yc_commitment_request_invitation.assert_called_once_with(
        mock_mpt_client, THREE_YC_TEMP_3YC_STATUSES
    )
    mock_update_agreement.assert_not_called()
    mock_sync_agreement.assert_called_once_with(
        mock_mpt_client,
        agreement,
        dry_run=False,
        sync_prices=True,
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
):
    agreement = agreement_factory()
    mock_get_agreements_by_3yc_commitment_request_invitation = mocker.patch(
        "adobe_vipm.flows.sync.get_agreements_by_3yc_commitment_request_invitation",
        return_value=[agreement, agreement],
        autospec=True,
    )
    mock_adobe_client.get_customer.return_value = adobe_customer_factory(
        commitment=adobe_commitment_factory(status=constants.ThreeYearCommitmentStatus.COMMITTED)
    )
    mock_sync_agreement = mocker.patch(
        "adobe_vipm.flows.sync.sync_agreement",
        autospec=True,
        side_effect=Exception("Unknown exception getting agreements by 3YC enroll status"),
    )
    mock_update_agreement = mocker.patch("adobe_vipm.flows.sync.update_agreement", autospec=True)

    sync_agreements_by_3yc_enroll_status(mock_mpt_client, dry_run=False)

    mock_get_agreements_by_3yc_commitment_request_invitation.assert_called_once_with(
        mock_mpt_client, THREE_YC_TEMP_3YC_STATUSES
    )
    mock_update_agreement.assert_not_called()
    mock_sync_agreement.assert_has_calls([
        mocker.call(mock_mpt_client, agreement, dry_run=False, sync_prices=True),
        mocker.call(mock_mpt_client, agreement, dry_run=False, sync_prices=True),
    ])
    assert caplog.messages == [
        "Checking 3YC enroll status for agreement AGR-2119-4550-8674-5962",
        "Unknown exception synchronizing 3YC enroll status for agreement AGR-2119-4550-8674-5962",
        "Checking 3YC enroll status for agreement AGR-2119-4550-8674-5962",
        "Unknown exception synchronizing 3YC enroll status for agreement AGR-2119-4550-8674-5962",
    ]


def test_sync_agreements_by_3yc_enroll_status_no_cust(
    mocker,
    caplog,
    mock_mpt_client,
    mock_adobe_client,
    agreement_factory,
    mock_send_exception,
    adobe_customer_factory,
    adobe_commitment_factory,
    mock_get_customer_or_process_lost_customer,
):
    agreement = agreement_factory()
    mock_get_agreements_by_3yc_commitment_request_invitation = mocker.patch(
        "adobe_vipm.flows.sync.get_agreements_by_3yc_commitment_request_invitation",
        return_value=[agreement],
        autospec=True,
    )
    mock_adobe_client.get_customer.side_effect = AdobeAPIError(
        status_code=int(AdobeStatus.INVALID_CUSTOMER.value),
        payload={"code": "1116", "message": "Invalid Customer", "additionalDetails": []},
    )
    mock_sync_agreement = mocker.patch("adobe_vipm.flows.sync.sync_agreement", autospec=True)
    mock_update_agreement = mocker.patch("adobe_vipm.flows.sync.update_agreement", autospec=True)
    mock_get_customer_or_process_lost_customer.return_value = None

    sync_agreements_by_3yc_enroll_status(mock_mpt_client, dry_run=False)

    mock_get_agreements_by_3yc_commitment_request_invitation.assert_called_once_with(
        mock_mpt_client, THREE_YC_TEMP_3YC_STATUSES
    )
    mock_get_customer_or_process_lost_customer.assert_called_once_with(
        mock_mpt_client, mock_adobe_client, agreement, customer_id=""
    )
    mock_update_agreement.assert_not_called()
    mock_sync_agreement.assert_not_called()
    assert caplog.messages == ["Checking 3YC enroll status for agreement AGR-2119-4550-8674-5962"]


@freeze_time("2024-11-09 12:30:00")
def test_sync_agreement_prices_with_3yc(
    mocker,
    agreement_factory,
    subscriptions_factory,
    lines_factory,
    adobe_subscription_factory,
    adobe_customer_factory,
    adobe_commitment_factory,
    mock_get_adobe_product_by_marketplace_sku,
    mock_adobe_client,
    mock_get_adobe_client,
    mock_mpt_client,
    mock_update_agreement_subscription,
    mock_get_agreement_subscription,
    mock_get_template_by_name,
):
    agreement = agreement_factory(
        lines=lines_factory(external_vendor_id="77777777CA", unit_purchase_price=10.11)
    )
    mpt_subscription = subscriptions_factory()[0]
    adobe_subscription = adobe_subscription_factory()
    mock_adobe_client.get_subscriptions.return_value = {"items": [adobe_subscription]}
    mock_adobe_client.get_customer.return_value = adobe_customer_factory(
        coterm_date="2025-04-04",
        commitment=adobe_commitment_factory(licenses=9, consumables=1220),
        recommitment_request=adobe_commitment_factory(status="ACCEPTED"),
    )
    mocked_get_agreement_subscription = mocker.patch(
        "adobe_vipm.flows.sync.get_agreement_subscription", return_value=mpt_subscription
    )
    mocker.patch(
        "adobe_vipm.airtable.models.get_prices_for_3yc_skus",
        side_effect=[{"65304578CA01A12": 1234.55}, {"77777777CA01A12": 20.22}],
    )
    mocked_update_agreement = mocker.patch(
        "adobe_vipm.flows.sync.update_agreement",
    )

    mock_get_template_by_name.return_value = {"id": "TPL-1234", "name": "Renewing"}

    sync_agreement(mock_mpt_client, agreement, dry_run=False, sync_prices=True)

    mocked_get_agreement_subscription.assert_called_once_with(
        mock_mpt_client,
        mpt_subscription["id"],
    )
    mock_update_agreement_subscription.assert_has_calls([
        mocker.call(
            mock_mpt_client,
            "SUB-1234-5678",
            template={"id": "TPL-1234", "name": "Renewing"},
        ),
        mocker.call(
            mock_mpt_client,
            mpt_subscription["id"],
            lines=[
                {"id": "ALI-2119-4550-8674-5962-0001", "price": {"unitPP": 1234.55}, "quantity": 10}
            ],
            parameters={
                "fulfillment": [
                    {"externalId": "adobeSKU", "value": "65304578CA01A12"},
                    {
                        "externalId": Param.CURRENT_QUANTITY.value,
                        "value": str(adobe_subscription[Param.CURRENT_QUANTITY.value]),
                    },
                    {
                        "externalId": Param.RENEWAL_QUANTITY.value,
                        "value": str(
                            adobe_subscription["autoRenewal"][Param.RENEWAL_QUANTITY.value]
                        ),
                    },
                    {
                        "externalId": "renewalDate",
                        "value": adobe_subscription["renewalDate"],
                    },
                    {"externalId": "lastSyncDate", "value": "2024-11-09"},
                ]
            },
            commitmentDate="2025-04-04",
            autoRenew=adobe_subscription["autoRenewal"]["enabled"],
            template={"id": "TPL-1234", "name": "Renewing"},
        ),
    ])

    expected_lines = lines_factory(external_vendor_id="77777777CA", unit_purchase_price=20.22)

    assert mocked_update_agreement.call_args_list == [
        mocker.call(
            mock_mpt_client,
            agreement["id"],
            lines=expected_lines,
            parameters={
                "fulfillment": [
                    {"externalId": "3YCRecommitmentRequestStatus", "value": "ACCEPTED"},
                    {"externalId": "3YCRecommitment", "value": None},
                    {"externalId": "3YCEnrollStatus", "value": "COMMITTED"},
                    {"externalId": "3YCStartDate", "value": "2024-01-01"},
                    {"externalId": "3YCEndDate", "value": "2025-01-01"},
                    {"externalId": "cotermDate", "value": "2025-04-04"},
                ],
                "ordering": [
                    {"externalId": "3YCLicenses", "value": "9"},
                    {"externalId": "3YCConsumables", "value": "1220"},
                ],
            },
        ),
        mocker.call(
            mock_mpt_client,
            agreement["id"],
            parameters={"fulfillment": [{"externalId": "lastSyncDate", "value": "2024-11-09"}]},
        ),
    ]


@freeze_time("2025-06-19")
@pytest.mark.parametrize("dry_run", [True, False])
def test_sync_global_customer_parameter(
    mocker,
    lines_factory,
    mock_mpt_client,
    mock_adobe_client,
    agreement_factory,
    mock_get_adobe_client,
    subscriptions_factory,
    adobe_customer_factory,
    mock_get_prices_for_skus,
    mock_update_subscriptions,
    adobe_subscription_factory,
    assets_factory,
    fulfillment_parameters_factory,
    mock_add_missing_subscriptions,
    mock_get_adobe_product_by_marketplace_sku,
    dry_run,
    caplog,
):
    agreement = agreement_factory(
        lines=lines_factory(external_vendor_id="77777777CA", unit_purchase_price=10.11),
        subscriptions=[
            {"id": "SUB-1000-2000-3000", "status": "Active", "item": {"id": "ITM-0000-0001-0001"}},
            {"id": "SUB-1234-5678", "status": "Terminated", "item": {"id": "ITM-0000-0001-0002"}},
            {"id": "SUB-1000-2000-5000", "status": "Active", "item": {"id": "ITM-0000-0001-0003"}},
        ],
    )
    adobe_subscription = adobe_subscription_factory()
    another_adobe_subscription = adobe_subscription_factory(
        subscription_id="b-sub-id",
        offer_id="77777777CA01A12",
        current_quantity=15,
        renewal_quantity=15,
    )
    adobe_deployment_subscription = adobe_subscription_factory(
        subscription_id="b-sub-id",
        offer_id="77777777CA01A12",
        current_quantity=20,
        renewal_quantity=20,
    )
    mock_adobe_client.get_subscriptions.return_value = {
        "items": [
            adobe_subscription,
            another_adobe_subscription,
            adobe_deployment_subscription,
            {**adobe_deployment_subscription, "subscriptionId": "d-sub-id"},
        ]
    }
    mock_adobe_client.get_customer.return_value = adobe_customer_factory(
        coterm_date="2025-04-04", global_sales_enabled=True
    )
    mock_adobe_client.get_customer_deployments_active_status.return_value = [
        {
            "deploymentId": "deployment-id",
            "status": "1000",
            "companyProfile": {"address": {"country": "DE"}},
        }
    ]
    deployment_agreements = [
        agreement_factory(
            agreement_id="AGR-deployment-1",
            fulfillment_parameters=fulfillment_parameters_factory(
                global_customer="", deployment_id="deployment-1", deployments=""
            ),
            lines=lines_factory(external_vendor_id="77777777CA", unit_purchase_price=10.11),
        ),
        agreement_factory(
            agreement_id="AGR-deployment-2",
            status=AgreementStatus.TERMINATED,
            fulfillment_parameters=fulfillment_parameters_factory(
                global_customer="", deployment_id="deployment-2", deployments=""
            ),
        ),
    ]
    mocker.patch(
        "adobe_vipm.flows.sync.get_agreements_by_customer_deployments",
        return_value=deployment_agreements,
    )
    mock_get_prices_for_skus.return_value = {"65304578CA01A12": 1234.55, "77777777CA01A12": 20.22}
    mocked_update_agreement = mocker.patch("adobe_vipm.flows.sync.update_agreement")
    mock_asset = assets_factory()[0]
    mock_asset["externalIds"] = {}
    mocker.patch("adobe_vipm.flows.sync.get_asset_by_id", return_value=mock_asset)

    sync_agreement(mock_mpt_client, agreement, dry_run=dry_run, sync_prices=True)

    mock_add_missing_subscriptions.assert_called_once()
    assert mock_update_subscriptions.call_count == 2
    expected_lines = lines_factory(external_vendor_id="77777777CA", unit_purchase_price=20.22)
    if not dry_run:
        assert mocked_update_agreement.call_args_list == [
            mocker.call(
                mock_mpt_client,
                agreement["id"],
                lines=expected_lines,
                parameters={"fulfillment": [{"externalId": "cotermDate", "value": "2025-04-04"}]},
            ),
            mocker.call(
                mock_mpt_client,
                agreement["id"],
                parameters={
                    "fulfillment": [
                        {"externalId": "globalCustomer", "value": ["Yes"]},
                        {"externalId": "deployments", "value": "deployment-id - DE"},
                    ]
                },
            ),
            mocker.call(
                mock_mpt_client,
                deployment_agreements[0]["id"],
                lines=expected_lines,
                parameters={"fulfillment": [{"externalId": "cotermDate", "value": "2025-04-04"}]},
            ),
            mocker.call(
                mock_mpt_client,
                deployment_agreements[0]["id"],
                parameters={
                    "fulfillment": [
                        {
                            "id": "PAR-3528-2927",
                            "name": "3YC End Date",
                            "externalId": "3YCEndDate",
                            "type": "Date",
                            "value": "",
                        },
                        {
                            "id": "PAR-9876-5432",
                            "name": "3YC Enroll Status",
                            "externalId": "3YCEnrollStatus",
                            "type": "SingleLineText",
                            "value": "",
                        },
                        {
                            "id": "PAR-2266-4848",
                            "name": "3YC Start Date",
                            "externalId": "3YCStartDate",
                            "type": "Date",
                            "value": "",
                        },
                    ]
                },
            ),
            mocker.call(
                mock_mpt_client,
                agreement["id"],
                parameters={"fulfillment": [{"externalId": "lastSyncDate", "value": "2025-06-19"}]},
            ),
        ]
    else:
        assert mocked_update_agreement.call_args_list == [
            mocker.call(
                mock_mpt_client,
                agreement["id"],
                parameters={
                    "fulfillment": [
                        {"externalId": "globalCustomer", "value": ["Yes"]},
                        {"externalId": "deployments", "value": "deployment-id - DE"},
                    ]
                },
            )
        ]
    assert "Getting subscriptions for update for agreement AGR-deployment-1" in caplog.messages
    assert "Getting subscriptions for update for agreement AGR-deployment-2" not in caplog.messages
    assert (
            "No vendor subscription found for asset AST-1000-2000-3000: asset.externalIds.vendor "
            "is empty" in caplog.messages
    )

@freeze_time("2025-06-19")
def test_sync_global_customer_parameter_not_prices(
    mocker,
    caplog,
    mock_mpt_client,
    mock_adobe_client,
    agreement_factory,
    mock_add_missing_subscriptions,
    mock_get_subscriptions_for_update,
):
    mock_adobe_client.get_customer_deployments_active_status.return_value = [
        {
            "deploymentId": "deployment-id",
            "status": "1000",
            "companyProfile": {"address": {"country": "DE"}},
        }
    ]
    agreement = agreement_factory(assets=[])
    mocker.patch(
        "adobe_vipm.flows.sync.get_agreements_by_customer_deployments",
        return_value=[agreement],
    )
    mock_sync_agreement_prices = mocker.patch("adobe_vipm.flows.sync.sync_agreement_prices")

    sync_agreement(mock_mpt_client, agreement, dry_run=False, sync_prices=False)

    mock_sync_agreement_prices.assert_not_called()
    mock_get_subscriptions_for_update.assert_not_called()
    mock_add_missing_subscriptions.assert_called_once()
    assert caplog.messages == [
        "Synchronizing agreement AGR-2119-4550-8674-5962...",
        "Getting assets for update for agreement AGR-2119-4550-8674-5962",
        "Skipping price sync - sync_prices False.",
        "Agreement updated AGR-2119-4550-8674-5962",
        "Setting global customer for agreement AGR-2119-4550-8674-5962",
        "Setting deployments for agreement AGR-2119-4550-8674-5962",
        "Looking for orphaned deployment subscriptions in Adobe.",
        "Skipping price sync - sync_prices False.",
        "Agreement updated AGR-2119-4550-8674-5962",
        "Updating Last Sync Date for agreement AGR-2119-4550-8674-5962",
    ]


@freeze_time("2025-06-30")
def test_sync_global_customer_update_not_required(
    mocker,
    lines_factory,
    mock_mpt_client,
    agreement_factory,
    mock_adobe_client,
    mock_get_adobe_client,
    subscriptions_factory,
    adobe_customer_factory,
    mock_get_prices_for_skus,
    adobe_subscription_factory,
    mock_update_subscriptions,
    fulfillment_parameters_factory,
    mock_add_missing_subscriptions,
    mock_get_subscriptions_for_update,
    mock_get_adobe_product_by_marketplace_sku,
    mock_get_agreements_by_customer_deployments,
):
    agreement = agreement_factory(
        lines=lines_factory(external_vendor_id="77777777CA", unit_purchase_price=10.11),
        fulfillment_parameters=[
            {"externalId": "globalCustomer", "value": ["Yes"]},
            {"externalId": "deployments", "value": "deployment-id - DE"},
        ],
        subscriptions=[
            {"id": "SUB-1000-2000-3000", "status": "Active", "item": {"id": "ITM-0000-0001-0001"}},
            {"id": "SUB-1234-5678", "status": "Terminated", "item": {"id": "ITM-0000-0001-0002"}},
            {"id": "SUB-1000-2000-5000", "status": "Active", "item": {"id": "ITM-0000-0001-0003"}},
        ],
    )
    adobe_subscription = adobe_subscription_factory()
    another_adobe_subscription = adobe_subscription_factory(
        subscription_id="b-sub-id",
        offer_id="77777777CA01A12",
        current_quantity=15,
        renewal_quantity=15,
    )
    adobe_deployment_subscription = adobe_subscription_factory()
    another_adobe_deployment_subscription = adobe_subscription_factory()
    mock_adobe_client.get_subscription.side_effect = [
        adobe_subscription,
        another_adobe_subscription,
        adobe_deployment_subscription,
        another_adobe_deployment_subscription,
    ]
    mock_adobe_client.get_subscriptions.return_value = {
        "items": [
            adobe_subscription,
            another_adobe_subscription,
            adobe_deployment_subscription,
            another_adobe_deployment_subscription,
            {**another_adobe_deployment_subscription, "subscriptionId": "d-sub-id"},
        ]
    }
    mock_adobe_client.get_customer_deployments_active_status.return_value = [
        {
            "deploymentId": "deployment-id",
            "status": "1000",
            "companyProfile": {"address": {"country": "DE"}},
        }
    ]
    mock_adobe_client.get_customer.return_value = adobe_customer_factory(
        coterm_date="2025-04-04", global_sales_enabled=True
    )
    mock_get_prices_for_skus.return_value = {"65304578CA01A12": 1234.55, "77777777CA01A12": 20.22}
    mock_get_agreements_by_customer_deployments.return_value = [
        agreement_factory(
            fulfillment_parameters=fulfillment_parameters_factory(
                global_customer="", deployment_id=f"deployment-{i}", deployments=""
            )
        )
        for i in range(2)
    ]
    mocked_update_agreement = mocker.patch("adobe_vipm.flows.sync.update_agreement")

    sync_agreement(mock_mpt_client, agreement, dry_run=False, sync_prices=True)

    mock_add_missing_subscriptions.assert_called_once()
    assert mock_get_subscriptions_for_update.call_count == 3

    assert mocked_update_agreement.mock_calls == [
        mocker.call(
            mock_mpt_client,
            "AGR-2119-4550-8674-5962",
            lines=[
                {
                    "item": {
                        "id": "ITM-1234-1234-1234-0001",
                        "name": "Awesome product",
                        "externalIds": {"vendor": "77777777CA"},
                    },
                    "subscription": {
                        "id": "SUB-1000-2000-3000",
                        "status": "Active",
                        "name": "Subscription for Acrobat Pro for Teams; Multi Language",
                    },
                    "oldQuantity": 0,
                    "quantity": 170,
                    "price": {"unitPP": 20.22},
                    "id": "ALI-2119-4550-8674-5962-0001",
                }
            ],
            parameters={"fulfillment": [{"externalId": "cotermDate", "value": "2025-04-04"}]},
        ),
        mocker.call(
            mock_mpt_client,
            "AGR-2119-4550-8674-5962",
            lines=[],
            parameters={"fulfillment": [{"externalId": "cotermDate", "value": "2025-04-04"}]},
        ),
        mocker.call(
            mock_mpt_client, "AGR-2119-4550-8674-5962", parameters={"fulfillment": [{}, {}, {}]}
        ),
        mocker.call(
            mock_mpt_client,
            "AGR-2119-4550-8674-5962",
            lines=[],
            parameters={"fulfillment": [{"externalId": "cotermDate", "value": "2025-04-04"}]},
        ),
        mocker.call(
            mock_mpt_client,
            "AGR-2119-4550-8674-5962",
            parameters={"fulfillment": [{}, {}, {}]},
        ),
        mocker.call(
            mock_mpt_client,
            "AGR-2119-4550-8674-5962",
            parameters={"fulfillment": [{"externalId": "lastSyncDate", "value": "2025-06-30"}]},
        ),
    ]

    mock_adobe_client.get_customer_deployments_active_status.assert_called_once()


@freeze_time("2025-06-30")
def test_sync_global_customer_update_adobe_error(
    mocker,
    agreement_factory,
    subscriptions_factory,
    lines_factory,
    adobe_subscription_factory,
    adobe_customer_factory,
    adobe_api_error_factory,
    mock_get_adobe_product_by_marketplace_sku,
    mock_adobe_client,
    mock_get_adobe_client,
    mock_mpt_client,
    mock_update_agreement_subscription,
    mock_get_agreement_subscription,
    mock_get_template_by_name,
):
    agreement = agreement_factory(
        lines=lines_factory(external_vendor_id="77777777CA", unit_purchase_price=10.11),
        fulfillment_parameters=[
            {"externalId": "globalCustomer", "value": ["Yes"]},
            {"externalId": "deployments", "value": "deployment-id - DE"},
        ],
        subscriptions=[
            {"id": "SUB-1000-2000-3000", "status": "Active", "item": {"id": "ITM-0000-0001-0001"}},
            {"id": "SUB-1234-5678", "status": "Terminated", "item": {"id": "ITM-0000-0001-0002"}},
            {"id": "SUB-1000-2000-5000", "status": "Active", "item": {"id": "ITM-0000-0001-0003"}},
        ],
    )
    mpt_subscription = subscriptions_factory()[0]
    another_mpt_subscription = subscriptions_factory(
        adobe_sku="77777777CA01A12",
        adobe_subscription_id="b-sub-id",
        subscription_id="SUB-1000-2000-5000",
    )[0]
    adobe_subscription = adobe_subscription_factory()
    another_adobe_subscription = adobe_subscription_factory(
        subscription_id="b-sub-id",
        offer_id="77777777CA01A12",
        current_quantity=15,
        renewal_quantity=15,
    )
    mock_adobe_client.get_subscriptions.return_value = {
        "items": [adobe_subscription, another_adobe_subscription]
    }
    adobe_error = AdobeAPIError(400, adobe_api_error_factory("9999", "some error"))
    mock_adobe_client.get_customer_deployments_active_status.side_effect = adobe_error
    mock_adobe_client.get_customer.return_value = adobe_customer_factory(
        coterm_date="2025-04-04", global_sales_enabled=True
    )
    mocked_get_agreement_subscription = mocker.patch(
        "adobe_vipm.flows.sync.get_agreement_subscription",
        side_effect=[mpt_subscription, another_mpt_subscription],
    )

    mocker.patch(
        "adobe_vipm.airtable.models.get_prices_for_skus",
        side_effect=[
            {"65304578CA01A12": 1234.55, "77777777CA01A12": 20.22},
            {"65304578CA01A12": 1234.55, "77777777CA01A12": 20.22},
        ],
    )

    mocked_update_agreement_subscription = mocker.patch(
        "adobe_vipm.flows.sync.update_agreement_subscription"
    )

    mocked_update_agreement = mocker.patch("adobe_vipm.flows.sync.update_agreement")

    mocked_notifier = mocker.patch(
        "adobe_vipm.flows.sync.notify_agreement_unhandled_exception_in_teams"
    )
    mock_get_template_by_name.return_value = {"id": "TPL-1234", "name": "Renewing"}

    sync_agreement(mock_mpt_client, agreement, dry_run=False, sync_prices=True)

    assert mocked_get_agreement_subscription.call_args_list == [
        mocker.call(mock_mpt_client, mpt_subscription["id"]),
        mocker.call(mock_mpt_client, another_mpt_subscription["id"]),
    ]

    assert mocked_update_agreement_subscription.call_args_list == [
        mocker.call(
            mock_mpt_client,
            "SUB-1234-5678",
            template={"id": "TPL-1234", "name": "Renewing"},
        ),
        mocker.call(
            mock_mpt_client,
            mpt_subscription["id"],
            lines=[
                {"id": "ALI-2119-4550-8674-5962-0001", "price": {"unitPP": 1234.55}, "quantity": 10}
            ],
            parameters={
                "fulfillment": [
                    {"externalId": "adobeSKU", "value": "65304578CA01A12"},
                    {
                        "externalId": Param.CURRENT_QUANTITY.value,
                        "value": str(adobe_subscription[Param.CURRENT_QUANTITY.value]),
                    },
                    {
                        "externalId": Param.RENEWAL_QUANTITY.value,
                        "value": str(
                            adobe_subscription["autoRenewal"][Param.RENEWAL_QUANTITY.value]
                        ),
                    },
                    {
                        "externalId": "renewalDate",
                        "value": adobe_subscription["renewalDate"],
                    },
                    {"externalId": "lastSyncDate", "value": "2025-06-30"},
                ]
            },
            commitmentDate="2025-04-04",
            autoRenew=adobe_subscription["autoRenewal"]["enabled"],
            template={"id": "TPL-1234", "name": "Renewing"},
        ),
        mocker.call(
            mock_mpt_client,
            another_mpt_subscription["id"],
            lines=[
                {"id": "ALI-2119-4550-8674-5962-0001", "price": {"unitPP": 20.22}, "quantity": 15}
            ],
            parameters={
                "fulfillment": [
                    {"externalId": "adobeSKU", "value": "77777777CA01A12"},
                    {
                        "externalId": Param.CURRENT_QUANTITY.value,
                        "value": str(another_adobe_subscription[Param.CURRENT_QUANTITY.value]),
                    },
                    {
                        "externalId": Param.RENEWAL_QUANTITY.value,
                        "value": str(
                            another_adobe_subscription["autoRenewal"][Param.RENEWAL_QUANTITY.value]
                        ),
                    },
                    {
                        "externalId": "renewalDate",
                        "value": another_adobe_subscription["renewalDate"],
                    },
                    {"externalId": "lastSyncDate", "value": "2025-06-30"},
                ]
            },
            commitmentDate="2025-04-04",
            autoRenew=another_adobe_subscription["autoRenewal"]["enabled"],
            template={"id": "TPL-1234", "name": "Renewing"},
        ),
    ]

    expected_lines = lines_factory(external_vendor_id="77777777CA", unit_purchase_price=20.22)
    mocked_update_agreement.assert_called_once_with(
        mock_mpt_client,
        agreement["id"],
        lines=expected_lines,
        parameters={"fulfillment": [{"externalId": "cotermDate", "value": "2025-04-04"}]},
    )
    mock_adobe_client.get_customer_deployments_active_status.assert_called_once()
    mocked_notifier.assert_called_once()
    assert mocked_notifier.call_args_list[0].args[0] == agreement["id"]


def test_sync_global_customer_parameters_error(
    mocker,
    caplog,
    lines_factory,
    mock_mpt_client,
    mock_adobe_client,
    agreement_factory,
    mock_get_adobe_client,
    subscriptions_factory,
    adobe_customer_factory,
    adobe_api_error_factory,
    mock_get_prices_for_skus,
    adobe_subscription_factory,
    mock_sync_deployments_prices,
    mock_get_agreement_subscription,
    mock_get_subscriptions_for_update,
    mock_update_agreement_subscription,
    mock_get_adobe_product_by_marketplace_sku,
    mock_get_customer_or_process_lost_customer,
    mock_get_agreements_by_customer_deployments,
):
    agreement = agreement_factory(
        lines=lines_factory(external_vendor_id="77777777CA", unit_purchase_price=10.11),
        fulfillment_parameters=[
            {"externalId": "globalCustomer", "value": ["Yes"]},
            {"externalId": "deployments", "value": "deployment-id - DE"},
        ],
        assets=[],
        subscriptions=[
            {"id": "SUB-1000-2000-3000", "status": "Active", "item": {"id": "ITM-0000-0001-0001"}},
            {"id": "SUB-1234-5678", "status": "Terminated", "item": {"id": "ITM-0000-0001-0002"}},
            {"id": "SUB-1000-2000-5000", "status": "Active", "item": {"id": "ITM-0000-0001-0003"}},
        ],
    )
    mpt_subscription = subscriptions_factory()[0]
    another_mpt_subscription = subscriptions_factory(
        adobe_sku="77777777CA01A12",
        adobe_subscription_id="b-sub-id",
        subscription_id="SUB-1000-2000-5000",
    )[0]
    adobe_subscription = adobe_subscription_factory()
    another_adobe_subscription = adobe_subscription_factory(
        subscription_id="b-sub-id",
        offer_id="77777777CA01A12",
        current_quantity=15,
        renewal_quantity=15,
    )
    adobe_subscriptions = [
        adobe_subscription,
        another_adobe_subscription,
    ]
    mock_adobe_client.get_subscriptions.return_value = {"items": adobe_subscriptions}
    mock_adobe_client.get_customer_deployments_active_status.return_value = [
        {
            "deploymentId": "deployment-id",
            "status": "1000",
            "companyProfile": {"address": {"country": "UK"}},
        }
    ]
    customer = adobe_customer_factory(coterm_date="2025-04-04", global_sales_enabled=True)
    mock_get_customer_or_process_lost_customer.return_value = customer
    mock_get_agreement_subscription.side_effect = [mpt_subscription, another_mpt_subscription]
    mock_get_prices_for_skus.side_effect = [
        {"65304578CA01A12": 1234.55, "77777777CA01A12": 20.22},
        {"65304578CA01A12": 1234.55, "77777777CA01A12": 20.22},
    ]
    mocker.patch(
        "adobe_vipm.flows.sync.update_agreement",
        side_effect=[
            mocker.MagicMock(),
            AdobeAPIError(400, {"error": "some error"}),
            mocker.MagicMock(),
        ],
    )
    mocker.patch(
        "adobe_vipm.flows.sync.notify_agreement_unhandled_exception_in_teams",
    )

    with caplog.at_level(logging.ERROR):
        sync_agreement(mock_mpt_client, agreement, dry_run=False, sync_prices=False)

    mock_get_subscriptions_for_update.assert_not_called()
    mock_sync_deployments_prices.assert_called_once()
    assert (
        caplog.records[0].message
        == "Error setting global customer parameters for agreement AGR-2119-4550-8674-5962."
    )


def test_sync_agreement_error_getting_adobe_customer(
    mocker,
    mock_adobe_client,
    mock_mpt_client,
    agreement_factory,
    subscriptions_factory,
    lines_factory,
    adobe_subscription_factory,
    adobe_customer_factory,
    adobe_api_error_factory,
):
    agreement = agreement_factory(
        lines=lines_factory(external_vendor_id="77777777CA", unit_purchase_price=10.11),
        fulfillment_parameters=[
            {"externalId": "globalCustomer", "value": ["Yes"]},
            {"externalId": "deployments", "value": "deployment-id - DE"},
        ],
        subscriptions=[
            {
                "id": "SUB-1000-2000-3000",
                "status": "Active",
                "item": {
                    "id": "ITM-0000-0001-0001",
                },
            },
            {
                "id": "SUB-1234-5678",
                "status": "Terminated",
                "item": {
                    "id": "ITM-0000-0001-0002",
                },
            },
            {
                "id": "SUB-1000-2000-5000",
                "status": "Active",
                "item": {
                    "id": "ITM-0000-0001-0003",
                },
            },
        ],
    )
    adobe_error = AdobeAPIError(
        400,
        adobe_api_error_factory("9999", "some error"),
    )
    mock_adobe_client.get_customer.side_effect = adobe_error
    mocked_notifier = mocker.patch(
        "adobe_vipm.flows.sync.notify_agreement_unhandled_exception_in_teams"
    )

    sync_agreement(mock_mpt_client, agreement, dry_run=False, sync_prices=False)

    mock_adobe_client.get_customer.assert_called_once()
    mocked_notifier.assert_called_once()
    assert mocked_notifier.call_args_list[0].args[0] == agreement["id"]


def test_sync_agreement_notify_exception(
    mocker,
    agreement_factory,
):
    mock_notify_agreement_unhandled_exception_in_teams = mocker.patch(
        "adobe_vipm.flows.sync.notify_agreement_unhandled_exception_in_teams"
    )
    mocker.patch(
        "adobe_vipm.flows.sync.get_adobe_customer_id",
        side_effect=Exception("Test exception"),
    )
    mpt_client = mocker.MagicMock()
    agreement = agreement_factory()
    sync_agreement(mpt_client, agreement, dry_run=False, sync_prices=False)
    mock_notify_agreement_unhandled_exception_in_teams.assert_called_once()
    assert (
        mock_notify_agreement_unhandled_exception_in_teams.call_args_list[0].args[0]
        == agreement["id"]
    )


def test_sync_agreement_empty_discounts(
    mocker,
    agreement_factory,
    subscriptions_factory,
    adobe_customer_factory,
    caplog,
):
    agreement = agreement_factory(
        subscriptions=[
            {
                "id": "SUB-1000-2000-3000",
                "status": "Active",
                "item": {
                    "id": "ITM-0000-0001-0001",
                },
            },
        ],
    )

    mocked_mpt_client = mocker.MagicMock()
    mocked_adobe_client = mocker.MagicMock()

    customer = adobe_customer_factory()
    customer["discounts"] = []

    mocked_adobe_client.get_customer.return_value = customer

    mocker.patch(
        "adobe_vipm.flows.sync.get_adobe_client",
        return_value=mocked_adobe_client,
    )

    mocked_notifier = mocker.patch(
        "adobe_vipm.flows.sync.notify_agreement_unhandled_exception_in_teams",
    )

    sync_agreement(mocked_mpt_client, agreement, dry_run=False, sync_prices=False)

    mocked_notifier.assert_called_once()
    assert mocked_notifier.call_args_list[0].args[0] == agreement["id"]
    assert "does not have discounts information" in mocked_notifier.call_args_list[0].args[1]


@freeze_time("2025-06-19")
def test_sync_agreement_prices_with_missing_prices(
    mocker,
    agreement_factory,
    subscriptions_factory,
    lines_factory,
    adobe_subscription_factory,
    adobe_customer_factory,
    mock_get_adobe_product_by_marketplace_sku,
    mock_terminate_subscription,
    mock_mpt_client,
    mock_adobe_client,
    caplog,
    mock_update_agreement_subscription,
    mock_get_agreement_subscription,
    mock_get_template_by_name,
):
    agreement = agreement_factory(
        lines=lines_factory(
            external_vendor_id="77777777CA",
            unit_purchase_price=10.11,
        ),
        subscriptions=[
            {
                "id": "SUB-1000-2000-3000",
                "status": "Active",
                "item": {
                    "id": "ITM-0000-0001-0001",
                },
            },
            {
                "id": "SUB-1000-2000-5000",
                "status": "Active",
                "item": {
                    "id": "ITM-0000-0001-0003",
                },
            },
            {
                "id": "SUB-1000-2000-6000",
                "status": "Active",
                "item": {
                    "id": "ITM-0000-0001-0004",
                },
            },
        ],
    )

    mpt_subscription = subscriptions_factory()[0]
    another_mpt_subscription = subscriptions_factory(
        adobe_sku="77777777CA01A12",
        adobe_subscription_id="b-sub-id",
        subscription_id="SUB-1000-2000-5000",
    )[0]
    terminated_mpt_subscription = subscriptions_factory(
        adobe_sku="77777777CA01A13",
        adobe_subscription_id="c-sub-id",
        subscription_id="SUB-1000-2000-6000",
    )[0]

    adobe_subscription = adobe_subscription_factory()
    another_adobe_subscription = adobe_subscription_factory(
        subscription_id="b-sub-id",
        offer_id="77777777CA01A12",
        current_quantity=15,
        renewal_quantity=15,
    )
    terminated_adobe_subscription = adobe_subscription_factory(
        subscription_id="c-sub-id",
        offer_id="77777777CA01A13",
        current_quantity=10,
        renewal_quantity=10,
        status="1004",
    )
    mock_adobe_client.get_subscriptions.return_value = {
        "items": [
            adobe_subscription,
            another_adobe_subscription,
            terminated_adobe_subscription,
        ]
    }
    mock_adobe_client.get_customer.return_value = adobe_customer_factory(coterm_date="2025-04-04")

    mocker.patch(
        "adobe_vipm.flows.sync.get_adobe_client",
        return_value=mock_adobe_client,
    )

    mocker.patch(
        "adobe_vipm.flows.sync.get_agreement_subscription",
        side_effect=[
            mpt_subscription,
            another_mpt_subscription,
            terminated_mpt_subscription,
        ],
    )

    mocker.patch(
        "adobe_vipm.airtable.models.get_prices_for_skus",
        side_effect=[
            {"77777777CA01A12": 20.22},
            {"77777777CA01A12": 20.22},
        ],
    )

    mocked_notify_missing_prices = mocker.patch(
        "adobe_vipm.flows.sync.notify_missing_prices",
    )

    mocked_update_agreement_subscription = mocker.patch(
        "adobe_vipm.flows.sync.update_agreement_subscription",
    )
    mocked_update_agreement = mocker.patch(
        "adobe_vipm.flows.sync.update_agreement",
    )
    mock_get_template_by_name.side_effect = [
        {"id": "TPL-2345", "name": "Expired"},
        {"id": "TPL-1234", "name": "Renewing"},
    ]

    with caplog.at_level(logging.ERROR):
        sync_agreement(mock_mpt_client, agreement, dry_run=False, sync_prices=True)

    assert "Skipping subscription" in caplog.text
    assert "65304578CA01A12" in caplog.text

    mocked_notify_missing_prices.assert_called_once()
    call_args = mocked_notify_missing_prices.call_args[0]
    assert call_args[0] == agreement["id"]
    assert "65304578CA01A12" in call_args[1]
    assert call_args[2] == agreement["product"]["id"]
    assert call_args[3] == agreement["listing"]["priceList"]["currency"]

    mocked_update_agreement.call_args_list = [
        mocker.call(
            mock_mpt_client,
            agreement["id"],
            lines=agreement["lines"],
        ),
        mocker.call(
            mock_mpt_client,
            agreement["id"],
            parameters={"fulfillment": [{"externalId": "lastSyncDate", "value": "2025-06-19"}]},
        ),
    ]

    mock_adobe_client.get_subscriptions.assert_called_once_with("AUT-1234-5678", "a-client-id")

    assert mocked_update_agreement_subscription.mock_calls == [
        mocker.call(
            mock_mpt_client,
            terminated_mpt_subscription["id"],
            template={"id": "TPL-2345", "name": "Expired"},
        ),
        mocker.call(
            mock_mpt_client,
            another_mpt_subscription["id"],
            lines=[
                {"price": {"unitPP": 20.22}, "id": "ALI-2119-4550-8674-5962-0001", "quantity": 15}
            ],
            parameters={
                "fulfillment": [
                    {"externalId": Param.ADOBE_SKU.value, "value": "77777777CA01A12"},
                    {"externalId": Param.CURRENT_QUANTITY.value, "value": "15"},
                    {"externalId": Param.RENEWAL_QUANTITY.value, "value": "15"},
                    {"externalId": Param.RENEWAL_DATE.value, "value": "2026-06-20"},
                    {"externalId": Param.LAST_SYNC_DATE.value, "value": "2025-06-19"},
                ]
            },
            commitmentDate="2025-04-04",
            autoRenew=True,
            template={"id": "TPL-1234", "name": "Renewing"},
        ),
    ]
    mock_terminate_subscription.assert_called_once_with(
        mock_mpt_client, "SUB-1000-2000-6000", "Adobe subscription status 1004."
    )


@pytest.mark.usefixtures("mock_get_agreements_by_customer_deployments")
def test_sync_agreement_lost_customer(
    mocker,
    mock_mpt_client,
    mock_adobe_client,
    agreement_factory,
    mock_send_notification,
    mock_terminate_subscription,
    caplog,
):
    mock_adobe_client.get_customer.side_effect = AdobeAPIError(
        status_code=int(AdobeStatus.INVALID_CUSTOMER.value),
        payload={"code": "1116", "message": "Invalid Customer", "additionalDetails": []},
    )

    sync_agreement(mock_mpt_client, agreement_factory(), dry_run=False, sync_prices=False)

    assert mock_terminate_subscription.mock_calls == [
        mocker.call(mock_mpt_client, "SUB-1000-2000-3000", "Suspected Lost Customer"),
        mocker.call(mock_mpt_client, "SUB-1000-2000-3000", "Suspected Lost Customer"),
        mocker.call(mock_mpt_client, "SUB-1000-2000-3000", "Suspected Lost Customer"),
    ]
    assert mock_send_notification.mock_calls == [
        mocker.call(
            "Executing Lost Customer Procedure.",
            "Received Adobe error 1116 - Invalid Customer, assuming lost customer and proceeding"
            " with lost customer procedure.",
            "FFA500",
        )
    ]
    assert [rec.message for rec in caplog.records] == [
        "Synchronizing agreement AGR-2119-4550-8674-5962...",
        "Received Adobe error 1116 - Invalid Customer, assuming lost customer and"
        " proceeding with lost customer procedure.",
        "> Suspected Lost Customer: Terminating subscription SUB-1000-2000-3000.",
    ]


@pytest.mark.usefixtures("mock_get_agreements_by_customer_deployments")
def test_sync_agreement_lost_customer_error(
    mocker,
    mock_mpt_client,
    mock_adobe_client,
    mpt_error_factory,
    agreement_factory,
    mock_send_notification,
    mock_terminate_subscription,
    caplog,
):
    mock_adobe_client.get_customer.side_effect = AdobeAPIError(
        status_code=int(AdobeStatus.INVALID_CUSTOMER.value),
        payload={"code": "1116", "message": "Invalid Customer", "additionalDetails": []},
    )
    mock_terminate_subscription.side_effect = [
        MPTAPIError(500, mpt_error_factory(500, "Internal Server Error", "Oops!")),
        MPTAPIError(500, mpt_error_factory(500, "Internal Server Error", "Oops!")),
        MPTAPIError(500, mpt_error_factory(500, "Internal Server Error", "Oops!")),
        MPTAPIError(500, mpt_error_factory(500, "Internal Server Error", "Oops!")),
        MPTAPIError(500, mpt_error_factory(500, "Internal Server Error", "Oops!")),
        MPTAPIError(500, mpt_error_factory(500, "Internal Server Error", "Oops!")),
    ]

    sync_agreement(mock_mpt_client, agreement_factory(), dry_run=False, sync_prices=False)

    assert mock_terminate_subscription.mock_calls == [
        mocker.call(mock_mpt_client, "SUB-1000-2000-3000", "Suspected Lost Customer"),
        mocker.call(mock_mpt_client, "SUB-1000-2000-3000", "Suspected Lost Customer"),
        mocker.call(mock_mpt_client, "SUB-1000-2000-3000", "Suspected Lost Customer"),
    ]
    assert mock_send_notification.mock_calls == [
        mocker.call(
            "Executing Lost Customer Procedure.",
            "Received Adobe error 1116 - Invalid Customer, assuming lost customer and proceeding"
            " with lost customer procedure.",
            "FFA500",
        ),
        mocker.call(
            "🔥 > Suspected Lost Customer: Error terminating subscription SUB-1000-2000-3000",
            "500 Internal Server Error - Oops!"
            " (00-27cdbfa231ecb356ab32c11b22fd5f3c-721db10d009dfa2a-00)",
            "#541c2e",
            button=None,
            facts=None,
        ),
        mocker.call(
            "🔥 > Suspected Lost Customer: Error terminating subscription SUB-1000-2000-3000",
            "500 Internal Server Error - Oops!"
            " (00-27cdbfa231ecb356ab32c11b22fd5f3c-721db10d009dfa2a-00)",
            "#541c2e",
            button=None,
            facts=None,
        ),
        mocker.call(
            "🔥 > Suspected Lost Customer: Error terminating subscription SUB-1000-2000-3000",
            "500 Internal Server Error - Oops!"
            " (00-27cdbfa231ecb356ab32c11b22fd5f3c-721db10d009dfa2a-00)",
            "#541c2e",
            button=None,
            facts=None,
        ),
    ]

    assert [rec.message for rec in caplog.records] == [
        "Synchronizing agreement AGR-2119-4550-8674-5962...",
        "Received Adobe error 1116 - Invalid Customer, assuming lost customer and"
        " proceeding with lost customer procedure.",
        "> Suspected Lost Customer: Terminating subscription SUB-1000-2000-3000.",
        "> Suspected Lost Customer: Error terminating subscription SUB-1000-2000-3000.",
        "> Suspected Lost Customer: Error terminating subscription SUB-1000-2000-3000.",
        "> Suspected Lost Customer: Error terminating subscription SUB-1000-2000-3000.",
    ]


@pytest.mark.parametrize(
    "status",
    (s.value for s in AgreementStatus if s is not AgreementStatus.ACTIVE),
)
def test_sync_agreement_skips_inactive_agreement(
    mock_mpt_client, mock_get_adobe_client, mock_update_last_sync_date, status
):
    agreement = {"id": "1", "status": status, "subscriptions": []}

    sync_agreement(mock_mpt_client, agreement, dry_run=False, sync_prices=False)

    mock_update_last_sync_date.assert_not_called()


def test_get_subscriptions_for_update_skip_adobe_inactive(
    mock_mpt_client,
    mock_adobe_client,
    adobe_customer_factory,
    agreement_factory,
    adobe_subscription_factory,
    mock_get_agreement_subscription,
):
    adobe_subscriptions = [
        adobe_subscription_factory(status=AdobeStatus.SUBSCRIPTION_TERMINATED.value)
    ]

    assert (
        _get_subscriptions_for_update(
            mock_mpt_client, agreement_factory(), adobe_customer_factory(), adobe_subscriptions
        )
        == []
    )


@freeze_time("2025-07-23")
def test_get_subscriptions_for_update_terminated(
    mocker,
    mock_mpt_client,
    mock_adobe_client,
    agreement_factory,
    subscriptions_factory,
    adobe_customer_factory,
    adobe_subscription_factory,
    mock_terminate_subscription,
    mock_get_agreement_subscription,
    mock_update_agreement_subscription,
    mock_get_template_by_name,
):
    adobe_subscriptions = [
        adobe_subscription_factory(status=AdobeStatus.SUBSCRIPTION_TERMINATED.value)
    ]

    mock_get_template_by_name.return_value = {"id": "TPL-1234", "name": "Expired"}

    _get_subscriptions_for_update(
        mock_mpt_client, agreement_factory(), adobe_customer_factory(), adobe_subscriptions
    )

    mock_get_agreement_subscription.assert_called_once_with(
        mock_mpt_client, mock_get_agreement_subscription.return_value["id"]
    )
    mock_terminate_subscription.assert_called_once_with(
        mock_mpt_client,
        mock_get_agreement_subscription.return_value["id"],
        "Adobe subscription status 1004.",
    )

    mock_update_agreement_subscription.assert_has_calls([
        mocker.call(
            mock_mpt_client,
            mock_get_agreement_subscription.return_value["id"],
            template={"id": "TPL-1234", "name": "Expired"},
        ),
        mocker.call(
            mock_mpt_client,
            "SUB-1234-5678",
            template={"id": "TPL-1234", "name": "Expired"},
        ),
    ])


@freeze_time("2025-07-23")
def test_get_subscriptions_for_update_terminated_withoud_template(
    mock_mpt_client,
    mock_adobe_client,
    agreement_factory,
    subscriptions_factory,
    adobe_customer_factory,
    adobe_subscription_factory,
    mock_terminate_subscription,
    mock_get_agreement_subscription,
    mock_update_agreement_subscription,
    mock_get_template_by_name,
):
    adobe_subscriptions = [
        adobe_subscription_factory(status=AdobeStatus.SUBSCRIPTION_TERMINATED.value)
    ]

    mock_get_template_by_name.return_value = None

    _get_subscriptions_for_update(
        mock_mpt_client, agreement_factory(), adobe_customer_factory(), adobe_subscriptions
    )

    mock_get_agreement_subscription.assert_called_once_with(
        mock_mpt_client, mock_get_agreement_subscription.return_value["id"]
    )
    mock_terminate_subscription.assert_called_once_with(
        mock_mpt_client,
        mock_get_agreement_subscription.return_value["id"],
        "Adobe subscription status 1004.",
    )
    mock_update_agreement_subscription.assert_not_called()


def test_add_missing_subscriptions_none(
    mock_mpt_client,
    mock_adobe_client,
    agreement,
    agreement_factory,
    assets_factory,
    adobe_customer_factory,
    adobe_subscription_factory,
    mock_get_product_items_by_period,
    mock_create_asset,
    mock_create_agreement_subscription,
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
    mock_get_product_items_by_period.return_value = []

    _add_missing_subscriptions(
        mock_mpt_client,
        mock_adobe_client,
        adobe_customer_factory(),
        agreement_factory(),
        adobe_subscriptions=adobe_subscriptions,
    )

    mock_get_product_items_by_period.assert_not_called()
    mock_create_asset.assert_not_called()
    mock_create_agreement_subscription.assert_not_called()


def test_add_missing_subscriptions_without_vendor_id(
    mock_mpt_client,
    mock_adobe_client,
    agreement,
    agreement_factory,
    adobe_customer_factory,
    adobe_subscription_factory,
    mock_get_product_items_by_period,
    mock_get_product_items_by_skus,
    mock_create_agreement_subscription,
    mock_send_notification,
):
    adobe_subscriptions = [
        adobe_subscription_factory(subscription_id="a-sub-id", offer_id="65327701CA01A12"),
        adobe_subscription_factory(
            subscription_id = "55feb5038045e0b1ebf026e7522e17NA",
            offer_id = "65304578CA01A12",
            status = AdobeStatus.SUBSCRIPTION_TERMINATED,
        ),
        adobe_subscription_factory(
            subscription_id="1e5b9c974c4ea1bcabdb0fe697a2f1NA", offer_id="65304578CA01A12"
        ),
    ]

    agreement = agreement_factory()
    agreement["subscriptions"].append({
        "id": "SUB-1234-5678",
        "status": "1004",
    })

    mock_get_product_items_by_skus.return_value = []
    mock_get_product_items_by_period.return_value = []

    _add_missing_subscriptions(
        mock_mpt_client,
        mock_adobe_client,
        adobe_customer_factory(),
        agreement,
        adobe_subscriptions=adobe_subscriptions,
    )

    mock_send_notification.assert_called_once_with(
        "Missing external IDs",
        "Missing external IDs for entitlements: SUB-1234-5678 "
        "in the agreement AGR-2119-4550-8674-5962",
        TeamsColorCode.ORANGE.value,
    )
    mock_create_agreement_subscription.assert_not_called()


@freeze_time("2025-07-24")
def test_add_missing_subscriptions(
    mocker,
    items_factory,
    mock_mpt_client,
    mock_adobe_client,
    agreement_factory,
    adobe_customer_factory,
    mock_send_notification,
    mock_get_prices_for_skus,
    adobe_subscription_factory,
    mock_get_product_items_by_skus,
    mock_get_product_items_by_period,
    mock_create_asset,
    mock_create_agreement_subscription,
    mock_get_template_by_name,
):
    adobe_subscriptions = [
        adobe_subscription_factory(
            subscription_id="1e5b9c974c4ea1bcabdb0fe697a2f1NA", offer_id="65322572CAT1A10"
        ),
        adobe_subscription_factory(
            subscription_id="2e5b9c974c4ea1bcabdb0fe697a2f1NA", offer_id="65322572CAT1A13"
        ),
        adobe_subscription_factory(
            subscription_id="ae5b9c974c4ea1bcabdb0fe697a2f1NA", offer_id="75322572CAT1A11"
        ),
    ]
    mock_get_prices_for_skus.side_effect = [
        {
            "65322572CAT1A10": 12.14,
            "65322572CAT1A11": 11.14,
            "65322572CAT1A12": 10.14,
            "65322572CAT1A13": 9.14,
        },
        {"75322572CAT1A11": 22.14},
    ]
    mock_yearly_item = items_factory(item_id=193, external_vendor_id="65322572CA")[0]
    mock_one_time_item = items_factory(
        item_id=194,
        name="One time item",
        external_vendor_id="75322572CA",
        term_period=ItemTermsModel.ONE_TIME.value,
        term_model=ItemTermsModel.ONE_TIME.value,
    )[0]
    mock_mpt_get_asset_template_by_name = mocker.patch(
    "adobe_vipm.flows.sync.get_asset_template_by_name", return_value=None
    )
    mock_get_product_items_by_skus.return_value = [mock_yearly_item, mock_one_time_item]
    mock_get_product_items_by_period.return_value = [mock_yearly_item, mock_one_time_item]

    mock_get_template_by_name.return_value = {"id": "TPL-1234", "name": "Renewing"}

    _add_missing_subscriptions(
        mock_mpt_client,
        mock_adobe_client,
        adobe_customer_factory(),
        agreement_factory(),
        adobe_subscriptions=adobe_subscriptions,
    )

    mock_get_product_items_by_skus.assert_called_once_with(
        mock_mpt_client, "PRD-1111-1111", {"65322572CA", "75322572CA"}
    )
    mock_get_product_items_by_period.assert_not_called()
    mock_mpt_get_asset_template_by_name.assert_called_once_with(
        mock_mpt_client, "PRD-1111-1111", TEMPLATE_ASSET_DEFAULT
    )
    mock_create_asset.assert_called_once_with(
        mock_mpt_client,
        {
            "status": "Active",
            "name": "Asset for One time item",
            "agreement": {"id": "AGR-2119-4550-8674-5962"},
            "parameters": {
                "fulfillment": [
                    {"externalId": "adobeSKU", "value": "75322572CAT1A11"},
                    {"externalId": "currentQuantity", "value": "10"},
                    {"externalId": "usedQuantity", "value": "10"},
                ]
            },
            "externalIds": {"vendor": "ae5b9c974c4ea1bcabdb0fe697a2f1NA"},
            "lines": [{"quantity": 10, "item": mock_one_time_item, "price": {"unitPP": 22.14}}],
            "startDate": "2019-05-20T22:49:55Z",
            "product": {"id": "PRD-1111-1111"},
            "buyer": {"id": "BUY-3731-7971"},
            "licensee": {"id": "LC-321-321-321"},
            "seller": {"id": "SEL-9121-8944"},
            "template": None,
        },
    )
    mock_create_agreement_subscription.assert_called_once_with(
        mock_mpt_client,
        {
            "status": "Active",
            "commitmentDate": "2026-07-25",
            "price": {
                "unitPP": {
                    "65322572CAT1A10": 12.14,
                    "65322572CAT1A11": 11.14,
                    "65322572CAT1A12": 10.14,
                    "65322572CAT1A13": 9.14,
                }
            },
            "parameters": {
                "fulfillment": [
                    {"externalId": "adobeSKU", "value": "65322572CAT1A13"},
                    {"externalId": "currentQuantity", "value": "10"},
                    {"externalId": "renewalQuantity", "value": "10"},
                    {"externalId": "renewalDate", "value": "2026-07-25"},
                ]
            },
            "agreement": {"id": "AGR-2119-4550-8674-5962"},
            "buyer": {"id": "BUY-3731-7971"},
            "licensee": {"id": "LC-321-321-321"},
            "seller": {"id": "SEL-9121-8944"},
            "lines": [
                {
                    "quantity": 10,
                    "item": mock_yearly_item,
                    "price": {"unitPP": 9.14},
                }
            ],
            "name": ("Subscription for Awesome product"),
            "startDate": "2019-05-20T22:49:55Z",
            "externalIds": {"vendor": "2e5b9c974c4ea1bcabdb0fe697a2f1NA"},
            "product": {"id": "PRD-1111-1111"},
            "autoRenew": True,
            "template": {"id": "TPL-1234", "name": "Renewing"},
        },
    )


@freeze_time("2025-07-24")
def test_add_missing_subscriptions_deployment(
    mocker,
    items_factory,
    mock_mpt_client,
    mock_adobe_client,
    agreement_factory,
    adobe_customer_factory,
    mock_send_notification,
    mock_get_prices_for_skus,
    adobe_subscription_factory,
    mock_get_product_items_by_skus,
    fulfillment_parameters_factory,
    mock_create_asset,
    mock_create_agreement_subscription,
    mock_get_template_by_name,
):
    adobe_subscriptions = [
        adobe_subscription_factory(
            subscription_id="1e5b9c974c4ea1bcabdb0fe697a2f1NA",
            offer_id="65322572CAT1A10",
            deployment_id="deploymentId",
        ),
        adobe_subscription_factory(
            subscription_id="2e5b9c974c4ea1bcabdb0fe697a2f1NA",
            offer_id="65322572CAT1A13",
            deployment_id="deploymentId",
        ),
        adobe_subscription_factory(
            subscription_id="ae5b9c974c4ea1bcabdb0fe697a2f1NA",
            offer_id="75322572CAT1A11",
            deployment_id="deploymentId",
        ),
    ]
    mock_get_prices_for_skus.side_effect = [
        {
            "65322572CAT1A10": 12.14,
            "65322572CAT1A11": 11.14,
            "65322572CAT1A12": 10.14,
            "65322572CAT1A13": 9.14,
        },
        {"75322572CAT1A11": 22.14},
    ]
    mock_yearly_item = items_factory(item_id=193, external_vendor_id="65322572CA")[0]
    mock_one_time_item = items_factory(
        item_id=194,
        name="One time item",
        external_vendor_id="75322572CA",
        term_period=ItemTermsModel.ONE_TIME.value,
        term_model=ItemTermsModel.ONE_TIME.value,
    )[0]
    mock_get_product_items_by_skus.return_value = [mock_yearly_item, mock_one_time_item]
    agreement = agreement_factory(
        fulfillment_parameters=fulfillment_parameters_factory(deployment_id="deploymentId")
    )
    mock_mpt_get_asset_template_by_name = mocker.patch(
        "adobe_vipm.flows.sync.get_asset_template_by_name",
        return_value={"id": "fake_id", "name": "fake_name"}
    )
    mock_get_template_by_name.return_value = {"id": "TPL-1234", "name": "Renewing"}

    _add_missing_subscriptions(
        mock_mpt_client,
        mock_adobe_client,
        adobe_customer_factory(),
        agreement,
        adobe_subscriptions=adobe_subscriptions,
    )

    mock_get_product_items_by_skus.assert_called_once_with(
        mock_mpt_client, "PRD-1111-1111", {"65322572CA", "75322572CA"}
    )
    mock_mpt_get_asset_template_by_name.assert_called_once_with(
        mock_mpt_client, "PRD-1111-1111", TEMPLATE_ASSET_DEFAULT
    )
    mock_create_asset.assert_called_once_with(
        mock_mpt_client,
        {
            "status": "Active",
            "name": "Asset for One time item",
            "agreement": {"id": "AGR-2119-4550-8674-5962"},
            "parameters": {
                "fulfillment": [
                    {"externalId": "adobeSKU", "value": "75322572CAT1A11"},
                    {"externalId": "currentQuantity", "value": "10"},
                    {"externalId": "usedQuantity", "value": "10"},
                ]
            },
            "externalIds": {"vendor": "ae5b9c974c4ea1bcabdb0fe697a2f1NA"},
            "lines": [{"quantity": 10, "item": mock_one_time_item, "price": {"unitPP": 22.14}}],
            "startDate": "2019-05-20T22:49:55Z",
            "product": {"id": "PRD-1111-1111"},
            "buyer": {"id": "BUY-3731-7971"},
            "licensee": {"id": "LC-321-321-321"},
            "seller": {"id": "SEL-9121-8944"},
            "template": {"id": "fake_id", "name": "fake_name"},
        },
    )
    mock_create_agreement_subscription.assert_called_once_with(
        mock_mpt_client,
        {
            "status": "Active",
            "commitmentDate": "2026-07-25",
            "price": {
                "unitPP": {
                    "65322572CAT1A10": 12.14,
                    "65322572CAT1A11": 11.14,
                    "65322572CAT1A12": 10.14,
                    "65322572CAT1A13": 9.14,
                }
            },
            "parameters": {
                "fulfillment": [
                    {"externalId": "adobeSKU", "value": "65322572CAT1A13"},
                    {"externalId": "currentQuantity", "value": "10"},
                    {"externalId": "renewalQuantity", "value": "10"},
                    {"externalId": "renewalDate", "value": "2026-07-25"},
                ]
            },
            "agreement": {"id": "AGR-2119-4550-8674-5962"},
            "buyer": {"id": "BUY-3731-7971"},
            "licensee": {"id": "LC-321-321-321"},
            "seller": {"id": "SEL-9121-8944"},
            "lines": [
                {
                    "quantity": 10,
                    "item": mock_yearly_item,
                    "price": {"unitPP": 9.14},
                }
            ],
            "name": ("Subscription for Awesome product"),
            "startDate": "2019-05-20T22:49:55Z",
            "externalIds": {"vendor": "2e5b9c974c4ea1bcabdb0fe697a2f1NA"},
            "product": {"id": "PRD-1111-1111"},
            "autoRenew": True,
            "template": {"id": "TPL-1234", "name": "Renewing"},
        },
    )


@freeze_time("2025-07-27")
def test_add_missing_subscriptions_wrong_currency(
    mock_mpt_client,
    mock_adobe_client,
    agreement_factory,
    mock_send_exception,
    adobe_customer_factory,
    mock_send_notification,
    adobe_subscription_factory,
    mock_get_product_items_by_skus,
    mock_get_product_items_by_period,
    mock_create_asset,
    mock_create_agreement_subscription,
):
    adobe_subscriptions = [
        adobe_subscription_factory(
            subscription_id="2e5b9c974c4ea1bcabdb0fe697a2f1NA",
            currency_code="GBP",
            offer_id="65322572CAT1A13",
        )
    ]

    _add_missing_subscriptions(
        mock_mpt_client,
        mock_adobe_client,
        adobe_customer_factory(),
        agreement_factory(),
        adobe_subscriptions=adobe_subscriptions,
    )

    mock_get_product_items_by_skus.assert_called_once_with(
        mock_mpt_client, "PRD-1111-1111", {"65322572CA"}
    )
    mock_adobe_client.update_subscription.assert_called_once_with(
        "AUT-1234-5678", "a-client-id", "2e5b9c974c4ea1bcabdb0fe697a2f1NA", auto_renewal=False
    )
    mock_send_exception.assert_called_once_with(
        title="Price currency mismatch detected!",
        text="{'subscriptionId': '2e5b9c974c4ea1bcabdb0fe697a2f1NA', 'offerId': '65322572CAT1A13', "
        "'currentQuantity': 10, 'usedQuantity': 10, 'currencyCode': 'GBP', 'autoRenewal': "
        "{'enabled': True, 'renewalQuantity': 10}, 'creationDate': "
        "'2019-05-20T22:49:55Z', 'renewalDate': '2026-07-28', 'status': "
        "'1000', 'deploymentId': ''}",
    )
    mock_create_asset.assert_not_called()
    mock_create_agreement_subscription.assert_not_called()


def test_process_orphaned_deployment_subscriptions(
    agreement_factory, adobe_subscription_factory, mock_adobe_client
):
    _process_orphaned_deployment_subscriptions(
        mock_adobe_client,
        "authorization_id",
        "customer_id",
        [agreement_factory()],
        [
            adobe_subscription_factory(subscription_id="a-sub-id", deployment_id="deployment_id"),
            adobe_subscription_factory(
                subscription_id="c-sub-id", deployment_id="deployment_id", autorenewal_enabled=False
            ),
            adobe_subscription_factory(subscription_id="b-sub-id", deployment_id=""),
        ],
    )

    mock_adobe_client.update_subscription.assert_called_once_with(
        "authorization_id", "customer_id", "a-sub-id", auto_renewal=False
    )


def test_process_orphaned_deployment_subscriptions_none(
    agreement_factory, adobe_subscription_factory, mock_adobe_client
):
    agreement = agreement_factory()

    _process_orphaned_deployment_subscriptions(
        mock_adobe_client,
        "authorization_id",
        "customer_id",
        [agreement],
        [
            adobe_subscription_factory(
                subscription_id=agreement["subscriptions"][0]["externalIds"]["vendor"],
                deployment_id="deployment_id",
            )
        ],
    )

    mock_adobe_client.update_subscription.assert_not_called()


def test_process_orphaned_deployment_subscriptions_error(
    agreement_factory,
    adobe_subscription_factory,
    mock_adobe_client,
    mock_send_exception,
):
    mock_adobe_client.update_subscription.side_effect = Exception("Boom!")

    _process_orphaned_deployment_subscriptions(
        mock_adobe_client,
        "authorization_id",
        "customer_id",
        [agreement_factory()],
        [
            adobe_subscription_factory(subscription_id="a-sub-id", deployment_id="deployment_id"),
            adobe_subscription_factory(subscription_id="b-sub-id", deployment_id=""),
        ],
    )

    mock_send_exception.assert_called_once_with(
        "Error disabling auto-renewal for orphaned Adobe subscription a-sub-id.", "Boom!"
    )


def test_sync_agreement_without_subscriptions(
    mock_mpt_client,
    mock_adobe_client,
    agreement_factory,
    subscriptions_factory,
    lines_factory,
    adobe_subscription_factory,
    adobe_customer_factory,
    caplog,
):
    agreement = agreement_factory(
        lines=lines_factory(
            external_vendor_id="77777777CA",
            unit_purchase_price=10.11,
        )
    )
    adobe_subscription = adobe_subscription_factory()

    mock_adobe_client.get_subscription.return_value = adobe_subscription
    mock_adobe_client.get_subscriptions.return_value = {"items": []}
    mock_adobe_client.get_customer.return_value = adobe_customer_factory(coterm_date="2025-04-04")

    with caplog.at_level(logging.INFO):
        sync_agreement(mock_mpt_client, agreement, dry_run=True, sync_prices=True)

    assert "Skipping price sync - no subscriptions found for the customer" in caplog.text


def test_check_update_airtable_missing_deployments(
    mocker,
    agreement_factory,
    mock_send_notification,
    mock_airtable_base_info,
    adobe_deployment_factory,
    adobe_subscription_factory,
    fulfillment_parameters_factory,
    mock_get_gc_agreement_deployments_by_main_agreement,
    mock_get_gc_agreement_deployment_model
):
    deployments = [
        get_gc_agreement_deployment_model(AirTableBaseInfo(api_key="api-key", base_id="base-id"))(
            deployment_id=f"{i}"
        )
        for i in range(1, 4)
    ]
    mock_get_gc_agreement_deployments_by_main_agreement.return_value = deployments
    agreement = agreement_factory(
        fulfillment_parameters=fulfillment_parameters_factory(customer_id="P1005158636")
    )
    adobe_deployments = [
        adobe_deployment_factory(deployment_id=f"deployment-{i}") for i in range(1, 4)
    ]
    adobe_subscriptions = [
        adobe_subscription_factory(subscription_id=f"subscriptionId{i}") for i in range(3)
    ]
    mocker.patch(
        "adobe_vipm.airtable.models.get_transfer_by_authorization_membership_or_customer",
        side_effect=[
            mocker.MagicMock(
                name="Transfer", membership_id="membership_id", transfer_id="transfer_id"
            )
            for _ in range(2)
        ]
        + [None],
        spec=True,
    )

    _check_update_airtable_missing_deployments(agreement, adobe_deployments, adobe_subscriptions)

    assert mock_get_gc_agreement_deployment_model.mock_calls[:2] == [
        mocker.call(
            deployment_id="deployment-1",
            main_agreement_id="AGR-2119-4550-8674-5962",
            account_id="ACC-9121-8944",
            seller_id="SEL-9121-8944",
            product_id="PRD-1111-1111",
            membership_id="membership_id",
            transfer_id="transfer_id",
            status="pending",
            customer_id="P1005158636",
            deployment_currency=None,
            deployment_country="DE",
            licensee_id="LC-321-321-321",
        ),
        mocker.call(
            deployment_id="deployment-2",
            main_agreement_id="AGR-2119-4550-8674-5962",
            account_id="ACC-9121-8944",
            seller_id="SEL-9121-8944",
            product_id="PRD-1111-1111",
            membership_id="membership_id",
            transfer_id="transfer_id",
            status="pending",
            customer_id="P1005158636",
            deployment_currency=None,
            deployment_country="DE",
            licensee_id="LC-321-321-321",
        )
    ]
    assert mock_get_gc_agreement_deployment_model.mock_calls[2][0] == "batch_save"
    assert len(mock_get_gc_agreement_deployment_model.mock_calls[2].args[0]) == 2
    mock_send_notification.assert_called_once()


def test_check_update_airtable_missing_deployments_none(
    agreement_factory,
    mock_send_notification,
    mock_airtable_base_info,
    adobe_subscription_factory,
    mock_create_gc_agreement_deployments,
    mock_get_gc_agreement_deployments_by_main_agreement,
):
    deployments = [
        get_gc_agreement_deployment_model(AirTableBaseInfo(api_key="api-key", base_id="base-id"))(
            deployment_id=f"deployment-{i}"
        )
        for i in range(1, 4)
    ]
    mock_get_gc_agreement_deployments_by_main_agreement.return_value = deployments
    adobe_subscriptions = [
        adobe_subscription_factory(subscription_id=f"subscriptionId{i}") for i in range(4)
    ]

    _check_update_airtable_missing_deployments(
        agreement_factory(),
        [
            {"deploymentId": "deployment-1"},
            {"deploymentId": "deployment-2"},
            {"deploymentId": "deployment-3"},
        ],
        adobe_subscriptions,
    )

    mock_create_gc_agreement_deployments.assert_not_called()
    mock_send_notification.assert_not_called()
