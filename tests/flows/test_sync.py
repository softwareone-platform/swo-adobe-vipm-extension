import logging

import pytest
from freezegun import freeze_time

from adobe_vipm.adobe.errors import AdobeAPIError
from adobe_vipm.flows.sync import (
    sync_agreement,
    sync_agreements_by_3yc_end_date,
    sync_agreements_by_agreement_ids,
    sync_agreements_by_coterm_date,
    sync_agreements_by_next_sync,
    sync_all_agreements,
)
from adobe_vipm.flows.utils import get_adobe_customer_id

pytestmark = pytest.mark.usefixtures("mock_adobe_config")


@freeze_time("2025-06-23")
def test_sync_agreement_prices(
    mocker,
    agreement_factory,
    subscriptions_factory,
    lines_factory,
    adobe_subscription_factory,
    adobe_customer_factory,
    mock_get_adobe_product_by_marketplace_sku,
):
    mocker.patch(
        "adobe_vipm.flows.sync.get_adobe_product_by_marketplace_sku",
        side_effect=mock_get_adobe_product_by_marketplace_sku,
    )

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

    authorization_id = agreement["authorization"]["id"]
    customer_id = get_adobe_customer_id(agreement)

    mocked_mpt_client = mocker.MagicMock()

    mocked_adobe_client = mocker.MagicMock()
    mocked_adobe_client.get_subscription.side_effect = [
        adobe_subscription,
        another_adobe_subscription,
    ]
    mocked_adobe_client.get_customer.return_value = adobe_customer_factory(coterm_date="2025-04-04")

    mocker.patch(
        "adobe_vipm.airtable.models.get_adobe_product_by_marketplace_sku",
        side_effect=mock_get_adobe_product_by_marketplace_sku,
    )

    mocker.patch(
        "adobe_vipm.flows.sync.get_adobe_client",
        return_value=mocked_adobe_client,
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
        "adobe_vipm.flows.sync.update_agreement_subscription",
    )

    mocked_update_agreement = mocker.patch(
        "adobe_vipm.flows.sync.update_agreement",
    )

    sync_agreement(mocked_mpt_client, agreement, False)

    assert mocked_get_agreement_subscription.call_args_list == [
        mocker.call(
            mocked_mpt_client,
            mpt_subscription["id"],
        ),
        mocker.call(
            mocked_mpt_client,
            another_mpt_subscription["id"],
        ),
    ]
    assert mocked_adobe_client.get_subscription.call_args_list == [
        mocker.call(
            authorization_id,
            customer_id,
            mpt_subscription["externalIds"]["vendor"],
        ),
        mocker.call(
            authorization_id,
            customer_id,
            another_mpt_subscription["externalIds"]["vendor"],
        ),
    ]

    assert mocked_update_agreement_subscription.call_args_list == [
        mocker.call(
            mocked_mpt_client,
            mpt_subscription["id"],
            lines=[{"id": "ALI-2119-4550-8674-5962-0001", "price": {"unitPP": 1234.55}}],
            parameters={
                "fulfillment": [
                    {
                        "externalId": "adobeSKU",
                        "value": "65304578CA01A12",
                    },
                    {
                        "externalId": "currentQuantity",
                        "value": str(adobe_subscription["currentQuantity"]),
                    },
                    {
                        "externalId": "renewalQuantity",
                        "value": str(adobe_subscription["autoRenewal"]["renewalQuantity"]),
                    },
                    {
                        "externalId": "renewalDate",
                        "value": adobe_subscription["renewalDate"],
                    },
                ]
            },
            commitmentDate="2025-04-04",
            autoRenew=adobe_subscription["autoRenewal"]["enabled"],
        ),
        mocker.call(
            mocked_mpt_client,
            another_mpt_subscription["id"],
            lines=[{"id": "ALI-2119-4550-8674-5962-0001", "price": {"unitPP": 20.22}}],
            parameters={
                "fulfillment": [
                    {
                        "externalId": "adobeSKU",
                        "value": "77777777CA01A12",
                    },
                    {
                        "externalId": "currentQuantity",
                        "value": str(another_adobe_subscription["currentQuantity"]),
                    },
                    {
                        "externalId": "renewalQuantity",
                        "value": str(another_adobe_subscription["autoRenewal"]["renewalQuantity"]),
                    },
                    {
                        "externalId": "renewalDate",
                        "value": another_adobe_subscription["renewalDate"],
                    },
                ]
            },
            commitmentDate="2025-04-04",
            autoRenew=another_adobe_subscription["autoRenewal"]["enabled"],
        ),
    ]

    expected_lines = lines_factory(
        external_vendor_id="77777777CA",
        unit_purchase_price=20.22,
    )

    assert mocked_update_agreement.call_args_list == [
        mocker.call(
            mocked_mpt_client,
            agreement["id"],
            lines=expected_lines,
            parameters={"fulfillment": [{"externalId": "nextSync", "value": "2025-04-05"}]},
        ),
        mocker.call(
            mocked_mpt_client,
            agreement["id"],
            parameters={"fulfillment": [{"externalId": "lastSyncDate", "value": "2025-06-23"}]},
        ),
    ]


def test_sync_agreement_prices_dry_run(
    mocker,
    agreement_factory,
    subscriptions_factory,
    lines_factory,
    adobe_subscription_factory,
    adobe_customer_factory,
    mock_get_adobe_product_by_marketplace_sku,
):
    agreement = agreement_factory(
        lines=lines_factory(
            external_vendor_id="77777777CA",
            unit_purchase_price=10.11,
        )
    )
    mpt_subscription = subscriptions_factory()[0]
    adobe_subscription = adobe_subscription_factory()

    authorization_id = agreement["authorization"]["id"]
    customer_id = get_adobe_customer_id(agreement)

    mocked_mpt_client = mocker.MagicMock()

    mocked_adobe_client = mocker.MagicMock()
    mocked_adobe_client.get_subscription.return_value = adobe_subscription
    mocked_adobe_client.get_customer.return_value = adobe_customer_factory(coterm_date="2025-04-04")

    mocker.patch(
        "adobe_vipm.flows.sync.get_adobe_client",
        return_value=mocked_adobe_client,
    )

    mocker.patch(
        "adobe_vipm.flows.sync.get_adobe_product_by_marketplace_sku",
        side_effect=mock_get_adobe_product_by_marketplace_sku,
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

    sync_agreement(mocked_mpt_client, agreement, True)

    mocked_get_agreement_subscription.assert_called_once_with(
        mocked_mpt_client,
        mpt_subscription["id"],
    )
    mocked_adobe_client.get_subscription.assert_called_once_with(
        authorization_id,
        customer_id,
        mpt_subscription["externalIds"]["vendor"],
    )

    mocked_update_agreement_subscription.assert_not_called()
    mocked_update_agreement.assert_not_called()


def test_sync_agreement_prices_exception(
    mocker,
    agreement_factory,
    subscriptions_factory,
    adobe_api_error_factory,
    adobe_customer_factory,
    caplog,
):
    agreement = agreement_factory()
    mpt_subscription = subscriptions_factory()[0]

    mocked_mpt_client = mocker.MagicMock()

    mocked_adobe_client = mocker.MagicMock()
    mocked_adobe_client.get_customer.return_value = adobe_customer_factory()
    mocked_adobe_client.get_subscription.side_effect = AdobeAPIError(
        400,
        adobe_api_error_factory(code="9999", message="Error from Adobe."),
    )

    mocker.patch(
        "adobe_vipm.flows.sync.get_adobe_client",
        return_value=mocked_adobe_client,
    )

    mocked_get_agreement_subscription = mocker.patch(
        "adobe_vipm.flows.sync.get_agreement_subscription",
        return_value=mpt_subscription,
    )

    mocked_update_agreement_subscription = mocker.patch(
        "adobe_vipm.flows.sync.update_agreement_subscription",
    )

    mocked_update_agreement = mocker.patch(
        "adobe_vipm.flows.sync.update_agreement",
    )

    mocked_notifier = mocker.patch(
        "adobe_vipm.flows.sync.notify_agreement_unhandled_exception_in_teams",
    )

    with caplog.at_level(logging.ERROR):
        sync_agreement(mocked_mpt_client, agreement, False)

    assert f"Error synchronizing agreement {agreement['id']}" in caplog.text

    mocked_get_agreement_subscription.assert_called_once_with(
        mocked_mpt_client,
        mpt_subscription["id"],
    )

    mocked_update_agreement_subscription.assert_not_called()
    mocked_update_agreement.assert_not_called()
    mocked_notifier.assert_called_once()
    assert mocked_notifier.call_args_list[0].args[0] == agreement["id"]


def test_sync_agreement_prices_skip_processing(
    mocker, agreement_factory, caplog, adobe_customer_factory
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
    mocked_mpt_client = mocker.MagicMock()

    mocker.patch("adobe_vipm.flows.sync.get_adobe_client")

    mocked_update_agreement_subscription = mocker.patch(
        "adobe_vipm.flows.sync.update_agreement_subscription",
    )

    mocked_update_agreement = mocker.patch(
        "adobe_vipm.flows.sync.update_agreement",
    )
    mocked_adobe_client = mocker.MagicMock()
    customer = adobe_customer_factory()
    mocked_adobe_client.get_customer.return_value = customer

    with caplog.at_level(logging.INFO):
        sync_agreement(mocked_mpt_client, agreement, False)

    assert f"Agreement {agreement['id']} has processing subscriptions, skip it" in caplog.text

    mocked_update_agreement_subscription.assert_not_called()
    mocked_update_agreement.assert_not_called()


@pytest.mark.parametrize("dry_run", [True, False])
def test_sync_agreements_by_agreement_ids(mocker, agreement_factory, dry_run):
    agreement = agreement_factory()
    mocked_mpt_client = mocker.MagicMock()
    mocker.patch(
        "adobe_vipm.flows.sync.get_agreements_by_ids",
        return_value=[agreement],
    )
    mocked_sync_agreement = mocker.patch(
        "adobe_vipm.flows.sync.sync_agreement",
    )

    sync_agreements_by_agreement_ids(mocked_mpt_client, [agreement["id"]], dry_run)
    mocked_sync_agreement.assert_called_once_with(
        mocked_mpt_client,
        agreement,
        dry_run,
    )


@pytest.mark.parametrize("dry_run", [True, False])
def test_sync_all_agreements(mocker, agreement_factory, dry_run):
    agreement = agreement_factory()
    mocked_mpt_client = mocker.MagicMock()
    mocker.patch(
        "adobe_vipm.flows.sync.get_all_agreements",
        return_value=[agreement],
    )
    mocked_sync_agreement = mocker.patch(
        "adobe_vipm.flows.sync.sync_agreement",
    )

    sync_all_agreements(mocked_mpt_client, dry_run)
    mocked_sync_agreement.assert_called_once_with(
        mocked_mpt_client,
        agreement,
        dry_run,
    )


@pytest.mark.parametrize("dry_run", [True, False])
def test_sync_agreements_by_next_sync(mocker, agreement_factory, dry_run):
    agreement = agreement_factory()
    mocked_mpt_client = mocker.MagicMock()
    mocker.patch(
        "adobe_vipm.flows.sync.get_agreements_by_next_sync",
        return_value=[agreement],
    )
    mocked_sync_agreement = mocker.patch(
        "adobe_vipm.flows.sync.sync_agreement",
    )

    sync_agreements_by_next_sync(mocked_mpt_client, dry_run)
    mocked_sync_agreement.assert_called_once_with(
        mocked_mpt_client,
        agreement,
        dry_run,
    )


@freeze_time("2024-11-09")
@pytest.mark.parametrize("dry_run", [True, False])
def test_sync_agreements_by_3yc_end_date(mocker, agreement_factory, dry_run):
    agreement = agreement_factory()
    mocked_mpt_client = mocker.MagicMock()
    mocked_get_agreements_by_query = mocker.patch(
        "adobe_vipm.flows.sync.get_agreements_by_query",
        return_value=[agreement],
        autospec=True,
    )
    mocked_sync_agreement = mocker.patch(
        "adobe_vipm.flows.sync.sync_agreement",
        autospec=True,
    )

    sync_agreements_by_3yc_end_date(mocked_mpt_client, dry_run)

    mocked_sync_agreement.assert_called_once_with(
        mocked_mpt_client,
        agreement,
        dry_run,
    )
    mocked_get_agreements_by_query.assert_called_once_with(
        mocked_mpt_client,
        "eq(status,Active)&"
        "any(parameters.fulfillment,and(eq(externalId,3YCEndDate),eq(displayValue,2024-11-08)))&"
        "any(parameters.fulfillment,and(eq(externalId,lastSyncDate),ne(displayValue,2024-11-09)))&"
        "select=subscriptions,authorization,parameters,listing,lines,"
        "-template,-name,-status,-authorization,-vendor,-client,-price,-licensee,-buyer,-seller,"
        "-externalIds",
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

    sync_agreements_by_coterm_date(mock_mpt_client, dry_run)

    mocked_sync_agreement.assert_called_once_with(
        mock_mpt_client,
        agreement,
        dry_run,
    )
    mocked_get_agreements_by_query.assert_called_once_with(
        mock_mpt_client,
        "eq(status,Active)&"
        "any(parameters.fulfillment,and(eq(externalId,cotermDate),eq(displayValue,2025-06-15)))&"
        "any(parameters.fulfillment,and(eq(externalId,lastSyncDate),ne(displayValue,2025-06-16)))&"
        "select=subscriptions,authorization,parameters,listing,lines,"
        "-template,-name,-status,-authorization,-vendor,-client,-price,-licensee,-buyer,-seller,"
        "-externalIds",
    )


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
):
    agreement = agreement_factory(
        lines=lines_factory(
            external_vendor_id="77777777CA",
            unit_purchase_price=10.11,
        )
    )
    mpt_subscription = subscriptions_factory()[0]
    adobe_subscription = adobe_subscription_factory()

    authorization_id = agreement["authorization"]["id"]
    customer_id = get_adobe_customer_id(agreement)

    mocked_mpt_client = mocker.MagicMock()

    mocked_adobe_client = mocker.MagicMock()
    mocked_adobe_client.get_subscription.return_value = adobe_subscription
    mocked_adobe_client.get_customer.return_value = adobe_customer_factory(
        coterm_date="2025-04-04",
        commitment=adobe_commitment_factory(),
    )

    mocker.patch(
        "adobe_vipm.flows.sync.get_adobe_client",
        return_value=mocked_adobe_client,
    )

    mocked_get_agreement_subscription = mocker.patch(
        "adobe_vipm.flows.sync.get_agreement_subscription",
        return_value=mpt_subscription,
    )

    mocker.patch(
        "adobe_vipm.airtable.models.get_prices_for_3yc_skus",
        side_effect=[{"65304578CA01A12": 1234.55}, {"77777777CA01A12": 20.22}],
    )

    mocked_update_agreement_subscription = mocker.patch(
        "adobe_vipm.flows.sync.update_agreement_subscription",
    )

    mocked_update_agreement = mocker.patch(
        "adobe_vipm.flows.sync.update_agreement",
    )

    mocker.patch(
        "adobe_vipm.flows.sync.get_adobe_product_by_marketplace_sku",
        side_effect=mock_get_adobe_product_by_marketplace_sku,
    )

    sync_agreement(mocked_mpt_client, agreement, False)

    mocked_get_agreement_subscription.assert_called_once_with(
        mocked_mpt_client,
        mpt_subscription["id"],
    )
    mocked_adobe_client.get_subscription.assert_called_once_with(
        authorization_id,
        customer_id,
        mpt_subscription["externalIds"]["vendor"],
    )

    mocked_update_agreement_subscription.assert_called_once_with(
        mocked_mpt_client,
        mpt_subscription["id"],
        lines=[{"id": "ALI-2119-4550-8674-5962-0001", "price": {"unitPP": 1234.55}}],
        parameters={
            "fulfillment": [
                {"externalId": "adobeSKU", "value": "65304578CA01A12"},
                {
                    "externalId": "currentQuantity",
                    "value": str(adobe_subscription["currentQuantity"]),
                },
                {
                    "externalId": "renewalQuantity",
                    "value": str(adobe_subscription["autoRenewal"]["renewalQuantity"]),
                },
                {
                    "externalId": "renewalDate",
                    "value": adobe_subscription["renewalDate"],
                },
            ]
        },
        commitmentDate="2025-04-04",
        autoRenew=adobe_subscription["autoRenewal"]["enabled"],
    )

    expected_lines = lines_factory(
        external_vendor_id="77777777CA",
        unit_purchase_price=20.22,
    )

    assert mocked_update_agreement.call_args_list == [
        mocker.call(
            mocked_mpt_client,
            agreement["id"],
            lines=expected_lines,
            parameters={"fulfillment": [{"externalId": "nextSync", "value": "2025-04-05"}]},
        ),
        mocker.call(
            mocked_mpt_client,
            agreement["id"],
            parameters={"fulfillment": [{"externalId": "lastSyncDate", "value": "2024-11-09"}]},
        ),
    ]


@freeze_time("2025-06-19")
@pytest.mark.parametrize("dry_run", [True, False])
def test_sync_global_customer_parameter(
    mocker,
    agreement_factory,
    subscriptions_factory,
    fulfillment_parameters_factory,
    lines_factory,
    adobe_subscription_factory,
    adobe_customer_factory,
    mock_get_adobe_product_by_marketplace_sku,
    dry_run,
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
    mpt_subscription = subscriptions_factory()[0]
    another_mpt_subscription = subscriptions_factory(
        adobe_sku="77777777CA01A12",
        adobe_subscription_id="b-sub-id",
        subscription_id="SUB-1000-2000-5000",
    )[0]
    deployment_subscription = subscriptions_factory(
        adobe_subscription_id="d-sub-id",
    )[0]
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

    authorization_id = agreement["authorization"]["id"]
    customer_id = get_adobe_customer_id(agreement)

    mocked_mpt_client = mocker.MagicMock()

    mocked_adobe_client = mocker.MagicMock()
    mocked_adobe_client.get_subscription.side_effect = [
        adobe_subscription,
        another_adobe_subscription,
        adobe_deployment_subscription,
    ]
    mocked_adobe_client.get_customer.return_value = adobe_customer_factory(
        coterm_date="2025-04-04",
        global_sales_enabled=True,
    )
    mocked_adobe_client.get_customer_deployments_active_status.return_value = [
        {
            "deploymentId": "deployment-id",
            "status": "1000",
            "companyProfile": {"address": {"country": "DE"}},
        }
    ]
    deployment_agreements = [
        agreement_factory(
            fulfillment_parameters=fulfillment_parameters_factory(
                global_customer="",
                deployment_id="deployment-1",
                deployments="",
            ),
            lines=lines_factory(
                external_vendor_id="77777777CA",
                unit_purchase_price=10.11,
            ),
        )
    ]
    mocker.patch(
        "adobe_vipm.flows.sync.get_agreements_by_customer_deployments",
        return_value=deployment_agreements,
    )

    mocker.patch(
        "adobe_vipm.flows.sync.get_adobe_client",
        return_value=mocked_adobe_client,
    )

    mocked_get_agreement_subscription = mocker.patch(
        "adobe_vipm.flows.sync.get_agreement_subscription",
        side_effect=[
            mpt_subscription,
            another_mpt_subscription,
            deployment_subscription,
        ],
    )

    mocker.patch(
        "adobe_vipm.airtable.models.get_prices_for_skus",
        side_effect=[
            {"65304578CA01A12": 1234.55, "77777777CA01A12": 20.22},
            {"65304578CA01A12": 1234.55, "77777777CA01A12": 20.22},
            {"65304578CA01A12": 1234.55, "77777777CA01A12": 20.22},
            {"65304578CA01A12": 1234.55, "77777777CA01A12": 20.22},
        ],
    )

    mocked_update_agreement_subscription = mocker.patch(
        "adobe_vipm.flows.sync.update_agreement_subscription",
    )

    mocked_update_agreement = mocker.patch(
        "adobe_vipm.flows.sync.update_agreement",
    )

    mocker.patch(
        "adobe_vipm.flows.sync.get_adobe_product_by_marketplace_sku",
        side_effect=mock_get_adobe_product_by_marketplace_sku,
    )

    sync_agreement(mocked_mpt_client, agreement, dry_run)

    assert mocked_get_agreement_subscription.call_args_list == [
        mocker.call(
            mocked_mpt_client,
            mpt_subscription["id"],
        ),
        mocker.call(
            mocked_mpt_client,
            another_mpt_subscription["id"],
        ),
        mocker.call(
            mocked_mpt_client,
            deployment_subscription["id"],
        ),
    ]
    assert mocked_adobe_client.get_subscription.call_args_list == [
        mocker.call(
            authorization_id,
            customer_id,
            mpt_subscription["externalIds"]["vendor"],
        ),
        mocker.call(
            authorization_id,
            customer_id,
            another_mpt_subscription["externalIds"]["vendor"],
        ),
        mocker.call(
            authorization_id,
            customer_id,
            deployment_subscription["externalIds"]["vendor"],
        ),
    ]

    if not dry_run:
        assert mocked_update_agreement_subscription.call_args_list == [
            mocker.call(
                mocked_mpt_client,
                mpt_subscription["id"],
                lines=[{"id": "ALI-2119-4550-8674-5962-0001", "price": {"unitPP": 1234.55}}],
                parameters={
                    "fulfillment": [
                        {
                            "externalId": "adobeSKU",
                            "value": "65304578CA01A12",
                        },
                        {
                            "externalId": "currentQuantity",
                            "value": str(adobe_subscription["currentQuantity"]),
                        },
                        {
                            "externalId": "renewalQuantity",
                            "value": str(adobe_subscription["autoRenewal"]["renewalQuantity"]),
                        },
                        {
                            "externalId": "renewalDate",
                            "value": adobe_subscription["renewalDate"],
                        },
                    ]
                },
                commitmentDate="2025-04-04",
                autoRenew=adobe_subscription["autoRenewal"]["enabled"],
            ),
            mocker.call(
                mocked_mpt_client,
                another_mpt_subscription["id"],
                lines=[{"id": "ALI-2119-4550-8674-5962-0001", "price": {"unitPP": 20.22}}],
                parameters={
                    "fulfillment": [
                        {
                            "externalId": "adobeSKU",
                            "value": "77777777CA01A12",
                        },
                        {
                            "externalId": "currentQuantity",
                            "value": str(another_adobe_subscription["currentQuantity"]),
                        },
                        {
                            "externalId": "renewalQuantity",
                            "value": str(
                                another_adobe_subscription["autoRenewal"]["renewalQuantity"]
                            ),
                        },
                        {
                            "externalId": "renewalDate",
                            "value": another_adobe_subscription["renewalDate"],
                        },
                    ]
                },
                commitmentDate="2025-04-04",
                autoRenew=another_adobe_subscription["autoRenewal"]["enabled"],
            ),
            mocker.call(
                mocked_mpt_client,
                deployment_subscription["id"],
                lines=[{"id": "ALI-2119-4550-8674-5962-0001", "price": {"unitPP": 20.22}}],
                parameters={
                    "fulfillment": [
                        {
                            "externalId": "adobeSKU",
                            "value": "77777777CA01A12",
                        },
                        {
                            "externalId": "currentQuantity",
                            "value": str(adobe_deployment_subscription["currentQuantity"]),
                        },
                        {
                            "externalId": "renewalQuantity",
                            "value": str(
                                adobe_deployment_subscription["autoRenewal"]["renewalQuantity"]
                            ),
                        },
                        {
                            "externalId": "renewalDate",
                            "value": adobe_deployment_subscription["renewalDate"],
                        },
                    ]
                },
                commitmentDate="2025-04-04",
                autoRenew=adobe_deployment_subscription["autoRenewal"]["enabled"],
            ),
        ]

    expected_lines = lines_factory(
        external_vendor_id="77777777CA",
        unit_purchase_price=20.22,
    )
    if not dry_run:
        assert mocked_update_agreement.call_args_list == [
            mocker.call(
                mocked_mpt_client,
                agreement["id"],
                lines=expected_lines,
                parameters={"fulfillment": [{"externalId": "nextSync", "value": "2025-04-05"}]},
            ),
            mocker.call(
                mocked_mpt_client,
                agreement["id"],
                parameters={
                    "fulfillment": [
                        {"externalId": "globalCustomer", "value": ["Yes"]},
                        {"externalId": "deployments", "value": "deployment-id - DE"},
                    ]
                },
            ),
            mocker.call(
                mocked_mpt_client,
                deployment_agreements[0]["id"],
                lines=expected_lines,
                parameters={"fulfillment": [{"externalId": "nextSync", "value": "2025-04-05"}]},
            ),
            mocker.call(
                mocked_mpt_client,
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
                mocked_mpt_client,
                deployment_agreements[0]["id"],
                parameters={"fulfillment": [{"externalId": "lastSyncDate", "value": "2025-06-19"}]},
            ),
        ]


def test_sync_global_customer_update_not_required(
    mocker,
    agreement_factory,
    fulfillment_parameters_factory,
    subscriptions_factory,
    lines_factory,
    adobe_subscription_factory,
    adobe_customer_factory,
    mock_get_adobe_product_by_marketplace_sku,
):
    agreement = agreement_factory(
        lines=lines_factory(
            external_vendor_id="77777777CA",
            unit_purchase_price=10.11,
        ),
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
    mpt_subscription = subscriptions_factory()[0]
    another_mpt_subscription = subscriptions_factory(
        adobe_sku="77777777CA01A12",
        adobe_subscription_id="b-sub-id",
        subscription_id="SUB-1000-2000-5000",
    )[0]
    deployment_subscription = subscriptions_factory(
        adobe_subscription_id="d-sub-id",
    )[0]
    another_deployment_subscription = subscriptions_factory(
        adobe_subscription_id="d-sub-id",
    )[0]
    adobe_subscription = adobe_subscription_factory()
    another_adobe_subscription = adobe_subscription_factory(
        subscription_id="b-sub-id",
        offer_id="77777777CA01A12",
        current_quantity=15,
        renewal_quantity=15,
    )
    adobe_deployment_subscription = adobe_subscription_factory()
    another_adobe_deployment_subscription = adobe_subscription_factory()

    authorization_id = agreement["authorization"]["id"]
    customer_id = get_adobe_customer_id(agreement)

    mocked_mpt_client = mocker.MagicMock()

    mocked_adobe_client = mocker.MagicMock()
    mocked_adobe_client.get_subscription.side_effect = [
        adobe_subscription,
        another_adobe_subscription,
        adobe_deployment_subscription,
        another_adobe_deployment_subscription,
    ]

    mocker.patch(
        "adobe_vipm.flows.sync.get_adobe_product_by_marketplace_sku",
        side_effect=mock_get_adobe_product_by_marketplace_sku,
    )

    mocked_adobe_client.get_customer_deployments_active_status.return_value = [
        {
            "deploymentId": "deployment-id",
            "status": "1000",
            "companyProfile": {"address": {"country": "DE"}},
        }
    ]
    mocked_adobe_client.get_customer.return_value = adobe_customer_factory(
        coterm_date="2025-04-04",
        global_sales_enabled=True,
    )

    mocker.patch(
        "adobe_vipm.flows.sync.get_adobe_client",
        return_value=mocked_adobe_client,
    )

    mocked_get_agreement_subscription = mocker.patch(
        "adobe_vipm.flows.sync.get_agreement_subscription",
        side_effect=[
            mpt_subscription,
            another_mpt_subscription,
            deployment_subscription,
            another_deployment_subscription,
        ],
    )

    mocker.patch(
        "adobe_vipm.airtable.models.get_prices_for_skus",
        side_effect=[
            {"65304578CA01A12": 1234.55, "77777777CA01A12": 20.22},
            {"65304578CA01A12": 1234.55, "77777777CA01A12": 20.22},
            {"65304578CA01A12": 1234.55, "77777777CA01A12": 20.22},
            {"65304578CA01A12": 1234.55, "77777777CA01A12": 20.22},
            {"65304578CA01A12": 1234.55, "77777777CA01A12": 20.22},
            {"65304578CA01A12": 1234.55, "77777777CA01A12": 20.22},
        ],
    )

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
    mocker.patch(
        "adobe_vipm.flows.sync.get_agreements_by_customer_deployments",
        return_value=deployment_agreements,
    )

    mocked_update_agreement_subscription = mocker.patch(
        "adobe_vipm.flows.sync.update_agreement_subscription",
    )

    mocked_update_agreement = mocker.patch(
        "adobe_vipm.flows.sync.update_agreement",
    )

    sync_agreement(mocked_mpt_client, agreement, False)

    assert mocked_get_agreement_subscription.call_args_list == [
        mocker.call(
            mocked_mpt_client,
            mpt_subscription["id"],
        ),
        mocker.call(
            mocked_mpt_client,
            another_mpt_subscription["id"],
        ),
        mocker.call(
            mocked_mpt_client,
            deployment_subscription["id"],
        ),
        mocker.call(
            mocked_mpt_client,
            another_deployment_subscription["id"],
        ),
    ]
    assert mocked_adobe_client.get_subscription.call_args_list == [
        mocker.call(
            authorization_id,
            customer_id,
            mpt_subscription["externalIds"]["vendor"],
        ),
        mocker.call(
            authorization_id,
            customer_id,
            another_mpt_subscription["externalIds"]["vendor"],
        ),
        mocker.call(
            authorization_id,
            "",
            deployment_subscription["externalIds"]["vendor"],
        ),
        mocker.call(
            authorization_id,
            "",
            another_deployment_subscription["externalIds"]["vendor"],
        ),
    ]

    assert mocked_update_agreement_subscription.call_args_list == [
        mocker.call(
            mocked_mpt_client,
            mpt_subscription["id"],
            lines=[{"id": "ALI-2119-4550-8674-5962-0001", "price": {"unitPP": 1234.55}}],
            parameters={
                "fulfillment": [
                    {
                        "externalId": "adobeSKU",
                        "value": "65304578CA01A12",
                    },
                    {
                        "externalId": "currentQuantity",
                        "value": str(adobe_subscription["currentQuantity"]),
                    },
                    {
                        "externalId": "renewalQuantity",
                        "value": str(adobe_subscription["autoRenewal"]["renewalQuantity"]),
                    },
                    {
                        "externalId": "renewalDate",
                        "value": adobe_subscription["renewalDate"],
                    },
                ]
            },
            commitmentDate="2025-04-04",
            autoRenew=adobe_subscription["autoRenewal"]["enabled"],
        ),
        mocker.call(
            mocked_mpt_client,
            another_mpt_subscription["id"],
            lines=[{"id": "ALI-2119-4550-8674-5962-0001", "price": {"unitPP": 20.22}}],
            parameters={
                "fulfillment": [
                    {
                        "externalId": "adobeSKU",
                        "value": "77777777CA01A12",
                    },
                    {
                        "externalId": "currentQuantity",
                        "value": str(another_adobe_subscription["currentQuantity"]),
                    },
                    {
                        "externalId": "renewalQuantity",
                        "value": str(another_adobe_subscription["autoRenewal"]["renewalQuantity"]),
                    },
                    {
                        "externalId": "renewalDate",
                        "value": another_adobe_subscription["renewalDate"],
                    },
                ]
            },
            commitmentDate="2025-04-04",
            autoRenew=another_adobe_subscription["autoRenewal"]["enabled"],
        ),
        mocker.call(
            mocked_mpt_client,
            deployment_subscription["id"],
            lines=[{"id": "ALI-2119-4550-8674-5962-0001", "price": {"unitPP": 1234.55}}],
            parameters={
                "fulfillment": [
                    {
                        "externalId": "adobeSKU",
                        "value": "65304578CA01A12",
                    },
                    {
                        "externalId": "currentQuantity",
                        "value": str(adobe_deployment_subscription["currentQuantity"]),
                    },
                    {
                        "externalId": "renewalQuantity",
                        "value": str(
                            adobe_deployment_subscription["autoRenewal"]["renewalQuantity"]
                        ),
                    },
                    {
                        "externalId": "renewalDate",
                        "value": adobe_deployment_subscription["renewalDate"],
                    },
                ]
            },
            commitmentDate="2025-04-04",
            autoRenew=adobe_deployment_subscription["autoRenewal"]["enabled"],
        ),
        mocker.call(
            mocked_mpt_client,
            another_deployment_subscription["id"],
            lines=[{"id": "ALI-2119-4550-8674-5962-0001", "price": {"unitPP": 1234.55}}],
            parameters={
                "fulfillment": [
                    {
                        "externalId": "adobeSKU",
                        "value": "65304578CA01A12",
                    },
                    {
                        "externalId": "currentQuantity",
                        "value": str(another_adobe_deployment_subscription["currentQuantity"]),
                    },
                    {
                        "externalId": "renewalQuantity",
                        "value": str(
                            another_adobe_deployment_subscription["autoRenewal"]["renewalQuantity"]
                        ),
                    },
                    {
                        "externalId": "renewalDate",
                        "value": another_adobe_deployment_subscription["renewalDate"],
                    },
                ]
            },
            commitmentDate="2025-04-04",
            autoRenew=another_adobe_deployment_subscription["autoRenewal"]["enabled"],
        ),
    ]

    expected_lines = lines_factory(
        external_vendor_id="77777777CA",
        unit_purchase_price=20.22,
    )
    assert mocked_update_agreement.mock_calls[0] == mocker.call(
        mocked_mpt_client,
        agreement["id"],
        lines=expected_lines,
        parameters={"fulfillment": [{"externalId": "nextSync", "value": "2025-04-05"}]},
    )
    mocked_adobe_client.get_customer_deployments_active_status.assert_called_once()


def test_sync_global_customer_update_adobe_error(
    mocker,
    agreement_factory,
    subscriptions_factory,
    lines_factory,
    adobe_subscription_factory,
    adobe_customer_factory,
    adobe_api_error_factory,
    mock_get_adobe_product_by_marketplace_sku,
):
    agreement = agreement_factory(
        lines=lines_factory(
            external_vendor_id="77777777CA",
            unit_purchase_price=10.11,
        ),
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

    authorization_id = agreement["authorization"]["id"]
    customer_id = get_adobe_customer_id(agreement)

    mocked_mpt_client = mocker.MagicMock()

    mocked_adobe_client = mocker.MagicMock()
    mocked_adobe_client.get_subscription.side_effect = [
        adobe_subscription,
        another_adobe_subscription,
    ]
    adobe_error = AdobeAPIError(
        400,
        adobe_api_error_factory(
            "9999",
            "some error",
        ),
    )
    mocked_adobe_client.get_customer_deployments_active_status.side_effect = adobe_error
    mocked_adobe_client.get_customer.return_value = adobe_customer_factory(
        coterm_date="2025-04-04",
        global_sales_enabled=True,
    )

    mocker.patch(
        "adobe_vipm.flows.sync.get_adobe_client",
        return_value=mocked_adobe_client,
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
        "adobe_vipm.flows.sync.update_agreement_subscription",
    )

    mocked_update_agreement = mocker.patch(
        "adobe_vipm.flows.sync.update_agreement",
    )

    mocked_notifier = mocker.patch(
        "adobe_vipm.flows.sync.notify_agreement_unhandled_exception_in_teams",
    )

    mocker.patch(
        "adobe_vipm.flows.sync.get_adobe_product_by_marketplace_sku",
        side_effect=mock_get_adobe_product_by_marketplace_sku,
    )

    sync_agreement(mocked_mpt_client, agreement, False)

    assert mocked_get_agreement_subscription.call_args_list == [
        mocker.call(
            mocked_mpt_client,
            mpt_subscription["id"],
        ),
        mocker.call(
            mocked_mpt_client,
            another_mpt_subscription["id"],
        ),
    ]
    assert mocked_adobe_client.get_subscription.call_args_list == [
        mocker.call(
            authorization_id,
            customer_id,
            mpt_subscription["externalIds"]["vendor"],
        ),
        mocker.call(
            authorization_id,
            customer_id,
            another_mpt_subscription["externalIds"]["vendor"],
        ),
    ]

    assert mocked_update_agreement_subscription.call_args_list == [
        mocker.call(
            mocked_mpt_client,
            mpt_subscription["id"],
            lines=[{"id": "ALI-2119-4550-8674-5962-0001", "price": {"unitPP": 1234.55}}],
            parameters={
                "fulfillment": [
                    {
                        "externalId": "adobeSKU",
                        "value": "65304578CA01A12",
                    },
                    {
                        "externalId": "currentQuantity",
                        "value": str(adobe_subscription["currentQuantity"]),
                    },
                    {
                        "externalId": "renewalQuantity",
                        "value": str(adobe_subscription["autoRenewal"]["renewalQuantity"]),
                    },
                    {
                        "externalId": "renewalDate",
                        "value": adobe_subscription["renewalDate"],
                    },
                ]
            },
            commitmentDate="2025-04-04",
            autoRenew=adobe_subscription["autoRenewal"]["enabled"],
        ),
        mocker.call(
            mocked_mpt_client,
            another_mpt_subscription["id"],
            lines=[{"id": "ALI-2119-4550-8674-5962-0001", "price": {"unitPP": 20.22}}],
            parameters={
                "fulfillment": [
                    {
                        "externalId": "adobeSKU",
                        "value": "77777777CA01A12",
                    },
                    {
                        "externalId": "currentQuantity",
                        "value": str(another_adobe_subscription["currentQuantity"]),
                    },
                    {
                        "externalId": "renewalQuantity",
                        "value": str(another_adobe_subscription["autoRenewal"]["renewalQuantity"]),
                    },
                    {
                        "externalId": "renewalDate",
                        "value": another_adobe_subscription["renewalDate"],
                    },
                ]
            },
            commitmentDate="2025-04-04",
            autoRenew=another_adobe_subscription["autoRenewal"]["enabled"],
        ),
    ]

    expected_lines = lines_factory(
        external_vendor_id="77777777CA",
        unit_purchase_price=20.22,
    )
    mocked_update_agreement.assert_called_once_with(
        mocked_mpt_client,
        agreement["id"],
        lines=expected_lines,
        parameters={"fulfillment": [{"externalId": "nextSync", "value": "2025-04-05"}]},
    )
    mocked_adobe_client.get_customer_deployments_active_status.assert_called_once()
    mocked_notifier.assert_called_once()
    assert mocked_notifier.call_args_list[0].args[0] == agreement["id"]


def test_sync_global_customer_parameters_error(
    mocker,
    agreement_factory,
    subscriptions_factory,
    lines_factory,
    adobe_subscription_factory,
    adobe_customer_factory,
    adobe_api_error_factory,
    mock_get_adobe_product_by_marketplace_sku,
    caplog,
):
    agreement = agreement_factory(
        lines=lines_factory(
            external_vendor_id="77777777CA",
            unit_purchase_price=10.11,
        ),
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

    mocked_mpt_client = mocker.MagicMock()

    mocked_adobe_client = mocker.MagicMock()
    mocked_adobe_client.get_subscription.side_effect = [
        adobe_subscription,
        another_adobe_subscription,
    ]
    mocked_adobe_client.get_customer_deployments_active_status.return_value = [
        {
            "deploymentId": "deployment-id",
            "status": "1000",
            "companyProfile": {"address": {"country": "UK"}},
        }
    ]
    mocked_adobe_client.get_customer.return_value = adobe_customer_factory(
        coterm_date="2025-04-04",
        global_sales_enabled=True,
    )

    mocker.patch(
        "adobe_vipm.flows.sync.get_adobe_client",
        return_value=mocked_adobe_client,
    )

    mocker.patch(
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

    mocker.patch(
        "adobe_vipm.flows.sync.update_agreement_subscription",
    )

    mocker.patch(
        "adobe_vipm.flows.sync.update_agreement",
        side_effect=[mocker.MagicMock(), AdobeAPIError(400, {"error": "some error"})],
    )

    mocker.patch(
        "adobe_vipm.flows.sync.notify_agreement_unhandled_exception_in_teams",
    )

    mocker.patch(
        "adobe_vipm.flows.sync.get_adobe_product_by_marketplace_sku",
        side_effect=mock_get_adobe_product_by_marketplace_sku,
    )

    with caplog.at_level(logging.ERROR):
        sync_agreement(mocked_mpt_client, agreement, False)

    assert caplog.records[0].message == (
        "Error setting global customer parameters for agreement "
        "AGR-2119-4550-8674-5962: some error - {'error': 'some error'}"
    )


def test_sync_agreement_error_getting_adobe_customer(
    mocker,
    agreement_factory,
    subscriptions_factory,
    lines_factory,
    adobe_subscription_factory,
    adobe_customer_factory,
    adobe_api_error_factory,
):
    agreement = agreement_factory(
        lines=lines_factory(
            external_vendor_id="77777777CA",
            unit_purchase_price=10.11,
        ),
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
    mocked_mpt_client = mocker.MagicMock()

    mocked_adobe_client = mocker.MagicMock()

    adobe_error = AdobeAPIError(
        400,
        adobe_api_error_factory(
            "9999",
            "some error",
        ),
    )
    mocked_adobe_client.get_customer.side_effect = adobe_error

    mocker.patch(
        "adobe_vipm.flows.sync.get_adobe_client",
        return_value=mocked_adobe_client,
    )
    mocked_notifier = mocker.patch(
        "adobe_vipm.flows.sync.notify_agreement_unhandled_exception_in_teams",
    )
    sync_agreement(mocked_mpt_client, agreement, False)
    mocked_adobe_client.get_customer.assert_called_once()
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
    sync_agreement(mpt_client, agreement, False)
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
    """
    Test that sync_agreement notifies when customer discounts are empty.
    """
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

    sync_agreement(mocked_mpt_client, agreement, False)

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
    caplog,
):
    """
    Test that sync_agreement_prices handles missing prices correctly by:
    - Continuing with other SKUs that have prices
    - Generating appropriate notifications for missing prices
    - Logging the error
    """
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

    mocked_mpt_client = mocker.MagicMock()

    mocked_adobe_client = mocker.MagicMock()
    mocked_adobe_client.get_subscription.side_effect = [
        adobe_subscription,
        another_adobe_subscription,
        terminated_adobe_subscription,
    ]
    mocked_adobe_client.get_customer.return_value = adobe_customer_factory(coterm_date="2025-04-04")

    mocker.patch(
        "adobe_vipm.flows.sync.get_adobe_client",
        return_value=mocked_adobe_client,
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

    mocker.patch(
        "adobe_vipm.flows.sync.get_adobe_product_by_marketplace_sku",
        side_effect=mock_get_adobe_product_by_marketplace_sku,
    )

    with caplog.at_level(logging.ERROR):
        sync_agreement(mocked_mpt_client, agreement, False)

    assert "Skipping subscription" in caplog.text
    assert "65304578CA01A12" in caplog.text

    mocked_notify_missing_prices.assert_called_once()
    call_args = mocked_notify_missing_prices.call_args[0]
    assert call_args[0] == agreement["id"]
    assert "65304578CA01A12" in call_args[1]
    assert call_args[2] == agreement["product"]["id"]
    assert call_args[3] == agreement["listing"]["priceList"]["currency"]

    assert len(mocked_update_agreement_subscription.call_args_list) == 1
    update_call = mocked_update_agreement_subscription.call_args_list[0]
    assert update_call[1]["lines"][0]["price"]["unitPP"] == 20.22

    mocked_update_agreement.call_args_list = [
        mocker.call(
            mocked_mpt_client,
            agreement["id"],
            lines=agreement["lines"],
            parameters={"fulfillment": [{"externalId": "nextSync", "value": "2025-04-05"}]},
        ),
        mocker.call(
            mocked_mpt_client,
            agreement["id"],
            parameters={"fulfillment": [{"externalId": "lastSyncDate", "value": "2025-06-19"}]},
        ),
    ]

    assert len(mocked_adobe_client.get_subscription.call_args_list) == 3

    assert "77777777CA01A13" not in [
        call[1]["lines"][0]["price"]["unitPP"]
        for call in mocked_update_agreement_subscription.call_args_list
    ]
