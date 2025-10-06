import logging

import pytest
from freezegun import freeze_time

from adobe_vipm.adobe.constants import AdobeStatus
from adobe_vipm.adobe.errors import AdobeAPIError
from adobe_vipm.airtable.models import AirTableBaseInfo, get_gc_agreement_deployment_model
from adobe_vipm.flows.constants import AgreementStatus, ItemTermsModel, Param
from adobe_vipm.flows.errors import MPTAPIError
from adobe_vipm.flows.sync.agreement import AgreementSyncer

pytestmark = pytest.mark.usefixtures("mock_adobe_config")


@pytest.fixture
def mock_create_asset(mocker):
    return mocker.patch("mpt_extension_sdk.mpt_http.mpt.create_asset", spec=True)


@pytest.fixture
def mock_create_agreement_subscription(mocker):
    return mocker.patch("mpt_extension_sdk.mpt_http.mpt.create_agreement_subscription", spec=True)


@pytest.fixture
def mock_get_template_by_name(mocker):
    return mocker.patch("mpt_extension_sdk.mpt_http.mpt.get_template_by_name", spec=True)


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
    mock_update_agreement,
    mock_get_template_by_name,
    mocked_agreement_syncer,
    mock_add_missing_subscriptions,
):
    agreement = agreement_factory(
        lines=lines_factory(external_vendor_id="77777777CA", unit_purchase_price=10.11),
        subscriptions=[
            {
                "id": "SUB-1000-2000-3000",
                "status": "Active",
                "item": {"id": "ITM-0000-0001-0001"},
                "externalIds": {"vendor": "ae5b9c974c4ea1bcabdb0fe697a2f1NA"},
            },
            {
                "id": "SUB-1234-5678",
                "status": "Terminated",
                "item": {"id": "ITM-0000-0001-0002"},
                "externalIds": {"vendor": "ae5b9c974c4ea1bcabdb0fe697a2f1NA"},
            },
            {
                "id": "SUB-1000-2000-5000",
                "status": "Active",
                "item": {"id": "ITM-0000-0001-0003"},
                "externalIds": {"vendor": "ae5b9c974c4ea1bcabdb0fe697a2f1NA"},
            },
        ],
    )
    mocked_agreement_syncer._agreement = agreement
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
    mocked_agreement_syncer._adobe_subscriptions = [adobe_subscription, another_adobe_subscription]
    mock_adobe_client.get_subscriptions.return_value = {
        "items": [adobe_subscription, another_adobe_subscription]
    }
    mocked_agreement_syncer._customer = adobe_customer_factory(coterm_date="2025-04-04")
    mock_get_agreement_subscription.side_effect = [mpt_subscription, another_mpt_subscription]
    mocker.patch(
        "adobe_vipm.airtable.models.get_prices_for_skus",
        side_effect=[
            {"65304578CA01A12": 1234.55, "77777777CA01A12": 20.22},
            {"65304578CA01A12": 1234.55, "77777777CA01A12": 20.22},
        ],
    )

    mock_get_template_by_name.return_value = {"id": "TPL-1234", "name": "Renewing"}

    mocked_agreement_syncer.sync(dry_run=False, sync_prices=True)

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
            commitmentDate="2024-01-23",
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
            commitmentDate="2024-01-23",
            autoRenew=another_adobe_subscription["autoRenewal"]["enabled"],
            template={"id": "TPL-1234", "name": "Renewing"},
        ),
    ])
    expected_lines = lines_factory(external_vendor_id="77777777CA", unit_purchase_price=20.22)
    mock_update_agreement.assert_has_calls([
        mocker.call(
            mock_mpt_client,
            agreement["id"],
            lines=expected_lines,
            parameters={"fulfillment": [{"externalId": "cotermDate", "value": "2024-01-23"}]},
        ),
        mocker.call(
            mock_mpt_client,
            agreement["id"],
            parameters={"fulfillment": [{"externalId": "lastSyncDate", "value": "2025-06-23"}]},
        ),
    ])


@freeze_time("2025-06-23")
def test_sync_agreement_update_agrement(
    mock_mpt_client,
    mocked_agreement_syncer,
    mock_get_agreement,
):
    mocked_agreement_syncer.sync(dry_run=False, sync_prices=True)

    mock_get_agreement.assert_called_once_with(
        mock_mpt_client, mocked_agreement_syncer._agreement["id"]
    )


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
    mock_update_agreement,
    mock_get_subscriptions_for_update,
    mocked_agreement_syncer,
    mock_update_asset,
):
    asset_id = "AST-1111-2222-3333"
    mock_asset = assets_factory(asset_id=asset_id, adobe_subscription_id="sub-one-time-id")[0]
    mocker.patch("mpt_extension_sdk.mpt_http.mpt.get_asset_by_id", return_value=mock_asset)
    mock_lines = lines_factory(external_vendor_id="65304578CA")
    agreement = agreement_factory(lines=mock_lines, assets=[mock_asset], subscriptions=[])
    mocked_agreement_syncer._agreement = agreement
    adobe_subscription = adobe_subscription_factory(
        subscription_id="sub-one-time-id",
        offer_id="65304578CA01A12",
        used_quantity=6,
    )
    mocked_agreement_syncer._adobe_subscriptions = [adobe_subscription]
    mock_adobe_client.get_subscriptions.return_value = {"items": [adobe_subscription]}
    mocked_agreement_syncer._customer = adobe_customer_factory(coterm_date="2025-04-04")
    mock_get_subscriptions_for_update.return_value = []

    mocked_agreement_syncer.sync(dry_run=False, sync_prices=False)

    mock_update_asset.assert_called_once_with(
        mock_mpt_client,
        asset_id,
        parameters={
            "fulfillment": [
                {"externalId": "usedQuantity", "value": "6"},
                {"externalId": "lastSyncDate", "value": "2025-06-23"},
            ]
        },
    )
    mock_update_agreement.assert_has_calls([
        mocker.call(
            mock_mpt_client,
            agreement["id"],
            lines=mock_lines,
            parameters={"fulfillment": [{"externalId": "cotermDate", "value": "2024-01-23"}]},
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
    mock_get_subscriptions_for_update,
    mocked_agreement_syncer,
    mock_update_asset,
    mock_add_missing_subscriptions,
):
    asset_id = "AST-1111-2222-3333"
    mock_asset = assets_factory(asset_id=asset_id, adobe_subscription_id="sub-one-time-id")[0]
    mocker.patch("mpt_extension_sdk.mpt_http.mpt.get_asset_by_id", return_value=mock_asset)
    mock_lines = lines_factory(external_vendor_id="65327701CA")
    mocked_agreement_syncer._agreement = agreement_factory(
        lines=mock_lines, assets=[mock_asset], subscriptions=[]
    )
    adobe_subscription = adobe_subscription_factory(
        subscription_id="sub-one-time-id",
        offer_id="65327701CA01A12",
        used_quantity=6,
    )
    mock_adobe_client.get_subscriptions.return_value = {"items": [adobe_subscription]}
    mock_adobe_client.get_customer.return_value = adobe_customer_factory(coterm_date="2025-04-04")
    mock_get_subscriptions_for_update.return_value = []

    mocked_agreement_syncer.sync(dry_run=True, sync_prices=False)

    mock_update_asset.assert_not_called()


@freeze_time("2025-06-23")
def test_sync_agreement_not_prices(
    mocker,
    lines_factory,
    mock_mpt_client,
    mock_adobe_client,
    agreement_factory,
    subscriptions_factory,
    adobe_customer_factory,
    mock_get_prices_for_skus,
    mock_get_template_by_name,
    adobe_subscription_factory,
    mock_get_agreement_subscription,
    mock_update_agreement_subscription,
    mocked_agreement_syncer,
    mock_get_product_items_by_skus,
):
    mock_get_template_by_name.return_value = {"id": "TPL-1234", "name": "Renewing"}
    mocked_agreement_syncer._customer = adobe_customer_factory(coterm_date="2025-04-04")
    mock_get_prices_for_skus.return_value = {"65304578CA01A12": 1234.55}
    agreement = agreement_factory(
        subscriptions=subscriptions_factory(
            adobe_subscription_id="1e5b9c974c4ea1bcabdb0fe697a2f1NA", lines=lines_factory()
        )
    )
    mock_adobe_client.get_subscriptions.return_value = {
        "items": [
            adobe_subscription_factory(
                subscription_id="1e5b9c974c4ea1bcabdb0fe697a2f1NA",
                offer_id="65304578CA01A12",
                used_quantity=6,
            )
        ]
    }
    mock_get_agreement_subscription.return_value = agreement["subscriptions"][0]
    mocked_agreement_syncer._agreement = agreement

    mocked_agreement_syncer.sync(dry_run=False, sync_prices=False)

    mock_update_agreement_subscription.assert_called_once_with(
        mock_mpt_client,
        "SUB-1000-2000-3000",
        autoRenew=True,
        commitmentDate="2024-01-23",
        lines=[{"id": "ALI-2119-4550-8674-5962-0001", "quantity": 10}],
        parameters={
            "fulfillment": [
                {"externalId": "adobeSKU", "value": "65304578CA01A12"},
                {"externalId": "currentQuantity", "value": "10"},
                {"externalId": "renewalQuantity", "value": "10"},
                {"externalId": "renewalDate", "value": "2026-10-11"},
                {"externalId": "lastSyncDate", "value": "2025-06-23"},
            ],
        },
        template={"id": "TPL-1234", "name": "Renewing"},
    )


def test_sync_agreement_prices_dry_run(
    mocker,
    mock_adobe_client,
    mock_mpt_client,
    agreement_factory,
    subscriptions_factory,
    lines_factory,
    adobe_subscription_factory,
    adobe_customer_factory,
    mock_get_adobe_product_by_marketplace_sku,
    mock_update_agreement,
    mock_update_agreement_subscription,
    mock_get_agreement_subscription,
    mocked_agreement_syncer,
):
    mocked_agreement_syncer._agreement = agreement_factory(
        lines=lines_factory(external_vendor_id="77777777CA", unit_purchase_price=10.11)
    )
    mpt_subscription = subscriptions_factory()[0]
    mocked_agreement_syncer._customer = adobe_customer_factory(coterm_date="2025-04-04")
    mock_get_agreement_subscription.return_value = mpt_subscription
    mocker.patch(
        "adobe_vipm.airtable.models.get_prices_for_skus",
        side_effect=[{"65327701CA01A12": 1234.55}, {"77777777CA01A12": 20.22}],
    )

    mocked_agreement_syncer.sync(dry_run=True, sync_prices=True)

    mock_get_agreement_subscription.assert_called_once_with(mock_mpt_client, mpt_subscription["id"])
    mock_update_agreement_subscription.assert_not_called()
    mock_update_agreement.assert_not_called()


def test_sync_agreement_prices_exception(
    mocker,
    mock_adobe_client,
    mock_mpt_client,
    agreement_factory,
    subscriptions_factory,
    adobe_api_error_factory,
    adobe_customer_factory,
    caplog,
    mock_update_agreement,
    mock_update_agreement_subscription,
    mock_get_agreement_subscription,
    lines_factory,
    adobe_subscription_factory,
    mocked_agreement_syncer,
):
    mpt_subscriptions = subscriptions_factory(
        adobe_subscription_id="1e5b9c974c4ea1bcabdb0fe697a2f1NA",
        lines=lines_factory(),
    )
    agreement = agreement_factory(subscriptions=mpt_subscriptions)
    mock_adobe_client.get_subscriptions.return_value = {
        "items": [
            adobe_subscription_factory(
                subscription_id="1e5b9c974c4ea1bcabdb0fe697a2f1NA",
                offer_id="65304578CA01A12",
                used_quantity=6,
            )
        ]
    }

    mock_update_agreement_subscription.side_effect = AdobeAPIError(
        400, adobe_api_error_factory(code="9999", message="Error from Adobe.")
    )
    mpt_subscription = mpt_subscriptions[0]
    mock_get_agreement_subscription.return_value = mpt_subscription
    mocked_notifier = mocker.patch(
        "adobe_vipm.flows.sync.agreement.notify_agreement_unhandled_exception_in_teams",
    )

    with caplog.at_level(logging.ERROR):
        mocked_agreement_syncer.sync(dry_run=False, sync_prices=True)

    assert f"Error synchronizing agreement {agreement['id']}" in caplog.text
    mock_get_agreement_subscription.assert_called_once_with(mock_mpt_client, mpt_subscription["id"])
    mock_update_agreement_subscription.assert_not_called()
    mock_update_agreement.assert_not_called()
    mocked_notifier.assert_called_once()
    assert mocked_notifier.call_args_list[0].args[0] == agreement["id"]


def test_sync_agreement_prices_skip_processing(
    mocker,
    mock_adobe_client,
    mock_mpt_client,
    agreement_factory,
    caplog,
    adobe_customer_factory,
    mock_update_agreement,
    mocked_agreement_syncer,
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
    mocked_agreement_syncer._agreement = agreement

    with caplog.at_level(logging.INFO):
        mocked_agreement_syncer.sync(dry_run=False, sync_prices=False)

    assert f"Agreement {agreement['id']} has processing subscriptions, skip it" in caplog.text

    mock_update_agreement.assert_not_called()


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
    mock_update_agreement,
    mock_get_template_by_name,
    mocked_agreement_syncer,
):
    agreement = agreement_factory(
        lines=lines_factory(external_vendor_id="77777777CA", unit_purchase_price=10.11)
    )
    mocked_agreement_syncer._agreement = agreement
    adobe_subscription = adobe_subscription_factory()
    mock_adobe_client.get_subscriptions.return_value = {"items": [adobe_subscription]}
    mock_adobe_client.get_customer.return_value = adobe_customer_factory(
        coterm_date="2025-04-04",
        commitment=adobe_commitment_factory(licenses=9, consumables=1220),
        recommitment_request=adobe_commitment_factory(status="ACCEPTED"),
    )
    mpt_subscription = subscriptions_factory()[0]
    mock_get_agreement_subscription.return_value = mpt_subscription
    mocker.patch(
        "adobe_vipm.airtable.models.get_prices_for_3yc_skus",
        side_effect=[{"65304578CA01A12": 1234.55}, {"77777777CA01A12": 20.22}],
    )

    mock_get_template_by_name.return_value = {"id": "TPL-1234", "name": "Renewing"}

    mocked_agreement_syncer.sync(dry_run=False, sync_prices=True)

    mock_get_agreement_subscription.assert_called_once_with(
        mock_mpt_client,
        mpt_subscription["id"],
    )
    mock_update_agreement_subscription.assert_called_once_with(
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
                    "value": str(adobe_subscription["autoRenewal"][Param.RENEWAL_QUANTITY.value]),
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
    )

    expected_lines = lines_factory(external_vendor_id="77777777CA", unit_purchase_price=20.22)

    assert mock_update_agreement.call_args_list == [
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
    dry_run,
    lines_factory,
    mock_mpt_client,
    mock_adobe_client,
    agreement_factory,
    mock_update_agreement,
    mock_get_adobe_client,
    subscriptions_factory,
    adobe_customer_factory,
    mock_get_prices_for_skus,
    mock_update_subscriptions,
    adobe_subscription_factory,
    fulfillment_parameters_factory,
    mock_add_missing_subscriptions,
    mock_get_adobe_product_by_marketplace_sku,
    mock_get_agreements_by_customer_deployments,
    mocked_agreement_syncer,
    mock_check_update_airtable_missing_deployments,
):
    agreement = agreement_factory(
        lines=lines_factory(external_vendor_id="77777777CA", unit_purchase_price=20.22),
        subscriptions=[
            {"id": "SUB-1000-2000-3000", "status": "Active", "item": {"id": "ITM-0000-0001-0001"}},
            {"id": "SUB-1234-5678", "status": "Terminated", "item": {"id": "ITM-0000-0001-0002"}},
            {"id": "SUB-1000-2000-5000", "status": "Active", "item": {"id": "ITM-0000-0001-0003"}},
        ],
    )
    mocked_agreement_syncer._agreement = agreement
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
            fulfillment_parameters=fulfillment_parameters_factory(
                global_customer="", deployment_id="deployment-1", deployments=""
            ),
            lines=lines_factory(external_vendor_id="77777777CA", unit_purchase_price=20.22),
        )
    ]
    mock_get_agreements_by_customer_deployments.return_value = deployment_agreements
    mock_get_prices_for_skus.return_value = {"65304578CA01A12": 1234.55, "77777777CA01A12": 20.22}

    mocked_agreement_syncer.sync(dry_run=dry_run, sync_prices=True)

    mock_add_missing_subscriptions.assert_called_once()
    expected_lines = lines_factory(external_vendor_id="77777777CA", unit_purchase_price=20.22)
    if not dry_run:
        assert mock_update_agreement.call_args_list == [
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
                deployment_agreements[0]["id"],
                parameters={"fulfillment": [{"externalId": "lastSyncDate", "value": "2025-06-19"}]},
            ),
        ]
    else:
        assert mock_update_agreement.call_args_list == [
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


@freeze_time("2025-06-30")
def test_sync_global_customer_update_not_required(
    mocker,
    mock_mpt_client,
    agreement_factory,
    mock_adobe_client,
    mock_update_agreement,
    adobe_customer_factory,
    mock_get_subscriptions_for_update,
    mock_get_agreements_by_customer_deployments,
    mocked_agreement_syncer,
    mock_check_update_airtable_missing_deployments,
):
    mock_get_subscriptions_for_update.return_value = []
    mock_get_agreements_by_customer_deployments.return_value = []
    mocked_agreement_syncer._agreement = agreement_factory(
        fulfillment_parameters=[
            {"externalId": "globalCustomer", "value": ["Yes"]},
            {"externalId": "deployments", "value": "deployment-id - DE"},
        ],
        subscriptions=[],
    )
    mock_adobe_client.get_customer.return_value = adobe_customer_factory(global_sales_enabled=True)
    mock_adobe_client.get_customer_deployments_active_status.return_value = [
        {
            "deploymentId": "deployment-id",
            "status": "1000",
            "companyProfile": {"address": {"country": "DE"}},
        }
    ]

    mocked_agreement_syncer.sync(dry_run=False, sync_prices=True)

    mock_update_agreement.assert_has_calls([
        mocker.call(
            mock_mpt_client,
            "AGR-2119-4550-8674-5962",
            lines=[],
            parameters={"fulfillment": [{"externalId": "cotermDate", "value": "2024-01-23"}]},
        ),
        mocker.call(
            mock_mpt_client,
            "AGR-2119-4550-8674-5962",
            parameters={"fulfillment": [{"externalId": "lastSyncDate", "value": "2025-06-30"}]},
        ),
    ])

    mock_adobe_client.get_customer_deployments_active_status.assert_called_once()


@freeze_time("2025-06-30")
def test_sync_global_customer_no_active_deployments(
    mocker,
    mock_mpt_client,
    agreement_factory,
    mock_adobe_client,
    mock_update_agreement,
    adobe_customer_factory,
    mock_add_missing_subscriptions,
    mock_get_subscriptions_for_update,
    mock_get_agreements_by_customer_deployments,
    mocked_agreement_syncer,
):
    mock_adobe_client.get_customer_deployments_active_status.return_value = []
    mock_get_subscriptions_for_update.return_value = []
    mock_adobe_client.get_customer.return_value = adobe_customer_factory(global_sales_enabled=True)

    mocked_agreement_syncer.sync(dry_run=False, sync_prices=True)

    mock_add_missing_subscriptions.assert_called_once()
    mock_get_subscriptions_for_update.assert_called()
    mock_get_agreements_by_customer_deployments.assert_not_called()
    mock_adobe_client.get_customer_deployments_active_status.assert_called_once()
    assert mock_update_agreement.mock_calls == [
        mocker.call(
            mock_mpt_client,
            "AGR-2119-4550-8674-5962",
            lines=[],
            parameters={"fulfillment": [{"externalId": "cotermDate", "value": "2024-01-23"}]},
        ),
        mocker.call(
            mock_mpt_client,
            "AGR-2119-4550-8674-5962",
            parameters={"fulfillment": [{"externalId": "globalCustomer", "value": ["Yes"]}]},
        ),
        mocker.call(
            mock_mpt_client,
            "AGR-2119-4550-8674-5962",
            parameters={"fulfillment": [{"externalId": "lastSyncDate", "value": "2025-06-30"}]},
        ),
    ]


@freeze_time("2025-06-30")
def test_sync_global_customer_update_adobe_error(
    adobe_api_error_factory,
    mock_adobe_client,
    mock_get_agreement_subscription,
    mocked_agreement_syncer,
    mock_notify_agreement_unhandled_exception_in_teams,
):
    mock_adobe_client.get_customer_deployments_active_status.side_effect = AdobeAPIError(
        400, adobe_api_error_factory("9999", "some error")
    )

    mocked_agreement_syncer.sync(dry_run=False, sync_prices=True)

    mock_notify_agreement_unhandled_exception_in_teams.assert_called_once()
    assert (
        mock_notify_agreement_unhandled_exception_in_teams.call_args_list[0].args[0]
        == mocked_agreement_syncer._agreement["id"]
    )


def test_sync_global_customer_parameters_error(
    mocker,
    caplog,
    mock_update_agreement,
    mocked_agreement_syncer,
    mock_notify_agreement_unhandled_exception_in_teams,
):
    mock_update_agreement.side_effect = AdobeAPIError(400, {"error": "some error"})

    with caplog.at_level(logging.ERROR):
        mocked_agreement_syncer._sync_global_customer_parameters([
            {
                "deploymentId": "deployment-id",
                "status": "1000",
                "companyProfile": {"address": {"country": "DE"}},
            }
        ])

    assert (
        caplog.records[0].message
        == "Error setting global customer parameters for agreement AGR-2119-4550-8674-5962."
    )


def test_sync_agreement_notify_exception(
    mocked_agreement_syncer,
    mock_add_missing_subscriptions,
    mock_notify_agreement_unhandled_exception_in_teams,
):
    mock_add_missing_subscriptions.side_effect = Exception("Test exception")

    mocked_agreement_syncer.sync(dry_run=False, sync_prices=False)

    mock_notify_agreement_unhandled_exception_in_teams.assert_called_once()
    assert (
        mock_notify_agreement_unhandled_exception_in_teams.call_args_list[0].args[0]
        == mocked_agreement_syncer._agreement["id"]
    )


def test_sync_agreement_empty_discounts(
    mocker,
    mock_adobe_client,
    mock_mpt_client,
    agreement_factory,
    subscriptions_factory,
    adobe_customer_factory,
    caplog,
    mocked_agreement_syncer,
):
    mocked_agreement_syncer._agreement = agreement_factory(
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
    customer = adobe_customer_factory()
    customer["discounts"] = []
    mock_adobe_client.get_customer.return_value = customer
    mocked_notifier = mocker.patch(
        "adobe_vipm.flows.sync.agreement.notify_agreement_unhandled_exception_in_teams"
    )

    mocked_agreement_syncer.sync(dry_run=False, sync_prices=False)

    mocked_notifier.assert_called_once()
    assert mocked_notifier.call_args_list[0].args[0] == mocked_agreement_syncer._agreement["id"]
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
    mock_update_agreement,
    mock_get_template_by_name,
    mocked_agreement_syncer,
    mock_add_missing_subscriptions,
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
                "item": {"id": "ITM-0000-0001-0001"},
                "externalIds": {"vendor": "ae5b9c974c4ea1bcabdb0fe697a2f1NA"},
            },
            {
                "id": "SUB-1000-2000-5000",
                "status": "Active",
                "item": {"id": "ITM-0000-0001-0003"},
                "externalIds": {"vendor": "ae5b9c974c4ea1bcabdb0fe697a2f1NA"},
            },
            {
                "id": "SUB-1000-2000-6000",
                "status": "Active",
                "item": {"id": "ITM-0000-0001-0004"},
                "externalIds": {"vendor": "ae5b9c974c4ea1bcabdb0fe697a2f1NA"},
            },
        ],
    )
    mocked_agreement_syncer._agreement = agreement
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
    mocked_agreement_syncer._adobe_subscriptions = [
        adobe_subscription,
        another_adobe_subscription,
        terminated_adobe_subscription,
    ]
    mocked_agreement_syncer._customer = adobe_customer_factory(coterm_date="2025-04-04")
    mock_get_agreement_subscription.side_effect = [
        mpt_subscription,
        another_mpt_subscription,
        terminated_mpt_subscription,
    ]
    mocker.patch(
        "adobe_vipm.airtable.models.get_prices_for_skus",
        side_effect=[
            {"77777777CA01A12": 20.22},
            {"77777777CA01A12": 20.22},
        ],
    )

    mocked_notify_missing_prices = mocker.patch(
        "adobe_vipm.flows.sync.agreement.notify_missing_prices"
    )

    mock_get_template_by_name.side_effect = [
        {"id": "TPL-2345", "name": "Expired"},
        {"id": "TPL-1234", "name": "Renewing"},
    ]

    with caplog.at_level(logging.ERROR):
        mocked_agreement_syncer.sync(dry_run=False, sync_prices=True)

    assert "Skipping subscription" in caplog.text
    assert "65304578CA01A12" in caplog.text
    mocked_notify_missing_prices.assert_called_once()
    call_args = mocked_notify_missing_prices.call_args[0]
    assert call_args[0] == agreement["id"]
    assert "65304578CA01A12" in call_args[1]
    assert call_args[2] == agreement["product"]["id"]
    assert call_args[3] == agreement["listing"]["priceList"]["currency"]

    mock_update_agreement.call_args_list = [
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
    assert mock_update_agreement_subscription.mock_calls == [
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
                    {"externalId": Param.RENEWAL_DATE.value, "value": "2026-10-11"},
                    {"externalId": Param.LAST_SYNC_DATE.value, "value": "2025-06-19"},
                ]
            },
            commitmentDate="2024-01-23",
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
    mocked_agreement_syncer,
    caplog,
):
    mock_adobe_client.get_customer.side_effect = AdobeAPIError(
        status_code=int(AdobeStatus.INVALID_CUSTOMER.value),
        payload={"code": "1116", "message": "Invalid Customer", "additionalDetails": []},
    )

    AgreementSyncer(mock_mpt_client, mock_adobe_client, agreement_factory()).sync(
        dry_run=False, sync_prices=True
    )

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
    assert caplog.messages == [
        "Synchronizing agreement AGR-2119-4550-8674-5962",
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
    mocked_agreement_syncer,
    caplog,
):
    mock_adobe_client.get_customer.side_effect = AdobeAPIError(
        status_code=int(AdobeStatus.INVALID_CUSTOMER.value),
        payload={"code": "1116", "message": "Invalid Customer", "additionalDetails": []},
    )
    mock_terminate_subscription.side_effect = MPTAPIError(
        500, mpt_error_factory(500, "Internal Server Error", "Oops!")
    )

    AgreementSyncer(mock_mpt_client, mock_adobe_client, agreement_factory()).sync(
        dry_run=False, sync_prices=True
    )

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
        "Synchronizing agreement AGR-2119-4550-8674-5962",
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
    mock_mpt_client,
    mock_get_adobe_client,
    mock_update_last_sync_date,
    mocked_agreement_syncer,
    status,
):
    mocked_agreement_syncer._agreement = {"id": "1", "status": status, "subscriptions": []}

    mocked_agreement_syncer.sync(dry_run=False, sync_prices=False)

    mock_update_last_sync_date.assert_not_called()


def test_get_subscriptions_for_update_skip_adobe_inactive(
    mock_mpt_client,
    mock_adobe_client,
    adobe_customer_factory,
    agreement_factory,
    adobe_subscription_factory,
    mock_get_agreement_subscription,
    mocked_agreement_syncer,
):
    mocked_agreement_syncer._adobe_subscriptions = [
        adobe_subscription_factory(status=AdobeStatus.SUBSCRIPTION_TERMINATED.value)
    ]

    assert mocked_agreement_syncer._get_subscriptions_for_update(agreement_factory()) == []


@freeze_time("2025-07-23")
def test_get_subscriptions_for_update_terminated(
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
    mocked_agreement_syncer,
):
    adobe_subscriptions = [
        adobe_subscription_factory(status=AdobeStatus.SUBSCRIPTION_TERMINATED.value)
    ]
    mock_get_template_by_name.return_value = {"id": "TPL-1234", "name": "Expired"}
    mocked_agreement_syncer._adobe_subscriptions = adobe_subscriptions

    mocked_agreement_syncer._get_subscriptions_for_update(agreement_factory())

    mock_get_agreement_subscription.assert_called_once_with(
        mock_mpt_client, mock_get_agreement_subscription.return_value["id"]
    )
    mock_terminate_subscription.assert_called_once_with(
        mock_mpt_client,
        mock_get_agreement_subscription.return_value["id"],
        "Adobe subscription status 1004.",
    )
    mock_update_agreement_subscription.assert_called_once_with(
        mock_mpt_client,
        mock_get_agreement_subscription.return_value["id"],
        template={"id": "TPL-1234", "name": "Expired"},
    )


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
    mocked_agreement_syncer,
):
    mocked_agreement_syncer._adobe_subscriptions = [
        adobe_subscription_factory(status=AdobeStatus.SUBSCRIPTION_TERMINATED.value)
    ]
    mock_get_template_by_name.return_value = None
    mock_get_template_by_name.return_value = {"id": "TPL-1234", "name": "Expired"}

    mocked_agreement_syncer._get_subscriptions_for_update(agreement_factory())

    mock_get_agreement_subscription.assert_called_once_with(
        mock_mpt_client, mock_get_agreement_subscription.return_value["id"]
    )
    mock_terminate_subscription.assert_called_once_with(
        mock_mpt_client,
        mock_get_agreement_subscription.return_value["id"],
        "Adobe subscription status 1004.",
    )
    mock_update_agreement_subscription.assert_called_once_with(
        mock_mpt_client,
        mock_get_agreement_subscription.return_value["id"],
        template={"id": "TPL-1234", "name": "Expired"},
    )


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
    mocked_agreement_syncer,
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
    mocked_agreement_syncer._adobe_subscriptions = adobe_subscriptions
    mock_get_product_items_by_period.return_value = []

    mocked_agreement_syncer._add_missing_subscriptions()

    mock_get_product_items_by_period.assert_not_called()
    mock_create_asset.assert_not_called()
    mock_create_agreement_subscription.assert_not_called()


@freeze_time("2025-07-24")
def test_add_missing_subscriptions(
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
    mocked_agreement_syncer,
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
    mocked_agreement_syncer._adobe_subscriptions = adobe_subscriptions
    mocked_agreement_syncer._customer = adobe_customer_factory()
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
    mock_get_product_items_by_period.return_value = [mock_yearly_item, mock_one_time_item]

    mock_get_template_by_name.return_value = {"id": "TPL-1234", "name": "Renewing"}

    mocked_agreement_syncer._add_missing_subscriptions()

    mock_get_product_items_by_skus.assert_called_once_with(
        mock_mpt_client, "PRD-1111-1111", {"65322572CA", "75322572CA"}
    )
    mock_get_product_items_by_period.assert_not_called()
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
        },
    )
    mock_create_agreement_subscription.assert_called_once_with(
        mock_mpt_client,
        {
            "status": "Active",
            "commitmentDate": "2026-10-11",
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
                    {"externalId": "renewalDate", "value": "2026-10-11"},
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
    mocked_agreement_syncer,
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
    mocked_agreement_syncer._adobe_subscriptions = adobe_subscriptions
    mocked_agreement_syncer._customer = adobe_customer_factory()
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
    mocked_agreement_syncer._agreement = agreement
    mock_get_template_by_name.return_value = {"id": "TPL-1234", "name": "Renewing"}

    mocked_agreement_syncer._add_missing_subscriptions()

    mock_get_product_items_by_skus.assert_called_once_with(
        mock_mpt_client, "PRD-1111-1111", {"65322572CA", "75322572CA"}
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
        },
    )
    mock_create_agreement_subscription.assert_called_once_with(
        mock_mpt_client,
        {
            "status": "Active",
            "commitmentDate": "2026-10-11",
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
                    {"externalId": "renewalDate", "value": "2026-10-11"},
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
    mocked_agreement_syncer,
):
    adobe_subscriptions = [
        adobe_subscription_factory(
            subscription_id="2e5b9c974c4ea1bcabdb0fe697a2f1NA",
            currency_code="GBP",
            offer_id="65322572CAT1A13",
        )
    ]
    mocked_agreement_syncer._adobe_subscriptions = adobe_subscriptions
    mocked_agreement_syncer._customer = adobe_customer_factory()

    mocked_agreement_syncer._add_missing_subscriptions()

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
        "'2019-05-20T22:49:55Z', 'renewalDate': '2026-10-11', 'status': "
        "'1000', 'deploymentId': ''}",
    )
    mock_create_asset.assert_not_called()
    mock_create_agreement_subscription.assert_not_called()


def test_process_orphaned_deployment_subscriptions(
    agreement_factory, adobe_subscription_factory, mock_adobe_client, mocked_agreement_syncer
):
    mocked_agreement_syncer._adobe_subscriptions = [
        adobe_subscription_factory(subscription_id="a-sub-id", deployment_id="deployment_id"),
        adobe_subscription_factory(subscription_id="b-sub-id", deployment_id=""),
    ]

    mocked_agreement_syncer._process_orphaned_deployment_subscriptions([agreement_factory()])

    mock_adobe_client.update_subscription.assert_called_once_with(
        "AUT-1234-5678", "a-client-id", "a-sub-id", auto_renewal=False
    )


def test_process_orphaned_deployment_subscriptions_none(
    agreement_factory,
    adobe_subscription_factory,
    mock_adobe_client,
    mocked_agreement_syncer,
    mock_agreement,
):
    mocked_agreement_syncer._adobe_subscriptions = []

    mocked_agreement_syncer._process_orphaned_deployment_subscriptions([mock_agreement])

    mock_adobe_client.update_subscription.assert_not_called()


def test_process_orphaned_deployment_subscriptions_error(
    agreement_factory,
    adobe_subscription_factory,
    mock_adobe_client,
    mock_send_exception,
    mocked_agreement_syncer,
):
    mock_adobe_client.update_subscription.side_effect = Exception("Boom!")
    mocked_agreement_syncer._adobe_subscriptions = [
        adobe_subscription_factory(subscription_id="a-sub-id", deployment_id="deployment_id"),
        adobe_subscription_factory(subscription_id="b-sub-id", deployment_id=""),
    ]

    mocked_agreement_syncer._process_orphaned_deployment_subscriptions([agreement_factory()])

    mock_send_exception.assert_called_once_with(
        "Error disabling auto-renewal for orphaned Adobe subscription a-sub-id.", "Boom!"
    )


def test_sync_agreement_without_subscriptions(mocked_agreement_syncer, mock_adobe_client, caplog):
    mock_adobe_client.get_subscriptions.return_value = {"items": []}

    with caplog.at_level(logging.INFO):
        mocked_agreement_syncer.sync(dry_run=True, sync_prices=True)

    assert "Skipping price sync - no subscriptions found for the customer" in caplog.text


def test_check_update_airtable_missing_deployments(
    mocker,
    mock_settings,
    mock_pymsteams,
    agreement_factory,
    mock_send_notification,
    mock_airtable_base_info,
    adobe_deployment_factory,
    adobe_subscription_factory,
    fulfillment_parameters_factory,
    mock_create_gc_agreement_deployments,
    mock_get_gc_agreement_deployment_model,
    mock_get_gc_agreement_deployments_by_main_agreement,
    mocked_agreement_syncer,
    adobe_customer_factory,
):
    mock_gc_agreement_deployment_model = mocker.MagicMock(name="GCAgreementDeployment")
    mock_get_gc_agreement_deployment_model.return_value = mock_gc_agreement_deployment_model
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
    mocked_agreement_syncer._agreement = agreement
    mocked_agreement_syncer._customer = adobe_customer_factory()
    adobe_deployments = [
        adobe_deployment_factory(deployment_id=f"deployment-{i}") for i in range(1, 4)
    ]
    mocked_agreement_syncer._adobe_subscriptions = [
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

    mocked_agreement_syncer._check_update_airtable_missing_deployments(adobe_deployments)

    mock_create_gc_agreement_deployments.assert_called_once_with(
        agreement["product"]["id"],
        [
            mock_gc_agreement_deployment_model.return_value,
            mock_gc_agreement_deployment_model.return_value,
        ],
    )
    mock_gc_agreement_deployment_model.assert_has_calls(
        (
            mocker.call(
                deployment_id="deployment-1",
                main_agreement_id="AGR-2119-4550-8674-5962",
                account_id="ACC-9121-8944",
                seller_id="SEL-9121-8944",
                product_id="PRD-1111-1111",
                membership_id="membership_id",
                transfer_id="transfer_id",
                status="pending",
                customer_id="a-client-id",
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
                customer_id="a-client-id",
                deployment_currency=None,
                deployment_country="DE",
                licensee_id="LC-321-321-321",
            ),
        ),
        any_order=True,
    )
    mock_send_notification.assert_called_once()


def test_check_update_airtable_missing_deployments_none(
    agreement_factory,
    mock_send_notification,
    mock_airtable_base_info,
    adobe_subscription_factory,
    mock_create_gc_agreement_deployments,
    mock_get_gc_agreement_deployments_by_main_agreement,
    mocked_agreement_syncer,
):
    deployments = [
        get_gc_agreement_deployment_model(AirTableBaseInfo(api_key="api-key", base_id="base-id"))(
            deployment_id=f"deployment-{i}"
        )
        for i in range(1, 4)
    ]
    mock_get_gc_agreement_deployments_by_main_agreement.return_value = deployments
    mocked_agreement_syncer._adobe_subscriptions = [
        adobe_subscription_factory(subscription_id=f"subscriptionId{i}") for i in range(4)
    ]

    mocked_agreement_syncer._check_update_airtable_missing_deployments([
        {"deploymentId": "deployment-1"},
        {"deploymentId": "deployment-2"},
        {"deploymentId": "deployment-3"},
    ])

    mock_create_gc_agreement_deployments.assert_not_called()
    mock_send_notification.assert_not_called()


@freeze_time("2025-10-02")
def test_update_subscription_dry_run(
    mock_mpt_client,
    adobe_subscription_factory,
    mock_get_prices_for_skus,
    subscriptions_factory,
    caplog,
    mocked_agreement_syncer,
):
    mocked_agreement_syncer._update_subscription(
        "65304578CA01A12",
        "product_id",
        adobe_subscription_factory(),
        "coterm_date",
        {"65304578CA01A12": 1234.55, "77777777CA01A12": 20.22},
        subscriptions_factory()[0],
        dry_run=True,
        sync_prices=False,
    )
    assert caplog.messages == [
        "NOT updating subscription due to dry_run=True: Subscription: "
        "SUB-1000-2000-3000 (ALI-2119-4550-8674-5962-0001), sku=65304578CA01A12, "
        "current_price=1234.55, new_price=1234.55, auto_renew=True, "
        "current_quantity=10, renewal_quantity=10, renewal_date=2026-10-11, "
        "commitment_date=coterm_date"
    ]
