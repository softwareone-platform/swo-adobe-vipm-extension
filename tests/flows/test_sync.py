import logging

import pytest
from freezegun import freeze_time

from adobe_vipm.adobe.errors import AdobeAPIError
from adobe_vipm.flows.sync import (
    sync_agreement,
    sync_agreements_by_agreement_ids,
    sync_agreements_by_next_sync,
    sync_all_agreements,
)
from adobe_vipm.flows.utils import get_adobe_customer_id

pytestmark = pytest.mark.usefixtures("mock_adobe_config")


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
    mocked_adobe_client.get_customer.return_value = adobe_customer_factory(
        coterm_date="2025-04-04"
    )

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
        "adobe_vipm.flows.sync.get_prices_for_skus",
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
            lines=[
                {"id": "ALI-2119-4550-8674-5962-0001", "price": {"unitPP": 1234.55}}
            ],
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
                        "value": str(
                            adobe_subscription["autoRenewal"]["renewalQuantity"]
                        ),
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
    mocked_adobe_client.get_customer.return_value = adobe_customer_factory(
        coterm_date="2025-04-04"
    )

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
        "adobe_vipm.flows.sync.get_prices_for_skus",
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
        side_effect=mpt_subscription,
    )

    mocked_update_agreement_subscription = mocker.patch(
        "adobe_vipm.flows.sync.update_agreement_subscription",
    )

    mocked_update_agreement = mocker.patch(
        "adobe_vipm.flows.sync.update_agreement",
    )

    with caplog.at_level(logging.ERROR):
        sync_agreement(mocked_mpt_client, agreement, False)

    assert f"Cannot sync agreement {agreement['id']}" in caplog.text

    mocked_get_agreement_subscription.assert_called_once_with(
        mocked_mpt_client,
        mpt_subscription["id"],
    )

    mocked_update_agreement_subscription.assert_not_called()
    mocked_update_agreement.assert_not_called()


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

    assert (
        f"Agreement {agreement['id']} has processing subscriptions, skip it"
        in caplog.text
    )

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
        "adobe_vipm.flows.sync.get_prices_for_3yc_skus",
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

    mocked_update_agreement.assert_called_once_with(
        mocked_mpt_client,
        agreement["id"],
        lines=expected_lines,
        parameters={"fulfillment": [{"externalId": "nextSync", "value": "2025-04-05"}]},
    )


def test_sync_global_customer_parameter(
    mocker,
    agreement_factory,
    subscriptions_factory,
    fulfillment_parameters_factory,
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
    mocked_adobe_client.get_customer_deployments.return_value = {
        "totalCount": 1,
        "items": [
            {
                "deploymentId": "deployment-id",
                "status": "1000",
                "companyProfile": {"address": {"country": "DE"}},
            }
        ],
    }
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
        "adobe_vipm.flows.sync.get_prices_for_skus",
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

    assert mocked_update_agreement_subscription.call_args_list == [
        mocker.call(
            mocked_mpt_client,
            mpt_subscription["id"],
            lines=[
                {"id": "ALI-2119-4550-8674-5962-0001", "price": {"unitPP": 1234.55}}
            ],
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
                        "value": str(
                            adobe_subscription["autoRenewal"]["renewalQuantity"]
                        ),
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
                            adobe_deployment_subscription["autoRenewal"][
                                "renewalQuantity"
                            ]
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
    assert mocked_update_agreement.mock_calls == [
        mocker.call(
            mocked_mpt_client,
            agreement["id"],
            lines=expected_lines,
            parameters={
                "fulfillment": [{"externalId": "nextSync", "value": "2025-04-05"}]
            },
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
            parameters={
                "fulfillment": [{"externalId": "nextSync", "value": "2025-04-05"}]
            },
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

    mocked_adobe_client.get_customer_deployments.return_value = {
        "totalCount": 1,
        "items": [
            {
                "deploymentId": "deployment-id",
                "status": "1000",
                "companyProfile": {"address": {"country": "DE"}},
            }
        ],
    }
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
        "adobe_vipm.flows.sync.get_prices_for_skus",
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
            lines=[
                {"id": "ALI-2119-4550-8674-5962-0001", "price": {"unitPP": 1234.55}}
            ],
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
                        "value": str(
                            adobe_subscription["autoRenewal"]["renewalQuantity"]
                        ),
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
            lines=[
                {"id": "ALI-2119-4550-8674-5962-0001", "price": {"unitPP": 1234.55}}
            ],
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
                            adobe_deployment_subscription["autoRenewal"][
                                "renewalQuantity"
                            ]
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
            lines=[
                {"id": "ALI-2119-4550-8674-5962-0001", "price": {"unitPP": 1234.55}}
            ],
            parameters={
                "fulfillment": [
                    {
                        "externalId": "adobeSKU",
                        "value": "65304578CA01A12",
                    },
                    {
                        "externalId": "currentQuantity",
                        "value": str(
                            another_adobe_deployment_subscription["currentQuantity"]
                        ),
                    },
                    {
                        "externalId": "renewalQuantity",
                        "value": str(
                            another_adobe_deployment_subscription["autoRenewal"][
                                "renewalQuantity"
                            ]
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
    mocked_adobe_client.get_customer_deployments.assert_called_once()


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
    mocked_adobe_client.get_customer_deployments.side_effect = adobe_error
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
        "adobe_vipm.flows.sync.get_prices_for_skus",
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
            lines=[
                {"id": "ALI-2119-4550-8674-5962-0001", "price": {"unitPP": 1234.55}}
            ],
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
                        "value": str(
                            adobe_subscription["autoRenewal"]["renewalQuantity"]
                        ),
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
    mocked_adobe_client.get_customer_deployments.assert_called_once()


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
    sync_agreement(mocked_mpt_client, agreement, False)
    mocked_adobe_client.get_customer.assert_called_once()
