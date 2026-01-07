import logging
from unittest import mock

import pytest
from freezegun import freeze_time

from adobe_vipm.adobe import constants
from adobe_vipm.adobe.constants import AdobeStatus
from adobe_vipm.adobe.errors import AdobeAPIError, AuthorizationNotFoundError
from adobe_vipm.airtable.models import AirTableBaseInfo, get_gc_agreement_deployment_model
from adobe_vipm.flows.constants import (
    TEMPLATE_ASSET_DEFAULT,
    TEMPLATE_SUBSCRIPTION_AUTORENEWAL_ENABLE,
    TEMPLATE_SUBSCRIPTION_TERMINATION,
    AgreementStatus,
    ItemTermsModel,
    Param,
)
from adobe_vipm.flows.errors import MPTAPIError
from adobe_vipm.flows.sync.agreement import (
    AgreementSyncer,
    get_customer_or_process_lost_customer,
    sync_agreement,
    sync_agreements_by_3yc_end_date,
    sync_agreements_by_3yc_enroll_status,
    sync_agreements_by_agreement_ids,
    sync_agreements_by_coterm_date,
    sync_agreements_by_renewal_date,
    sync_all_agreements,
)


def test_agreement_syncer_sync_dry_run(
    mocker,
    mock_mpt_client,
    mock_adobe_client,
    adobe_customer_factory,
    adobe_subscription_factory,
    items_factory,
    mock_agreement,
    mock_get_agreement,
    mock_get_agreements_by_customer_deployments,
    mock_get_prices_for_skus,
    mock_get_product_items_by_skus,
    mock_mpt_create_asset,
    mock_mpt_get_asset_template_by_name,
    mock_get_template_data_by_adobe_subscription,
    mock_mpt_create_agreement_subscription,
    mock_mpt_get_agreement_subscription,
    mock_mpt_terminate_subscription,
    mock_mpt_update_agreement,
    mock_mpt_update_asset,
    mock_get_gc_agreement_deployments_by_main_agreement,
    caplog,
):
    mock_customer = adobe_customer_factory(global_sales_enabled=True)
    mock_subscriptions = [
        adobe_subscription_factory(
            subscription_id=mock_agreement["subscriptions"][0]["externalIds"]["vendor"]
        ),
        adobe_subscription_factory(subscription_id="missing-sub-usd"),
        adobe_subscription_factory(subscription_id="missing-sub-eur", currency_code="EUR"),
        adobe_subscription_factory(subscription_id="missing-asset", offer_id="99999999CA01A12"),
    ]
    mock_get_agreement.return_value = mock_agreement
    mock_get_prices_for_skus.return_value = {"65304578CA01A12": 1234.55, "99999999CA01A12": 987.54}
    mock_get_product_items_by_skus.return_value = [
        items_factory()[0],
        items_factory(
            external_vendor_id="99999999CA",
            term_model=ItemTermsModel.ONE_TIME,
            term_period=ItemTermsModel.ONE_TIME,
        )[0],
    ]
    mock_get_template_data_by_adobe_subscription.return_value = None
    mock_mpt_get_agreement_subscription.return_value = mock_agreement["subscriptions"][0]
    mock_mpt_get_asset_template_by_name.return_value = None

    AgreementSyncer(
        mock_mpt_client,
        mock_adobe_client,
        mock_agreement,
        mock_customer,
        mock_subscriptions,
        dry_run=True,
    ).sync(sync_prices=True)  # act

    mock_get_product_items_by_skus.assert_called_once()
    mock_adobe_client.update_subscription.assert_not_called()
    assert "Dry run mode: skipping update adobe subscription missing-sub-eur" in caplog.text
    mock_mpt_create_agreement_subscription.assert_not_called()
    assert (
        "Dry run mode: skipping subscription creation for agreement AGR-2119-4550-8674-5962"
        in caplog.text
    )
    mock_mpt_create_asset.assert_not_called()
    assert (
        "Dry run mode: skipping create mpt asset for agreement AGR-2119-4550-8674-5962"
        in caplog.text
    )
    mock_mpt_update_asset.assert_not_called()
    mock_mpt_terminate_subscription.assert_not_called()
    mock_mpt_update_agreement.assert_not_called()
    assert "Dry run mode: skipping update for agreement AGR-2119-4550-8674-5962" in caplog.text
    assert (
        "Dry run mode: skipping update agreement last sync date AGR-2119-4550-8674-5962"
        in caplog.text
    )
    assert "Dry run mode: skipping update agreement gc_3yc AGR-2119-4550-8674-5962" in caplog.text
    assert (
        "Dry run mode: skipping update agreement subscription SUB-1000-2000-3000 with: "
        in caplog.text
    )


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
    mock_mpt_get_agreement_subscription,
    mock_mpt_update_agreement_subscription,
    mock_mpt_client,
    mock_mpt_update_agreement,
    mock_get_template_data_by_adobe_subscription,
    mocked_agreement_syncer,
    mock_add_missing_subscriptions_and_assets,
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
    mocked_agreement_syncer._adobe_customer = adobe_customer_factory(coterm_date="2025-04-04")
    mock_mpt_get_agreement_subscription.side_effect = [mpt_subscription, another_mpt_subscription]
    mocker.patch(
        "adobe_vipm.airtable.models.get_prices_for_skus",
        side_effect=[
            {"65304578CA01A12": 1234.55, "77777777CA01A12": 20.22},
            {"65304578CA01A12": 1234.55, "77777777CA01A12": 20.22},
        ],
    )
    mock_get_template_data_by_adobe_subscription.return_value = {
        "id": "TPL-1234",
        "name": "Renewing",
    }

    mocked_agreement_syncer.sync(sync_prices=True)  # act

    mock_mpt_get_agreement_subscription.assert_has_calls([
        mocker.call(mock_mpt_client, mpt_subscription["id"]),
        mocker.call(mock_mpt_client, another_mpt_subscription["id"]),
    ])
    mock_mpt_update_agreement_subscription.assert_has_calls([
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
    mock_mpt_update_agreement.assert_has_calls([
        mocker.call(
            mock_mpt_client,
            agreement["id"],
            lines=expected_lines,
            parameters={
                "fulfillment": [
                    {"externalId": "3YCRecommitmentRequestStatus", "value": None},
                    {"externalId": "3YCRecommit", "value": None},
                    {"externalId": "3YCEnrollStatus", "value": None},
                    {"externalId": "3YCStartDate", "value": None},
                    {"externalId": "3YCEndDate", "value": None},
                    {"externalId": "cotermDate", "value": "2025-04-04"},
                ],
                "ordering": [],
            },
        ),
        mocker.call(
            mock_mpt_client,
            agreement["id"],
            parameters={"fulfillment": [{"externalId": "lastSyncDate", "value": "2025-06-23"}]},
        ),
    ])


@freeze_time("2025-06-23")
def test_sync_agreement_update_agreement(
    mock_mpt_client, mocked_agreement_syncer, mock_get_agreement, mock_get_prices_for_skus
):
    mocked_agreement_syncer.sync(sync_prices=True)  # act

    mock_get_agreement.assert_called_once_with(
        mock_mpt_client, mocked_agreement_syncer._agreement["id"]
    )


@freeze_time("2025-06-23")
def test_sync_agreement_update_agreement_education(
    mock_mpt_client,
    mocked_agreement_syncer,
    mock_get_agreement,
    mock_get_prices_for_skus,
    mock_mpt_update_agreement,
):
    mocked_agreement_syncer._agreement["product"]["id"] = "PRD-4444-4444"
    mocked_agreement_syncer._adobe_customer["companyProfile"]["marketSubSegments"] = [
        "EDU_1",
        "EDU_2",
    ]

    mocked_agreement_syncer.sync(sync_prices=True)  # act

    mock_mpt_update_agreement.assert_has_calls([
        mock.call(
            mock_mpt_client,
            mocked_agreement_syncer._agreement["id"],
            parameters={
                "fulfillment": [
                    {"externalId": "3YCRecommitmentRequestStatus", "value": None},
                    {"externalId": "3YCRecommit", "value": None},
                    {"externalId": "3YCEnrollStatus", "value": None},
                    {"externalId": "3YCStartDate", "value": None},
                    {"externalId": "3YCEndDate", "value": None},
                    {"externalId": "cotermDate", "value": "2024-01-23"},
                    {"externalId": "educationSubSegment", "value": "EDU_1,EDU_2"},
                ],
                "ordering": [],
            },
            lines=[],
        ),
        mock.call(
            mock_mpt_client,
            mocked_agreement_syncer._agreement["id"],
            parameters={
                "fulfillment": [
                    {"externalId": "lastSyncDate", "value": "2025-06-23"},
                ],
            },
        ),
    ])


@freeze_time("2025-06-23")
def test_sync_agreement_not_prices(
    lines_factory,
    mock_mpt_client,
    mock_adobe_client,
    agreement_factory,
    subscriptions_factory,
    adobe_customer_factory,
    mock_get_prices_for_skus,
    mock_get_template_data_by_adobe_subscription,
    adobe_subscription_factory,
    mock_mpt_get_agreement_subscription,
    mock_mpt_update_agreement_subscription,
    mocked_agreement_syncer,
    mock_get_product_items_by_skus,
):
    mocked_agreement_syncer._adobe_customer = adobe_customer_factory(coterm_date="2025-04-04")
    mock_get_prices_for_skus.return_value = {"65304578CA01A12": 1234.55}
    mock_get_template_data_by_adobe_subscription.return_value = {
        "id": "TPL-1234",
        "name": "Renewing",
    }
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
    mock_mpt_get_agreement_subscription.return_value = agreement["subscriptions"][0]
    mocked_agreement_syncer._agreement = agreement

    mocked_agreement_syncer.sync(sync_prices=False)  # act

    mock_mpt_update_agreement_subscription.assert_called_once_with(
        mock_mpt_client,
        "SUB-1000-2000-3000",
        autoRenew=True,
        commitmentDate="2025-04-04",
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


@pytest.mark.parametrize(
    ("agreement_status"),
    [
        AgreementStatus.TERMINATED,
        AgreementStatus.ACTIVE,
    ],
)
def test_process_orphaned_deployment_subscriptions_status(
    agreement_status,
    mock_adobe_client,
    agreement_factory,
    mock_add_missing_subscriptions_and_assets,
    mock_get_agreements_by_customer_deployments,
    fulfillment_parameters_factory,
    mock_get_prices_for_skus,
    mock_check_update_airtable_missing_deployments,
    mocked_agreement_syncer,
    adobe_subscription_factory,
    adobe_customer_factory,
):
    mock_adobe_client.get_customer_deployments_active_status.return_value = [
        {
            "deploymentId": "deployment-id",
            "status": "1000",
            "companyProfile": {"address": {"country": "DE"}},
        }
    ]
    deployment_agreement = agreement_factory(
        assets=[],
        status=agreement_status,
        fulfillment_parameters=fulfillment_parameters_factory(
            global_customer="yes", deployment_id="deployment_id"
        ),
    )
    mock_get_agreements_by_customer_deployments.return_value = [deployment_agreement]
    mocked_agreement_syncer._adobe_subscriptions = [
        adobe_subscription_factory(
            subscription_id="specific_subscription_id", deployment_id="deployment-id"
        ),
        adobe_subscription_factory(
            subscription_id="subscription_id",
            deployment_id="deployment-id",
            autorenewal_enabled=False,
        ),
    ]
    mocked_agreement_syncer._adobe_customer = adobe_customer_factory(global_sales_enabled=True)

    mocked_agreement_syncer.sync(sync_prices=True)  # act

    mock_adobe_client.update_subscription.assert_called_once_with(
        "AUT-1234-5678", "a-client-id", "specific_subscription_id", auto_renewal=False
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
    mock_mpt_update_agreement,
    mock_mpt_update_agreement_subscription,
    mock_mpt_get_agreement_subscription,
    mocked_agreement_syncer,
    mock_get_template_data_by_adobe_subscription,
):
    mocked_agreement_syncer._agreement = agreement_factory(
        lines=lines_factory(external_vendor_id="77777777CA", unit_purchase_price=10.11)
    )
    mpt_subscription = subscriptions_factory()[0]
    mocked_agreement_syncer._adobe_customer = adobe_customer_factory(coterm_date="2025-04-04")
    mock_mpt_get_agreement_subscription.return_value = mpt_subscription
    mocker.patch(
        "adobe_vipm.airtable.models.get_prices_for_skus",
        side_effect=[{"65327701CA01A12": 1234.55}, {"77777777CA01A12": 20.22}],
    )
    mock_get_template_data_by_adobe_subscription.return_value = {
        "id": "TPL-1234",
        "name": "Expired",
    }
    mocked_agreement_syncer._dry_run = True

    mocked_agreement_syncer.sync(sync_prices=True)  # act

    mock_mpt_get_agreement_subscription.assert_called_once_with(
        mock_mpt_client, mpt_subscription["id"]
    )
    mock_mpt_update_agreement_subscription.assert_not_called()
    mock_mpt_update_agreement.assert_not_called()
    mock_get_template_data_by_adobe_subscription.assert_called_once()


def test_sync_agreement_prices_exception(
    mocker,
    mock_adobe_client,
    mock_mpt_client,
    agreement_factory,
    subscriptions_factory,
    adobe_api_error_factory,
    adobe_customer_factory,
    caplog,
    mock_mpt_update_agreement,
    mock_mpt_update_agreement_subscription,
    mock_mpt_get_agreement_subscription,
    lines_factory,
    adobe_subscription_factory,
    mocked_agreement_syncer,
    mock_mpt_get_template_by_name,
    mock_notify_agreement_unhandled_exception_in_teams,
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
    mock_mpt_get_template_by_name.return_value = {"id": "TPL-1234", "name": "Expired"}
    mock_mpt_update_agreement_subscription.side_effect = AdobeAPIError(
        400, adobe_api_error_factory(code="9999", message="Error from Adobe.")
    )
    mpt_subscription = mpt_subscriptions[0]
    mock_mpt_get_agreement_subscription.return_value = mpt_subscription

    with caplog.at_level(logging.ERROR):
        mocked_agreement_syncer.sync(sync_prices=True)  # act

    assert f"Error synchronizing agreement {agreement['id']}" in caplog.text
    mock_mpt_get_agreement_subscription.assert_called_once_with(
        mock_mpt_client, mpt_subscription["id"]
    )
    mock_mpt_update_agreement_subscription.assert_called_once_with(
        mock_mpt_client,
        "SUB-1234-5678",
        template={"id": "TPL-1234", "name": "Expired"},
    )
    mock_mpt_update_agreement.assert_not_called()
    mock_notify_agreement_unhandled_exception_in_teams.assert_called_once_with(
        agreement["id"], mocker.ANY
    )


def test_sync_agreement_prices_skip_processing(
    mock_adobe_client,
    mock_mpt_client,
    agreement_factory,
    caplog,
    adobe_customer_factory,
    mock_mpt_update_agreement,
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
        mocked_agreement_syncer.sync(sync_prices=False)  # act

    assert f"Agreement {agreement['id']} has processing subscriptions, skip it" in caplog.text
    mock_mpt_update_agreement.assert_not_called()


# ???: (tests below) why are we testing the sync_agreement method in this file instead of
# flows -> sync -> test_helper


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
    mock_mpt_client,
    mock_mpt_update_agreement_subscription,
    mock_mpt_get_agreement_subscription,
    mock_mpt_update_agreement,
    mock_mpt_get_template_by_name,
    mock_get_template_data_by_adobe_subscription,
):
    agreement = agreement_factory(
        lines=lines_factory(external_vendor_id="77777777CA", unit_purchase_price=10.11)
    )
    adobe_subscription = adobe_subscription_factory()
    mock_adobe_client.get_subscriptions.return_value = {"items": [adobe_subscription]}
    mock_adobe_client.get_customer.return_value = adobe_customer_factory(
        coterm_date="2025-04-04",
        commitment=adobe_commitment_factory(licenses=9, consumables=1220),
        recommitment_request=adobe_commitment_factory(status="ACCEPTED"),
    )
    mpt_subscription = subscriptions_factory()[0]
    mock_mpt_get_agreement_subscription.return_value = mpt_subscription
    mocker.patch(
        "adobe_vipm.airtable.models.get_prices_for_3yc_skus",
        side_effect=[{"65304578CA01A12": 1234.55}, {"77777777CA01A12": 20.22}],
    )
    mock_mpt_get_template_by_name.return_value = {"id": "TPL-1234", "name": "Terminated"}
    mock_get_template_data_by_adobe_subscription.return_value = {
        "id": "TPL-1234",
        "name": "Renewing",
    }

    sync_agreement(
        mock_mpt_client, mock_adobe_client, agreement, dry_run=False, sync_prices=True
    )  # act

    mock_mpt_get_agreement_subscription.assert_called_once_with(
        mock_mpt_client, mpt_subscription["id"]
    )
    mock_mpt_update_agreement_subscription.assert_has_calls([
        mocker.call(
            mock_mpt_client,
            "SUB-1234-5678",
            template={"id": "TPL-1234", "name": TEMPLATE_SUBSCRIPTION_TERMINATION},
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
            template={"id": "TPL-1234", "name": TEMPLATE_SUBSCRIPTION_AUTORENEWAL_ENABLE},
        ),
    ])
    expected_lines = lines_factory(external_vendor_id="77777777CA", unit_purchase_price=20.22)
    assert mock_mpt_update_agreement.call_args_list == [
        mocker.call(
            mock_mpt_client,
            agreement["id"],
            lines=expected_lines,
            parameters={
                "fulfillment": [
                    {"externalId": "3YCRecommitmentRequestStatus", "value": "ACCEPTED"},
                    {"externalId": "3YCRecommit", "value": None},
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
    mock_mpt_get_template_by_name.assert_called_once_with(
        mock_mpt_client, "PRD-1111-1111", TEMPLATE_SUBSCRIPTION_TERMINATION
    )
    mock_get_template_data_by_adobe_subscription.assert_called_once_with(
        adobe_subscription, "PRD-1111-1111"
    )


@freeze_time("2025-06-19")
def test_sync_global_customer_parameter(
    mocker,
    lines_factory,
    mock_mpt_client,
    mock_adobe_client,
    agreement_factory,
    mock_mpt_update_agreement,
    subscriptions_factory,
    adobe_customer_factory,
    mock_get_prices_for_skus,
    mock_update_subscriptions,
    adobe_subscription_factory,
    fulfillment_parameters_factory,
    mock_add_missing_subscriptions_and_assets,
    mock_get_adobe_product_by_marketplace_sku,
    mock_get_agreements_by_customer_deployments,
    mock_check_update_airtable_missing_deployments,
    caplog,
):
    agreement = agreement_factory(
        lines=lines_factory(external_vendor_id="77777777CA", unit_purchase_price=20.22),
        subscriptions=[
            {
                "id": "SUB-1000-2000-3000",
                "status": "Active",
                "item": {"id": "ITM-0000-0001-0001"},
                "externalIds": {"vendor": "1e5b9c974c4ea1bcabdb0fe697a2f1NA"},
            },
            {
                "id": "SUB-1234-5678",
                "status": "Terminated",
                "item": {"id": "ITM-0000-0001-0002"},
                "externalIds": {"vendor": "1e5b9c974c4ea1bcabdb0fe697a2f1NA"},
            },
            {
                "id": "SUB-1000-2000-5000",
                "status": "Active",
                "item": {"id": "ITM-0000-0001-0003"},
                "externalIds": {"vendor": "1e5b9c974c4ea1bcabdb0fe697a2f1NA"},
            },
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
            lines=lines_factory(external_vendor_id="77777777CA", unit_purchase_price=20.22),
        ),
        agreement_factory(
            agreement_id="AGR-deployment-2",
            status=AgreementStatus.TERMINATED,
            fulfillment_parameters=fulfillment_parameters_factory(
                global_customer="", deployment_id="deployment-2", deployments=""
            ),
        ),
    ]
    mock_get_agreements_by_customer_deployments.return_value = deployment_agreements
    mock_get_prices_for_skus.return_value = {"65304578CA01A12": 1234.55, "77777777CA01A12": 20.22}

    sync_agreement(
        mock_mpt_client, mock_adobe_client, agreement, dry_run=False, sync_prices=True
    )  # act

    mock_add_missing_subscriptions_and_assets.assert_called_once()
    expected_lines = lines_factory(external_vendor_id="77777777CA", unit_purchase_price=20.22)
    mock_mpt_update_agreement.assert_has_calls([
        mocker.call(
            mock_mpt_client,
            agreement["id"],
            lines=expected_lines,
            parameters={
                "fulfillment": [
                    {"externalId": "3YCRecommitmentRequestStatus", "value": None},
                    {"externalId": "3YCRecommit", "value": None},
                    {"externalId": "3YCEnrollStatus", "value": None},
                    {"externalId": "3YCStartDate", "value": None},
                    {"externalId": "3YCEndDate", "value": None},
                    {"externalId": "cotermDate", "value": "2025-04-04"},
                ],
                "ordering": [],
            },
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
            parameters={
                "fulfillment": [
                    {"externalId": "3YCRecommitmentRequestStatus", "value": None},
                    {"externalId": "3YCRecommit", "value": None},
                    {"externalId": "3YCEnrollStatus", "value": None},
                    {"externalId": "3YCStartDate", "value": None},
                    {"externalId": "3YCEndDate", "value": None},
                    {"externalId": "cotermDate", "value": "2025-04-04"},
                ],
                "ordering": [],
            },
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
    ])
    assert "Getting subscriptions for update for agreement AGR-deployment-1" in caplog.messages
    assert "Getting subscriptions for update for agreement AGR-deployment-2" not in caplog.messages


def test_sync_global_customer(
    mock_adobe_client,
    agreement_factory,
    mock_mpt_update_agreement,
    adobe_customer_factory,
    mock_get_prices_for_skus,
    mock_update_subscriptions,
    adobe_subscription_factory,
    fulfillment_parameters_factory,
    mock_add_missing_subscriptions_and_assets,
    mock_get_agreements_by_customer_deployments,
    mock_check_update_airtable_missing_deployments,
    mock_mpt_get_agreement_subscription,
    mocked_agreement_syncer,
    caplog,
):
    mocked_agreement_syncer._agreement = agreement_factory(
        fulfillment_parameters=fulfillment_parameters_factory(
            global_customer="yes", deployment_id=""
        ),
        assets=[],
    )
    mock_mpt_get_agreement_subscription.return_value = mocked_agreement_syncer._agreement[
        "subscriptions"
    ][0]
    mocked_agreement_syncer._adobe_customer = adobe_customer_factory(global_sales_enabled=True)
    mock_adobe_client.get_customer_deployments_active_status.return_value = [
        {
            "deploymentId": "deployment-id",
            "status": "1000",
            "companyProfile": {"address": {"country": "DE"}},
        }
    ]
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
    deployment_agreements = [
        agreement_factory(
            agreement_id="AGR-deployment-1",
            fulfillment_parameters=fulfillment_parameters_factory(
                global_customer="", deployment_id="deployment-1", deployments=""
            ),
        ),
        agreement_factory(
            agreement_id="AGR-deployment-2",
            status=AgreementStatus.TERMINATED,
            fulfillment_parameters=fulfillment_parameters_factory(
                global_customer="", deployment_id="deployment-2", deployments=""
            ),
        ),
    ]
    mock_get_agreements_by_customer_deployments.return_value = deployment_agreements

    mocked_agreement_syncer.sync(sync_prices=True)  # act

    mock_add_missing_subscriptions_and_assets.assert_called_once()
    mock_mpt_update_agreement.assert_called()
    assert caplog.messages == [
        "Synchronizing agreement AGR-2119-4550-8674-5962",
        "Getting assets for update for agreement AGR-2119-4550-8674-5962",
        "Getting subscriptions for update for agreement AGR-2119-4550-8674-5962",
        "Agreement updated AGR-2119-4550-8674-5962",
        "Setting global customer for agreement AGR-2119-4550-8674-5962",
        "Setting deployments for agreement AGR-2119-4550-8674-5962",
        "Looking for orphaned deployment subscriptions in Adobe.",
        "Getting subscriptions for update for agreement AGR-deployment-1",
        "Agreement updated AGR-deployment-1",
        "Updating Last Sync Date for agreement AGR-2119-4550-8674-5962",
    ]


def test_sync_global_customer_dry(
    mock_adobe_client,
    agreement_factory,
    mock_mpt_update_agreement,
    adobe_customer_factory,
    mock_get_prices_for_skus,
    mock_update_subscriptions,
    adobe_subscription_factory,
    fulfillment_parameters_factory,
    mock_add_missing_subscriptions_and_assets,
    mock_get_agreements_by_customer_deployments,
    mock_mpt_get_agreement_subscription,
    mock_get_gc_agreement_deployments_by_main_agreement,
    mock_get_transfer_by_authorization_membership_or_customer,
    mocked_agreement_syncer,
    caplog,
):
    mocked_agreement_syncer._dry_run = True
    mocked_agreement_syncer._agreement = agreement_factory(
        fulfillment_parameters=fulfillment_parameters_factory(
            global_customer="yes", deployment_id=""
        ),
        assets=[],
    )
    mock_mpt_get_agreement_subscription.return_value = mocked_agreement_syncer._agreement[
        "subscriptions"
    ][0]
    mocked_agreement_syncer._adobe_customer = adobe_customer_factory(global_sales_enabled=True)
    mock_adobe_client.get_customer_deployments_active_status.return_value = [
        {
            "deploymentId": "deployment-id",
            "status": "1000",
            "companyProfile": {"address": {"country": "DE"}},
        }
    ]
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
    deployment_agreements = [
        agreement_factory(
            agreement_id="AGR-deployment-1",
            fulfillment_parameters=fulfillment_parameters_factory(
                global_customer="", deployment_id="deployment-1", deployments=""
            ),
        ),
        agreement_factory(
            agreement_id="AGR-deployment-2",
            status=AgreementStatus.TERMINATED,
            fulfillment_parameters=fulfillment_parameters_factory(
                global_customer="", deployment_id="deployment-2", deployments=""
            ),
        ),
    ]
    mock_get_agreements_by_customer_deployments.return_value = deployment_agreements

    mocked_agreement_syncer.sync(sync_prices=True)  # act

    mock_add_missing_subscriptions_and_assets.assert_called_once()
    mock_mpt_update_agreement.assert_not_called()
    assert "skipping update" in caplog.text


def test_sync_deployment_agreement(
    mock_adobe_client,
    agreement_factory,
    mock_mpt_update_agreement,
    adobe_customer_factory,
    mock_get_prices_for_skus,
    mock_update_subscriptions,
    adobe_subscription_factory,
    fulfillment_parameters_factory,
    mock_add_missing_subscriptions_and_assets,
    mock_get_agreements_by_customer_deployments,
    mock_process_orphaned_deployment_subscriptions,
    mock_mpt_get_agreement_subscription,
    mocked_agreement_syncer,
    caplog,
):
    mocked_agreement_syncer._agreement = agreement_factory(
        fulfillment_parameters=fulfillment_parameters_factory(
            global_customer="yes", deployment_id="deployment-1"
        )
    )
    mocked_agreement_syncer._agreement["assets"] = []
    mock_mpt_get_agreement_subscription.return_value = mocked_agreement_syncer._agreement[
        "subscriptions"
    ][0]
    mocked_agreement_syncer._adobe_customer = adobe_customer_factory(global_sales_enabled=True)
    mock_adobe_client.get_customer_deployments_active_status.return_value = [
        {
            "deploymentId": "deployment-id",
            "status": "1000",
            "companyProfile": {"address": {"country": "DE"}},
        }
    ]
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
    deployment_agreements = [
        agreement_factory(
            agreement_id="AGR-deployment-1",
            fulfillment_parameters=fulfillment_parameters_factory(
                global_customer="", deployment_id="deployment-1", deployments=""
            ),
        ),
    ]
    mock_get_agreements_by_customer_deployments.return_value = deployment_agreements

    mocked_agreement_syncer.sync(sync_prices=True)  # act

    mock_add_missing_subscriptions_and_assets.assert_called_once()
    mock_mpt_update_agreement.assert_called()
    mock_get_agreements_by_customer_deployments.assert_not_called()
    mock_process_orphaned_deployment_subscriptions.assert_not_called()
    assert caplog.messages == [
        "Synchronizing agreement AGR-2119-4550-8674-5962",
        "Getting assets for update for agreement AGR-2119-4550-8674-5962",
        "Getting subscriptions for update for agreement AGR-2119-4550-8674-5962",
        "Agreement updated AGR-2119-4550-8674-5962",
        "Setting global customer for agreement AGR-2119-4550-8674-5962",
        "Setting deployments for agreement AGR-2119-4550-8674-5962",
        "Updating Last Sync Date for agreement AGR-2119-4550-8674-5962",
    ]


@freeze_time("2025-06-19")
def test_sync_global_customer_parameter_dry_run(
    mocker,
    lines_factory,
    mock_mpt_client,
    mock_adobe_client,
    agreement_factory,
    mock_mpt_update_agreement,
    subscriptions_factory,
    adobe_customer_factory,
    mock_get_prices_for_skus,
    mock_update_subscriptions,
    adobe_subscription_factory,
    fulfillment_parameters_factory,
    mock_add_missing_subscriptions_and_assets,
    mock_get_adobe_product_by_marketplace_sku,
    mock_get_agreements_by_customer_deployments,
    mock_check_update_airtable_missing_deployments,
):
    agreement = agreement_factory(
        lines=lines_factory(external_vendor_id="77777777CA", unit_purchase_price=20.22),
        subscriptions=[
            {
                "id": "SUB-1000-2000-3000",
                "status": "Active",
                "item": {"id": "ITM-0000-0001-0001"},
                "externalIds": {"vendor": "1e5b9c974c4ea1bcabdb0fe697a2f1NA"},
            },
            {
                "id": "SUB-1234-5678",
                "status": "Terminated",
                "item": {"id": "ITM-0000-0001-0002"},
                "externalIds": {"vendor": "1e5b9c974c4ea1bcabdb0fe697a2f1NA"},
            },
            {
                "id": "SUB-1000-2000-5000",
                "status": "Active",
                "item": {"id": "ITM-0000-0001-0003"},
                "externalIds": {"vendor": "1e5b9c974c4ea1bcabdb0fe697a2f1NA"},
            },
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
            fulfillment_parameters=fulfillment_parameters_factory(
                global_customer="", deployment_id="deployment-1", deployments=""
            ),
            lines=lines_factory(external_vendor_id="77777777CA", unit_purchase_price=20.22),
        )
    ]
    mock_get_agreements_by_customer_deployments.return_value = deployment_agreements
    mock_get_prices_for_skus.return_value = {"65304578CA01A12": 1234.55, "77777777CA01A12": 20.22}

    sync_agreement(
        mock_mpt_client, mock_adobe_client, agreement, dry_run=True, sync_prices=True
    )  # act

    mock_add_missing_subscriptions_and_assets.assert_called_once()
    mock_mpt_update_agreement.assert_not_called()


@freeze_time("2025-06-30")
def test_sync_global_customer_update_not_required(
    mocker,
    mock_mpt_client,
    agreement_factory,
    mock_adobe_client,
    mock_mpt_update_agreement,
    adobe_customer_factory,
    mock_get_subscriptions_for_update,
    mock_get_agreements_by_customer_deployments,
    mock_check_update_airtable_missing_deployments,
    mock_get_prices_for_skus,
):
    mock_get_subscriptions_for_update.return_value = []
    mock_get_agreements_by_customer_deployments.return_value = []
    agreement = agreement_factory(
        fulfillment_parameters=[
            {"externalId": "customerId", "value": "a-client-id"},
            {"externalId": "globalCustomer", "value": ["Yes"]},
            {"externalId": "deployments", "value": "deployment-id - DE"},
            {"externalId": "deploymentId", "value": "deployment-id"},
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

    sync_agreement(
        mock_mpt_client, mock_adobe_client, agreement, dry_run=False, sync_prices=True
    )  # act

    mock_mpt_update_agreement.assert_has_calls([
        mocker.call(
            mock_mpt_client,
            "AGR-2119-4550-8674-5962",
            lines=[],
            parameters={
                "fulfillment": [
                    {"externalId": "3YCCommitmentRequestStatus", "value": None},
                    {"externalId": "3YCEnrollStatus", "value": None},
                    {"externalId": "3YCStartDate", "value": None},
                    {"externalId": "3YCEndDate", "value": None},
                    {"externalId": "cotermDate", "value": "2024-01-23"},
                ],
                "ordering": [{"externalId": "3YC", "value": None}],
            },
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
    mock_mpt_update_agreement,
    adobe_customer_factory,
    mock_add_missing_subscriptions_and_assets,
    mock_get_subscriptions_for_update,
    mock_get_agreements_by_customer_deployments,
    mock_get_prices_for_skus,
    mock_get_gc_agreement_deployments_by_main_agreement,
):
    mock_adobe_client.get_customer_deployments_active_status.return_value = []
    mock_get_subscriptions_for_update.return_value = []
    mock_adobe_client.get_customer.return_value = adobe_customer_factory(global_sales_enabled=True)

    sync_agreement(
        mock_mpt_client, mock_adobe_client, agreement_factory(), dry_run=False, sync_prices=True
    )  # act

    mock_get_gc_agreement_deployments_by_main_agreement.assert_not_called()
    mock_get_agreements_by_customer_deployments.assert_not_called()
    mock_add_missing_subscriptions_and_assets.assert_called_once()
    mock_get_subscriptions_for_update.assert_called()
    mock_adobe_client.get_customer_deployments_active_status.assert_called_once()
    assert mock_mpt_update_agreement.mock_calls == [
        mocker.call(
            mock_mpt_client,
            "AGR-2119-4550-8674-5962",
            lines=[],
            parameters={
                "fulfillment": [
                    {"externalId": "3YCRecommitmentRequestStatus", "value": None},
                    {"externalId": "3YCRecommit", "value": None},
                    {"externalId": "3YCEnrollStatus", "value": None},
                    {"externalId": "3YCStartDate", "value": None},
                    {"externalId": "3YCEndDate", "value": None},
                    {"externalId": "cotermDate", "value": "2024-01-23"},
                ],
                "ordering": [],
            },
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
    mock_mpt_get_agreement_subscription,
    mocked_agreement_syncer,
    mock_notify_agreement_unhandled_exception_in_teams,
):
    mocked_agreement_syncer._adobe_customer["globalSalesEnabled"] = True
    mocked_agreement_syncer._agreement["subscriptions"] = []
    mock_adobe_client.get_customer_deployments_active_status.side_effect = AdobeAPIError(
        400, adobe_api_error_factory("9999", "some error")
    )

    mocked_agreement_syncer.sync(sync_prices=True)  # act

    mock_notify_agreement_unhandled_exception_in_teams.assert_called_once()
    assert (
        mock_notify_agreement_unhandled_exception_in_teams.call_args_list[0].args[0]
        == mocked_agreement_syncer._agreement["id"]
    )


def test_sync_global_customer_parameters_error(
    caplog,
    mock_mpt_update_agreement,
    mocked_agreement_syncer,
    mock_notify_agreement_unhandled_exception_in_teams,
):
    mock_mpt_update_agreement.side_effect = AdobeAPIError(400, {"error": "some error"})

    with caplog.at_level(logging.ERROR):
        mocked_agreement_syncer._sync_global_customer_parameters([
            {
                "deploymentId": "deployment-id",
                "status": "1000",
                "companyProfile": {"address": {"country": "DE"}},
            }
        ])  # act

    assert (
        caplog.records[0].message
        == "Error setting global customer parameters for agreement AGR-2119-4550-8674-5962."
    )


def test_sync_agreement_notify_exception(
    mocked_agreement_syncer,
    mock_add_missing_subscriptions_and_assets,
    mock_notify_agreement_unhandled_exception_in_teams,
):
    mock_add_missing_subscriptions_and_assets.side_effect = Exception("Test exception")

    mocked_agreement_syncer.sync(sync_prices=False)  # act

    mock_notify_agreement_unhandled_exception_in_teams.assert_called_once()
    assert (
        mock_notify_agreement_unhandled_exception_in_teams.call_args_list[0].args[0]
        == mocked_agreement_syncer._agreement["id"]
    )


def test_sync_agreement_empty_discounts(
    mock_adobe_client,
    mock_mpt_client,
    agreement_factory,
    subscriptions_factory,
    adobe_customer_factory,
    mock_send_warning,
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
    customer = adobe_customer_factory()
    customer["discounts"] = []
    mock_adobe_client.get_customer.return_value = customer

    sync_agreement(
        mock_mpt_client, mock_adobe_client, agreement, dry_run=False, sync_prices=False
    )  # act

    mock_send_warning.assert_called_once_with(
        "Customer does not have discounts information",
        "Error synchronizing agreement AGR-2119-4550-8674-5962. Customer a-client-id "
        "does not have discounts information. Cannot proceed with price "
        "synchronization.",
    )


@freeze_time("2025-06-19")
def test_sync_agreement_prices_with_missing_prices(
    mocker,
    agreement_factory,
    subscriptions_factory,
    lines_factory,
    adobe_subscription_factory,
    adobe_customer_factory,
    mock_get_adobe_product_by_marketplace_sku,
    mock_mpt_terminate_subscription,
    mock_mpt_client,
    mock_adobe_client,
    caplog,
    mock_mpt_update_agreement_subscription,
    mock_mpt_get_agreement_subscription,
    mock_mpt_update_agreement,
    mock_mpt_get_template_by_name,
    mock_get_template_data_by_adobe_subscription,
    mocked_agreement_syncer,
    mock_add_missing_subscriptions_and_assets,
    mock_notify_missing_prices,
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
    mocked_agreement_syncer._adobe_customer = adobe_customer_factory(coterm_date="2025-04-04")
    mock_mpt_get_agreement_subscription.side_effect = [
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
    mock_mpt_get_template_by_name.side_effect = [
        {"id": "TPL-2345", "name": "Expired"},
    ]
    mock_get_template_data_by_adobe_subscription.return_value = {
        "id": "TPL-1234",
        "name": "Renewing",
    }

    with caplog.at_level(logging.ERROR):
        mocked_agreement_syncer.sync(sync_prices=True)  # act

    assert "Skipping subscription" in caplog.text
    assert "65304578CA01A12" in caplog.text
    mock_notify_missing_prices.assert_called_once_with(
        "AGR-2119-4550-8674-5962", ["65304578CA01A12"], "PRD-1111-1111", "USD", None
    )
    assert mock_mpt_update_agreement.call_args_list == [
        mocker.call(
            mock_mpt_client,
            agreement["id"],
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
            parameters={
                "fulfillment": [
                    {"externalId": "3YCRecommitmentRequestStatus", "value": None},
                    {"externalId": "3YCRecommit", "value": None},
                    {"externalId": "3YCEnrollStatus", "value": None},
                    {"externalId": "3YCStartDate", "value": None},
                    {"externalId": "3YCEndDate", "value": None},
                    {"externalId": "cotermDate", "value": "2025-04-04"},
                ],
                "ordering": [],
            },
        ),
        mocker.call(
            mock_mpt_client,
            agreement["id"],
            parameters={"fulfillment": [{"externalId": "lastSyncDate", "value": "2025-06-19"}]},
        ),
    ]
    assert mock_mpt_update_agreement_subscription.mock_calls == [
        mocker.call(
            mock_mpt_client,
            terminated_mpt_subscription["id"],
            template={"id": "TPL-2345", "name": "Expired"},
        ),
        mocker.call(
            mock_mpt_client,
            another_mpt_subscription["id"],
            lines=[
                {"id": "ALI-2119-4550-8674-5962-0001", "quantity": 15, "price": {"unitPP": 20.22}}
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
            commitmentDate="2025-04-04",
            autoRenew=True,
            template={"id": "TPL-1234", "name": "Renewing"},
        ),
    ]
    mock_mpt_terminate_subscription.assert_called_once_with(
        mock_mpt_client, "SUB-1000-2000-6000", "Adobe subscription status 1004."
    )


def test_sync_agreement_empty_customer_id(
    mocker,
    mock_mpt_client,
    mock_adobe_client,
    agreement_factory,
    mock_notify_agreement_unhandled_exception_in_teams,
    caplog,
):
    agreement = agreement_factory(
        fulfillment_parameters=[{"externalId": "FakeFulfillmentParam"}],
        ordering_parameters=[{"externalId": "FakeOrderingParam"}],
    )
    mock_notify_agreement_unhandled_exception_in_teams = mocker.patch(
        "adobe_vipm.flows.sync.agreement.notify_agreement_unhandled_exception_in_teams"
    )

    sync_agreement(
        mock_mpt_client, mock_adobe_client, agreement, dry_run=False, sync_prices=False
    )  # act

    expected_params = {
        "ordering": [{"externalId": "FakeOrderingParam"}],
        "fulfillment": [{"externalId": "FakeFulfillmentParam"}],
    }
    expected_message = (
        f"CustomerId not found in Agreement AGR-2119-4550-8674-5962 with params "
        f"{expected_params}. Skipping."
    )
    mock_notify_agreement_unhandled_exception_in_teams.assert_called_once_with(
        "AGR-2119-4550-8674-5962", expected_message
    )
    assert expected_message in caplog.messages


@pytest.mark.usefixtures("mock_get_agreements_by_customer_deployments")
def test_sync_agreement_lost_customer(
    mocker,
    mock_mpt_client,
    mock_adobe_client,
    agreement_factory,
    mock_send_warning,
    mock_mpt_terminate_subscription,
    mocked_agreement_syncer,
    caplog,
):
    mock_adobe_client.get_customer.side_effect = AdobeAPIError(
        status_code=int(AdobeStatus.INVALID_CUSTOMER.value),
        payload={"code": "1116", "message": "Invalid Customer", "additionalDetails": []},
    )

    sync_agreement(
        mock_mpt_client, mock_adobe_client, agreement_factory(), dry_run=False, sync_prices=True
    )  # act

    assert mock_mpt_terminate_subscription.mock_calls == [
        mocker.call(mock_mpt_client, "SUB-1000-2000-3000", "Suspected Lost Customer"),
        mocker.call(mock_mpt_client, "SUB-1000-2000-3000", "Suspected Lost Customer"),
        mocker.call(mock_mpt_client, "SUB-1000-2000-3000", "Suspected Lost Customer"),
    ]
    mock_send_warning.assert_called_once_with(
        "Executing Lost Customer Procedure.",
        "Received Adobe error 1116 - Invalid Customer, assuming lost customer and proceeding"
        " with lost customer procedure.",
    )
    assert caplog.messages == [
        (
            "Received Adobe error 1116 - Invalid Customer, assuming lost customer and"
            " proceeding with lost customer procedure."
        ),
        "> Suspected Lost Customer: Terminating subscription SUB-1000-2000-3000.",
    ]


@pytest.mark.usefixtures("mock_get_agreements_by_customer_deployments")
def test_sync_agreement_lost_customer_error(
    mocker,
    mock_mpt_client,
    mock_adobe_client,
    mpt_error_factory,
    agreement_factory,
    mock_send_exception,
    mock_send_warning,
    mock_mpt_terminate_subscription,
    mocked_agreement_syncer,
    caplog,
):
    mock_adobe_client.get_customer.side_effect = AdobeAPIError(
        status_code=int(AdobeStatus.INVALID_CUSTOMER.value),
        payload={"code": "1116", "message": "Invalid Customer", "additionalDetails": []},
    )
    mock_mpt_terminate_subscription.side_effect = MPTAPIError(
        500, mpt_error_factory(500, "Internal Server Error", "Oops!")
    )

    sync_agreement(
        mock_mpt_client, mock_adobe_client, agreement_factory(), dry_run=False, sync_prices=True
    )  # act

    mock_mpt_terminate_subscription.assert_has_calls([
        mocker.call(mock_mpt_client, "SUB-1000-2000-3000", "Suspected Lost Customer"),
        mocker.call(mock_mpt_client, "SUB-1000-2000-3000", "Suspected Lost Customer"),
        mocker.call(mock_mpt_client, "SUB-1000-2000-3000", "Suspected Lost Customer"),
    ])
    mock_send_exception.assert_has_calls([
        mocker.call(
            "> Suspected Lost Customer: Error terminating subscription SUB-1000-2000-3000",
            "500 Internal Server Error - Oops!"
            " (00-27cdbfa231ecb356ab32c11b22fd5f3c-721db10d009dfa2a-00)",
        ),
        mocker.call(
            "> Suspected Lost Customer: Error terminating subscription SUB-1000-2000-3000",
            "500 Internal Server Error - Oops!"
            " (00-27cdbfa231ecb356ab32c11b22fd5f3c-721db10d009dfa2a-00)",
        ),
        mocker.call(
            "> Suspected Lost Customer: Error terminating subscription SUB-1000-2000-3000",
            "500 Internal Server Error - Oops!"
            " (00-27cdbfa231ecb356ab32c11b22fd5f3c-721db10d009dfa2a-00)",
        ),
    ])
    mock_send_warning.assert_called_once_with(
        "Executing Lost Customer Procedure.",
        "Received Adobe error 1116 - Invalid Customer, assuming lost customer and proceeding"
        " with lost customer procedure.",
    )
    assert [rec.message for rec in caplog.records] == [
        (
            "Received Adobe error 1116 - Invalid Customer, assuming lost customer and"
            " proceeding with lost customer procedure."
        ),
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
    mock_adobe_client,
    mock_update_last_sync_date,
    mocked_agreement_syncer,
    status,
):
    mocked_agreement_syncer._agreement = {"id": "1", "status": status, "subscriptions": []}

    mocked_agreement_syncer.sync(sync_prices=False)  # act

    mock_update_last_sync_date.assert_not_called()


def test_get_subscriptions_for_update_skip_adobe_inactive(
    mock_mpt_client,
    mock_adobe_client,
    adobe_customer_factory,
    agreement_factory,
    adobe_subscription_factory,
    mock_mpt_get_agreement_subscription,
    mocked_agreement_syncer,
):
    mocked_agreement_syncer._adobe_subscriptions = [
        adobe_subscription_factory(status=AdobeStatus.SUBSCRIPTION_TERMINATED.value)
    ]

    result = mocked_agreement_syncer._get_subscriptions_for_update(agreement_factory())

    assert result == []


@freeze_time("2025-07-23")
def test_get_subscriptions_for_update_terminated(
    mocker,
    mock_mpt_client,
    mock_adobe_client,
    agreement_factory,
    subscriptions_factory,
    adobe_customer_factory,
    adobe_subscription_factory,
    mock_mpt_terminate_subscription,
    mock_mpt_get_agreement_subscription,
    mock_mpt_update_agreement_subscription,
    mock_mpt_get_template_by_name,
    mocked_agreement_syncer,
):
    adobe_subscriptions = [
        adobe_subscription_factory(status=AdobeStatus.SUBSCRIPTION_TERMINATED.value)
    ]
    mock_mpt_get_template_by_name.return_value = {"id": "TPL-1234", "name": "Expired"}
    mocked_agreement_syncer._adobe_subscriptions = adobe_subscriptions

    mocked_agreement_syncer._get_subscriptions_for_update(agreement_factory())  # act

    mock_mpt_get_agreement_subscription.assert_called_once_with(
        mock_mpt_client, mock_mpt_get_agreement_subscription.return_value["id"]
    )
    mock_mpt_terminate_subscription.assert_called_once_with(
        mock_mpt_client,
        mock_mpt_get_agreement_subscription.return_value["id"],
        "Adobe subscription status 1004.",
    )
    mock_mpt_update_agreement_subscription.assert_has_calls([
        mocker.call(
            mock_mpt_client,
            mock_mpt_get_agreement_subscription.return_value["id"],
            template={"id": "TPL-1234", "name": "Expired"},
        ),
        mocker.call(
            mock_mpt_client,
            "SUB-1234-5678",
            template={"id": "TPL-1234", "name": "Expired"},
        ),
    ])


@freeze_time("2025-07-23")
def test_get_subscriptions_for_update_terminated_with_expired_template(
    mocker,
    mock_mpt_client,
    mock_adobe_client,
    agreement_factory,
    subscriptions_factory,
    adobe_customer_factory,
    adobe_subscription_factory,
    mock_mpt_terminate_subscription,
    mock_mpt_get_agreement_subscription,
    mock_mpt_update_agreement_subscription,
    mock_mpt_get_template_by_name,
    mocked_agreement_syncer,
):
    mocked_agreement_syncer._adobe_subscriptions = [
        adobe_subscription_factory(status=AdobeStatus.SUBSCRIPTION_TERMINATED.value)
    ]
    mock_mpt_get_template_by_name.return_value = {"id": "TPL-1234", "name": "Expired"}

    mocked_agreement_syncer._get_subscriptions_for_update(agreement_factory())  # act

    mock_mpt_get_agreement_subscription.assert_called_once_with(
        mock_mpt_client, mock_mpt_get_agreement_subscription.return_value["id"]
    )
    mock_mpt_terminate_subscription.assert_called_once_with(
        mock_mpt_client,
        mock_mpt_get_agreement_subscription.return_value["id"],
        "Adobe subscription status 1004.",
    )
    mock_mpt_update_agreement_subscription.assert_has_calls([
        mocker.call(
            mock_mpt_client,
            mock_mpt_get_agreement_subscription.return_value["id"],
            template={"id": "TPL-1234", "name": "Expired"},
        ),
        mocker.call(
            mock_mpt_client,
            "SUB-1234-5678",
            template={"id": "TPL-1234", "name": "Expired"},
        ),
    ])


@freeze_time("2025-07-23")
def test_get_subscriptions_for_update_terminated_without_template(
    mocker,
    mock_mpt_client,
    mock_adobe_client,
    agreement_factory,
    subscriptions_factory,
    adobe_customer_factory,
    adobe_subscription_factory,
    mock_mpt_terminate_subscription,
    mock_mpt_get_agreement_subscription,
    mock_mpt_update_agreement_subscription,
    mock_mpt_get_template_by_name,
    mocked_agreement_syncer,
):
    mocked_agreement_syncer._adobe_subscriptions = [
        adobe_subscription_factory(status=AdobeStatus.SUBSCRIPTION_TERMINATED.value)
    ]
    mock_mpt_get_template_by_name.side_effect = [{"id": "TPL-1234", "name": "Expired"}, None]

    mocked_agreement_syncer._get_subscriptions_for_update(agreement_factory())  # act

    mock_mpt_get_agreement_subscription.assert_called_once_with(
        mock_mpt_client, mock_mpt_get_agreement_subscription.return_value["id"]
    )
    mock_mpt_terminate_subscription.assert_called_once_with(
        mock_mpt_client,
        mock_mpt_get_agreement_subscription.return_value["id"],
        "Adobe subscription status 1004.",
    )
    mock_mpt_update_agreement_subscription.assert_has_calls([
        mocker.call(
            mock_mpt_client,
            mock_mpt_get_agreement_subscription.return_value["id"],
            template={"id": "TPL-1234", "name": "Expired"},
        )
    ])


@freeze_time("2025-07-23")
def test_get_subscriptions_for_update_terminated_with_assigned_template(
    mock_mpt_client,
    mock_adobe_client,
    agreement_factory,
    subscriptions_factory,
    adobe_customer_factory,
    adobe_subscription_factory,
    mock_mpt_terminate_subscription,
    mock_mpt_get_agreement_subscription,
    mock_mpt_update_agreement_subscription,
    mock_get_template_data_by_adobe_subscription,
    mocked_agreement_syncer,
):
    mocked_agreement_syncer._adobe_subscriptions = [
        adobe_subscription_factory(status=AdobeStatus.SUBSCRIPTION_TERMINATED.value)
    ]
    mock_get_template_data_by_adobe_subscription.side_effect = [
        {"id": "TPL-1234", "name": "Expired"}
    ]
    agreement = agreement_factory()
    agreement["subscriptions"][1]["template"] = {"id": "TPL-1234", "name": "Expired"}
    agreement["subscriptions"] = [agreement["subscriptions"][1]]

    mocked_agreement_syncer._get_subscriptions_for_update(agreement)  # act

    mock_mpt_get_agreement_subscription.assert_not_called()
    mock_mpt_update_agreement_subscription.assert_not_called()


def test_add_missing_subscriptions_none(
    mock_mpt_client,
    mock_adobe_client,
    agreement,
    agreement_factory,
    assets_factory,
    adobe_customer_factory,
    adobe_subscription_factory,
    mock_get_product_items_by_period,
    mock_mpt_create_asset,
    mock_mpt_create_agreement_subscription,
    mocked_agreement_syncer,
):
    adobe_subscriptions = [
        adobe_subscription_factory(subscription_id="a-sub-id", offer_id="65327701CA01A12"),
        adobe_subscription_factory(
            subscription_id="55feb5038045e0b1ebf026e7522e17NA",
            offer_id="65304578CA01A12",
            status=AdobeStatus.SUBSCRIPTION_TERMINATED.value,
        ),
        adobe_subscription_factory(
            subscription_id="1e5b9c974c4ea1bcabdb0fe697a2f1NA", offer_id="65304578CA01A12"
        ),
    ]
    mocked_agreement_syncer._adobe_subscriptions = adobe_subscriptions
    mock_get_product_items_by_period.return_value = []

    mocked_agreement_syncer._add_missing_subscriptions_and_assets()  # act

    mock_get_product_items_by_period.assert_not_called()
    mock_mpt_create_asset.assert_not_called()
    mock_mpt_create_agreement_subscription.assert_not_called()


def test_add_missing_subscriptions_without_vendor_id(
    mock_mpt_client,
    mock_adobe_client,
    agreement,
    agreement_factory,
    assets_factory,
    adobe_customer_factory,
    adobe_subscription_factory,
    mock_get_product_items_by_period,
    mock_mpt_create_asset,
    mock_mpt_create_agreement_subscription,
    mocked_agreement_syncer,
    mock_send_warning,
):
    adobe_subscriptions = [
        adobe_subscription_factory(subscription_id="a-sub-id", offer_id="65327701CA01A12"),
        adobe_subscription_factory(
            subscription_id="55feb5038045e0b1ebf026e7522e17NA",
            offer_id="65304578CA01A12",
            status=AdobeStatus.SUBSCRIPTION_TERMINATED.value,
        ),
        adobe_subscription_factory(
            subscription_id="1e5b9c974c4ea1bcabdb0fe697a2f1NA", offer_id="65304578CA01A12"
        ),
    ]
    agreement = agreement_factory()
    agreement["subscriptions"].append({"id": "SUB-1234-5678", "status": "1004"})
    mocked_agreement_syncer._adobe_subscriptions = adobe_subscriptions
    mocked_agreement_syncer._agreement = agreement
    mock_get_product_items_by_period.return_value = []

    mocked_agreement_syncer._add_missing_subscriptions_and_assets()  # act

    mock_send_warning.assert_called_once_with(
        "Missing external IDs",
        "Missing external IDs for entitlements: SUB-1234-5678 "
        "in the agreement AGR-2119-4550-8674-5962",
    )
    mock_get_product_items_by_period.assert_not_called()
    mock_mpt_create_asset.assert_not_called()
    mock_mpt_create_agreement_subscription.assert_not_called()


@freeze_time("2025-07-24")
def test_add_missing_subscriptions(
    mocker,
    items_factory,
    mock_mpt_client,
    mock_setup_client,
    mock_adobe_client,
    agreement_factory,
    adobe_customer_factory,
    mock_send_warning,
    mock_get_prices_for_skus,
    adobe_subscription_factory,
    mock_get_product_items_by_skus,
    mock_get_product_items_by_period,
    mock_mpt_create_asset,
    mock_mpt_create_agreement_subscription,
    mock_mpt_get_asset_template_by_name,
    mock_get_template_data_by_adobe_subscription,
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
    mocked_agreement_syncer._adobe_customer = adobe_customer_factory()
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
    mock_mpt_get_asset_template_by_name.return_value = None
    mock_get_product_items_by_skus.return_value = [mock_yearly_item, mock_one_time_item]
    mock_get_product_items_by_period.return_value = [mock_yearly_item, mock_one_time_item]
    mock_get_template_data_by_adobe_subscription.return_value = {
        "id": "TPL-1234",
        "name": "Renewing",
    }

    mocked_agreement_syncer._add_missing_subscriptions_and_assets()  # act

    mock_get_product_items_by_skus.assert_called_once_with(
        mock_mpt_client, "PRD-1111-1111", {"65322572CA", "75322572CA"}
    )
    mock_get_product_items_by_period.assert_not_called()
    mock_mpt_get_asset_template_by_name.assert_called_once_with(
        mock_setup_client, "PRD-1111-1111", TEMPLATE_ASSET_DEFAULT
    )
    mock_mpt_create_asset.assert_called_once_with(
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
    mock_mpt_create_agreement_subscription.assert_called_once_with(
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
def test_add_missing_subscriptions_fail_recovery_skus(
    mocker,
    adobe_customer_factory,
    mock_get_prices_for_skus,
    adobe_subscription_factory,
    mock_get_product_items_by_skus,
    mocked_agreement_syncer,
    mock_notify_missing_discount_levels,
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
    mock_get_consumable_discount_level = mocker.patch(
        "adobe_vipm.flows.utils.subscription.get_customer_consumables_discount_level"
    )
    mock_get_consumable_discount_level.side_effect = Exception("Test Exception")
    mocked_agreement_syncer._adobe_subscriptions = adobe_subscriptions
    mocked_agreement_syncer._adobe_customer = adobe_customer_factory()
    mock_get_prices_for_skus.side_effect = [
        {
            "65322572CAT1A10": 12.14,
            "65322572CAT1A11": 11.14,
            "65322572CAT1A12": 10.14,
            "65322572CAT1A13": 9.14,
        },
        {"75322572CAT1A11": 22.14},
    ]

    with pytest.raises(Exception, match="Test Exception"):
        mocked_agreement_syncer._add_missing_subscriptions_and_assets()

    mock_get_product_items_by_skus.assert_called_once()
    mock_notify_missing_discount_levels.assert_called_once()


@freeze_time("2025-07-24")
def test_add_missing_subscriptions_deployment(
    items_factory,
    mock_mpt_client,
    mock_setup_client,
    mock_adobe_client,
    agreement_factory,
    adobe_customer_factory,
    mock_send_warning,
    mock_get_prices_for_skus,
    adobe_subscription_factory,
    mock_get_product_items_by_skus,
    fulfillment_parameters_factory,
    mock_mpt_create_asset,
    mock_mpt_create_agreement_subscription,
    mock_mpt_get_asset_template_by_name,
    mock_get_template_data_by_adobe_subscription,
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
    mocked_agreement_syncer._adobe_customer = adobe_customer_factory()
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
    mock_get_template_data_by_adobe_subscription.return_value = {
        "id": "TPL-1234",
        "name": "Renewing",
    }
    mock_mpt_get_asset_template_by_name.return_value = {"id": "fake_id", "name": "fake_name"}

    mocked_agreement_syncer._add_missing_subscriptions_and_assets()  # act

    mock_get_product_items_by_skus.assert_called_once_with(
        mock_mpt_client, "PRD-1111-1111", {"65322572CA", "75322572CA"}
    )
    mock_mpt_get_asset_template_by_name.assert_called_once_with(
        mock_setup_client, "PRD-1111-1111", TEMPLATE_ASSET_DEFAULT
    )
    mock_mpt_create_asset.assert_called_once_with(
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
    mock_mpt_create_agreement_subscription.assert_called_once_with(
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
            "name": "Subscription for Awesome product",
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
    mock_send_warning,
    adobe_subscription_factory,
    mock_get_product_items_by_skus,
    mock_get_product_items_by_period,
    mock_mpt_create_asset,
    mock_mpt_create_agreement_subscription,
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
    mocked_agreement_syncer._adobe_customer = adobe_customer_factory()

    mocked_agreement_syncer._add_missing_subscriptions_and_assets()  # act

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
    mock_mpt_create_asset.assert_not_called()
    mock_mpt_create_agreement_subscription.assert_not_called()


def test_process_orphaned_deployment_subscriptions_none(
    mock_adobe_client,
    agreement_factory,
    mock_add_missing_subscriptions_and_assets,
    mock_get_agreements_by_customer_deployments,
    fulfillment_parameters_factory,
    mock_get_prices_for_skus,
    mock_check_update_airtable_missing_deployments,
    mocked_agreement_syncer,
    adobe_subscription_factory,
    adobe_customer_factory,
    subscriptions_factory,
):
    mock_adobe_client.get_customer_deployments_active_status.return_value = [
        {
            "deploymentId": "deployment-id",
            "status": "1000",
            "companyProfile": {"address": {"country": "DE"}},
        }
    ]
    deployment_agreement = agreement_factory(
        assets=[],
        fulfillment_parameters=fulfillment_parameters_factory(
            global_customer="yes",
            deployment_id="deployment-id",
        ),
        subscriptions=subscriptions_factory(
            subscription_id="mpt_subscription_id",
            adobe_subscription_id="specific_subscription_id",
        ),
    )
    mock_get_agreements_by_customer_deployments.return_value = [deployment_agreement]
    adobe_subscription = adobe_subscription_factory(
        subscription_id="specific_subscription_id",
        deployment_id="deployment-id",
    )
    mocked_agreement_syncer._adobe_subscriptions = [adobe_subscription]
    mocked_agreement_syncer._adobe_customer = adobe_customer_factory(global_sales_enabled=True)

    mocked_agreement_syncer.sync(sync_prices=True)  # act

    mock_adobe_client.update_subscription.assert_not_called()


def test_process_orphaned_deployment_subscriptions_error(
    mock_adobe_client,
    agreement_factory,
    mock_add_missing_subscriptions_and_assets,
    mock_get_agreements_by_customer_deployments,
    fulfillment_parameters_factory,
    mock_get_prices_for_skus,
    mock_check_update_airtable_missing_deployments,
    mocked_agreement_syncer,
    adobe_subscription_factory,
    adobe_customer_factory,
    mock_send_exception,
    caplog,
):
    mock_adobe_client.update_subscription.side_effect = Exception("Boom!")
    mock_adobe_client.get_customer_deployments_active_status.return_value = [
        {
            "deploymentId": "deployment-id",
            "status": "1000",
            "companyProfile": {"address": {"country": "DE"}},
        }
    ]
    deployment_agreement = agreement_factory(
        assets=[],
        fulfillment_parameters=fulfillment_parameters_factory(
            global_customer="yes", deployment_id="deployment_id"
        ),
    )
    mock_get_agreements_by_customer_deployments.return_value = [deployment_agreement]
    adobe_subscription = adobe_subscription_factory(
        subscription_id="specific_subscription_id", deployment_id="deployment-id"
    )
    mocked_agreement_syncer._adobe_subscriptions = [adobe_subscription]
    mocked_agreement_syncer._adobe_customer = adobe_customer_factory(global_sales_enabled=True)

    mocked_agreement_syncer.sync(sync_prices=True)  # act

    mock_adobe_client.update_subscription.assert_called_once_with(
        "AUT-1234-5678", "a-client-id", "specific_subscription_id", auto_renewal=False
    )
    mock_send_exception.assert_called_once_with(
        "Error disabling auto-renewal for orphaned Adobe subscription specific_subscription_id.",
        "Boom!",
    )


@pytest.mark.parametrize(
    "subscription_status",
    [AdobeStatus.SUBSCRIPTION_INACTIVE.value, AdobeStatus.PENDING.value],
)
def test_process_orphaned_deployment_subscriptions_skip_on_status(
    subscription_status,
    mock_adobe_client,
    agreement_factory,
    mock_add_missing_subscriptions_and_assets,
    mock_get_agreements_by_customer_deployments,
    fulfillment_parameters_factory,
    mock_get_prices_for_skus,
    mock_check_update_airtable_missing_deployments,
    mocked_agreement_syncer,
    adobe_subscription_factory,
    adobe_customer_factory,
    caplog,
):
    """Test that orphaned subscriptions with SUBSCRIPTION_INACTIVE or PENDING status are skipped."""
    mock_adobe_client.get_customer_deployments_active_status.return_value = [
        {
            "deploymentId": "deployment-id",
            "status": "1000",
            "companyProfile": {"address": {"country": "DE"}},
        }
    ]
    deployment_agreement = agreement_factory(
        assets=[],
        status=AgreementStatus.ACTIVE.value,
        fulfillment_parameters=fulfillment_parameters_factory(
            global_customer="yes", deployment_id="deployment_id"
        ),
    )
    mock_get_agreements_by_customer_deployments.return_value = [deployment_agreement]
    mocked_agreement_syncer._adobe_subscriptions = [
        adobe_subscription_factory(
            subscription_id="inactive_subscription_id",
            deployment_id="deployment-id",
            autorenewal_enabled=True,
            status=subscription_status,
        ),
    ]
    mocked_agreement_syncer._adobe_customer = adobe_customer_factory(global_sales_enabled=True)

    with caplog.at_level(logging.INFO):
        mocked_agreement_syncer.sync(sync_prices=True)  # act

    mock_adobe_client.update_subscription.assert_not_called()
    assert "Skipping orphaned subscription inactive_subscription_id" in caplog.text


def test_process_orphaned_deployment_subscriptions_skip_autorenewal_false_with_logging(
    mock_adobe_client,
    agreement_factory,
    mock_get_agreements_by_customer_deployments,
    fulfillment_parameters_factory,
    mock_get_prices_for_skus,
    mock_check_update_airtable_missing_deployments,
    mocked_agreement_syncer,
    adobe_subscription_factory,
    adobe_customer_factory,
    caplog,
):
    """Test that orphaned subscriptions with auto-renewal disabled are skipped and logged."""
    mock_adobe_client.get_customer_deployments_active_status.return_value = [
        {
            "deploymentId": "deployment-id",
            "status": "1000",
            "companyProfile": {"address": {"country": "DE"}},
        }
    ]
    deployment_agreement = agreement_factory(
        assets=[],
        status=AgreementStatus.ACTIVE.value,
        fulfillment_parameters=fulfillment_parameters_factory(
            global_customer="yes", deployment_id="deployment_id"
        ),
    )
    mock_get_agreements_by_customer_deployments.return_value = [deployment_agreement]
    mocked_agreement_syncer._adobe_subscriptions = [
        adobe_subscription_factory(
            subscription_id="no_autorenewal_subscription_id",
            deployment_id="deployment-id",
            autorenewal_enabled=False,
            status=AdobeStatus.PROCESSED.value,
        ),
    ]
    mocked_agreement_syncer._adobe_customer = adobe_customer_factory(global_sales_enabled=True)

    with caplog.at_level(logging.INFO):
        mocked_agreement_syncer.sync(sync_prices=True)  # act

    mock_adobe_client.update_subscription.assert_not_called()
    assert "Skipping orphaned subscription no_autorenewal_subscription_id" in caplog.text
    assert "(auto-renewal: False, status: 1000)" in caplog.text


def test_sync_agreement_without_subscriptions(
    mocked_agreement_syncer, mock_mpt_client, mock_adobe_client, mock_agreement, caplog
):
    mock_adobe_client.get_subscriptions.return_value = {"items": []}

    with caplog.at_level(logging.INFO):
        sync_agreement(
            mock_mpt_client, mock_adobe_client, mock_agreement, dry_run=True, sync_prices=True
        )  # act

    assert "Skipping price sync - no subscriptions found for the customer" in caplog.text


@freeze_time("2025-07-24")
def test_add_missing_subscriptions_without_price(
    mocker,
    items_factory,
    mock_mpt_client,
    mock_setup_client,
    mock_adobe_client,
    agreement_factory,
    adobe_customer_factory,
    mock_send_warning,
    mock_get_prices_for_skus,
    adobe_subscription_factory,
    mock_get_product_items_by_skus,
    mock_get_product_items_by_period,
    mock_mpt_create_asset,
    mock_mpt_create_agreement_subscription,
    mock_mpt_get_asset_template_by_name,
    mock_get_template_data_by_adobe_subscription,
    mocked_agreement_syncer,
):
    adobe_subscriptions = [
        adobe_subscription_factory(
            subscription_id="2e5b9c974c4ea1bcabdb0fe697a2f1NA", offer_id="65322572CAT1A13"
        ),
    ]
    mocked_agreement_syncer._adobe_subscriptions = adobe_subscriptions
    mocked_agreement_syncer._customer = adobe_customer_factory()
    mock_get_prices_for_skus.side_effect = [
        {},
    ]
    mock_yearly_item = items_factory(item_id=193, external_vendor_id="65322572CA")[0]
    mock_one_time_item = items_factory(
        item_id=194,
        name="One time item",
        external_vendor_id="75322572CA",
        term_period=ItemTermsModel.ONE_TIME.value,
        term_model=ItemTermsModel.ONE_TIME.value,
    )[0]
    mock_mpt_get_asset_template_by_name.return_value = None
    mock_get_product_items_by_skus.return_value = [mock_yearly_item, mock_one_time_item]
    mock_get_product_items_by_period.return_value = [mock_yearly_item, mock_one_time_item]
    mock_get_template_data_by_adobe_subscription.return_value = {
        "id": "TPL-1234",
        "name": "Renewing",
    }

    mocked_agreement_syncer._add_missing_subscriptions_and_assets()  # act

    mock_get_product_items_by_skus.assert_called_once_with(
        mock_mpt_client, "PRD-1111-1111", {"65322572CA"}
    )
    mock_get_product_items_by_period.assert_not_called()
    mock_mpt_create_agreement_subscription.assert_called_once_with(
        mock_mpt_client,
        {
            "status": "Active",
            "commitmentDate": "2026-10-11",
            "price": {"unitPP": {}},
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


def test_check_update_airtable_missing_deployments(
    mocker,
    agreement_factory,
    mock_send_warning,
    mock_airtable_base_info,
    adobe_deployment_factory,
    adobe_subscription_factory,
    fulfillment_parameters_factory,
    mock_get_gc_agreement_deployments_by_main_agreement,
    mocked_agreement_syncer,
    mock_get_gc_agreement_deployment_model,
):
    deployments = [
        get_gc_agreement_deployment_model(AirTableBaseInfo(api_key="api-key", base_id="base-id"))(
            deployment_id=f"{i}"
        )
        for i in range(1, 4)
    ]
    mock_get_gc_agreement_deployments_by_main_agreement.return_value = deployments
    agreement = agreement_factory(fulfillment_parameters=fulfillment_parameters_factory())
    mocked_agreement_syncer._agreement = agreement
    adobe_deployments = [
        adobe_deployment_factory(deployment_id=f"deployment-{i}") for i in range(1, 4)
    ]
    mocked_agreement_syncer._adobe_subscriptions = [
        adobe_subscription_factory(
            subscription_id=f"subscriptionId{i}", deployment_id=f"deployment-{i}"
        )
        for i in range(3)
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

    mocked_agreement_syncer._check_update_airtable_missing_deployments(adobe_deployments)  # act

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
            customer_id=mocked_agreement_syncer._adobe_customer["customerId"],
            deployment_currency="USD",
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
            customer_id=mocked_agreement_syncer._adobe_customer["customerId"],
            deployment_currency="USD",
            deployment_country="DE",
            licensee_id="LC-321-321-321",
        ),
    ]
    assert mock_get_gc_agreement_deployment_model.mock_calls[2][0] == "batch_save"
    assert len(mock_get_gc_agreement_deployment_model.mock_calls[2].args[0]) == 2
    mock_send_warning.assert_called_once()


def test_check_update_airtable_missing_deployments_none(
    agreement_factory,
    mock_send_warning,
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
    ])  # act

    mock_create_gc_agreement_deployments.assert_not_called()
    mock_send_warning.assert_not_called()


def test_not_syncing_unknown_products(
    mocker, mock_mpt_client, mock_adobe_client, agreement_factory, mocked_agreement_syncer, caplog
):
    mock_get_customer_or_process_lost_customer = mocker.patch(
        "adobe_vipm.flows.sync.agreement.get_customer_or_process_lost_customer", spec=True
    )
    agreement = agreement_factory()
    agreement["product"]["id"] = "NOT_CONFIGURED_PRODUCT"

    sync_agreement(
        mock_mpt_client, mock_adobe_client, agreement, dry_run=False, sync_prices=True
    )  # act

    mock_get_customer_or_process_lost_customer.assert_not_called()
    assert caplog.messages == ["Product NOT_CONFIGURED_PRODUCT not in MPT_PRODUCTS_IDS. Skipping."]


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
        "in(product.id,(PRD-1111-1111))&"
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
        "in(product.id,(PRD-1111-1111))&"
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
        "in(product.id,(PRD-1111-1111))&"
        "any(subscriptions,any(parameters.fulfillment,and(eq(externalId,renewalDate),in(displayValue,(2026-07-15,2026-06-15,2026-05-15,2026-04-15,2026-03-15,2026-02-15,2026-01-15,2025-12-15,2025-11-15,2025-10-15,2025-09-15,2025-08-15,2025-07-15,2025-06-15,2025-05-15,2025-04-15,2025-03-15,2025-02-15,2025-01-15,2024-12-15,2024-11-15,2024-10-15,2024-09-15,2024-08-15)))))&"
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
        mock_mpt_client, constants.THREE_YC_TEMP_3YC_STATUSES
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
        mock_mpt_client, constants.THREE_YC_TEMP_3YC_STATUSES
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
        "adobe_vipm.flows.sync.agreement.get_agreements_by_3yc_commitment_request_invitation",
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
        mock_mpt_client, constants.THREE_YC_TEMP_3YC_STATUSES
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
        mock_mpt_client, constants.THREE_YC_TEMP_3YC_STATUSES
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
        AdobeAPIError(400, {"code": AdobeStatus.INVALID_CUSTOMER.value, "message": "Test error"})
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


def test_get_customer_or_process_lost_customer_deployment_error(
    mocker,
    mock_mpt_client,
    mock_adobe_client,
    mock_send_warning,
    mock_send_exception,
    mock_mpt_terminate_subscription,
    mock_get_agreements_by_customer_deployments,
    agreement,
    adobe_customer_factory,
):
    mock_adobe_client.get_customer.side_effect = [
        AdobeAPIError(400, {"code": AdobeStatus.INVALID_CUSTOMER.value, "message": "Test error"})
    ]
    mock_adobe_client.get_customer_deployments_active_status.side_effect = [
        AdobeAPIError(
            500,
            {
                "code": AdobeStatus.INACTIVE_OR_GENERIC_FAILURE.value,
                "message": "Inactive or generic failure",
            },
        )
    ]

    result = get_customer_or_process_lost_customer(
        mock_mpt_client, mock_adobe_client, agreement, "fake_customer_id", dry_run=False
    )

    assert result is None
    mock_adobe_client.get_customer.assert_called_once_with("AUT-4785-7184", "fake_customer_id")
    mock_send_warning.assert_called_once()
    mock_send_exception.assert_called_once()


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
        AdobeAPIError(400, {"code": AdobeStatus.INVALID_CUSTOMER.value, "message": "Test error"})
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
