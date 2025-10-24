import pytest
from django.core.management import call_command

from adobe_vipm.adobe.errors import AdobeAPIError
from adobe_vipm.flows.constants import SubscriptionStatus
from adobe_vipm.flows.errors import MPTAPIError
from adobe_vipm.management.commands.migrate_assets_to_non_renewal_subs import Command

COMMAND_PATH = "adobe_vipm.management.commands.migrate_assets_to_non_renewal_subs"


@pytest.fixture
def mock_adobe_customer(adobe_customer_factory):
    return adobe_customer_factory()


@pytest.fixture
def mock_adobe_subscriptions(adobe_subscription_factory):
    return {
        "totalCount": 2,
        "items": [
            adobe_subscription_factory(
                subscription_id="22414976d94999ab2c976bdd52b779NA",
                offer_id="65327701CA01A12",
                current_quantity=222,
                used_quantity=23,
                deployment_id=None,
            ),
            adobe_subscription_factory(deployment_id="PR1400001947"),
        ],
    }


def test_add_arguments(mocker):
    parser = mocker.Mock()

    Command().add_arguments(parser)

    assert parser.add_argument.call_count == 2
    parser.add_argument.assert_any_call(
        "--agreements", nargs="*", default=[], help="List of specific agreements to update."
    )
    parser.add_argument.assert_any_call(
        "--dry-run", action="store_true", default=False, help="Run command without making changes."
    )


def test_handle(
    mocker,
    mock_adobe_client,
    mock_mpt_client,
    mock_adobe_customer,
    mock_adobe_subscriptions,
    agreement,
    capsys,
    items_factory,
):
    mock_get_agreements_by_query = mocker.patch(
        f"{COMMAND_PATH}.get_agreements_by_query", return_value=[agreement]
    )
    mock_adobe_client.get_customer.return_value = mock_adobe_customer
    mock_adobe_client.get_subscriptions_by_deployment.return_value = mock_adobe_subscriptions
    mocker.patch(f"{COMMAND_PATH}.SKUS_TO_PROCESS", ("65327701CA",))
    product_items = items_factory()
    mock_get_product_items_by_skus = mocker.patch(
        f"{COMMAND_PATH}.get_product_items_by_skus", return_value=product_items
    )
    mock_get_sku_price = mocker.patch(
        f"{COMMAND_PATH}.get_sku_price", return_value={"65327701CA01A12": 1.23}
    )
    mock_get_sku_with_discount_level = mocker.patch(
        f"{COMMAND_PATH}.get_sku_with_discount_level", return_value="65327701CA01A12"
    )
    mock_create_agreement_sub = mocker.patch(
        f"{COMMAND_PATH}.create_agreement_subscription",
        return_value={"id": "new-mpt-subscription-id"},
    )
    mock_terminate_asset = mocker.patch(f"{COMMAND_PATH}.terminate_asset")

    call_command("migrate_assets_to_non_renewal_subs", agreements=[agreement["id"]])

    mock_get_agreements_by_query.assert_called_once_with(mock_mpt_client, mocker.ANY)
    mock_adobe_client.get_customer.assert_called_once_with("AUT-4785-7184", "a-client-id")
    mock_adobe_client.get_subscriptions_by_deployment.assert_called_once_with(
        "AUT-4785-7184", "a-client-id", ""
    )
    mock_get_product_items_by_skus.assert_called_once_with(
        mock_mpt_client, "PRD-1111-1111", ["65327701CA"]
    )
    mock_get_sku_price.assert_called_once_with(
        mock_adobe_customer, ["65327701CA01A12"], "PRD-1111-1111", "USD"
    )
    mock_get_sku_with_discount_level.assert_called_once_with("65327701CA01A12", mock_adobe_customer)
    mock_create_agreement_sub.assert_called_once_with(
        mock_mpt_client,
        {
            "status": SubscriptionStatus.ACTIVE,
            "commitmentDate": "2026-10-11",
            "parameters": {
                "fulfillment": [
                    {"externalId": "adobeSKU", "value": "65327701CA01A12"},
                    {"externalId": "currentQuantity", "value": "222"},
                    {"externalId": "renewalQuantity", "value": "10"},
                    {"externalId": "renewalDate", "value": "2026-10-11"},
                ]
            },
            "agreement": {"id": "AGR-2119-4550-8674-5962"},
            "buyer": {"id": "BUY-3731-7971"},
            "licensee": {"id": "LCE-1111-2222-3333"},
            "seller": {"id": "SEL-9121-8944"},
            "lines": [
                {
                    "quantity": "222",
                    "item": {
                        "id": "ITM-1234-1234-1234-0001",
                        "name": "Awesome product",
                        "externalIds": {"vendor": "65304578CA"},
                        "terms": {"period": "1y", "model": "quantity"},
                        "status": "Published",
                    },
                    "price": {"unitPP": 1.23},
                }
            ],
            "name": "Subscription for Awesome product",
            "startDate": "2019-05-20T22:49:55Z",
            "externalIds": {"vendor": "22414976d94999ab2c976bdd52b779NA"},
            "product": {"id": "PRD-1111-1111"},
            "autoRenew": False,
        },
    )
    mock_terminate_asset.assert_called_once_with("AST-0535-8763-6274")
    out_log = capsys.readouterr().out
    assert "Subscription new-mpt-subscription-id has been created with:" in out_log
    assert "Agreement AGR-2119-4550-8674-5962 has been updated." in out_log


def test_handle_dry_run(
    mocker,
    mock_adobe_client,
    mock_adobe_customer,
    mock_adobe_subscriptions,
    agreement,
    capsys,
    items_factory,
):
    mocker.patch(f"{COMMAND_PATH}.get_agreements_by_query", return_value=[agreement])
    mock_adobe_client.get_customer.return_value = mock_adobe_customer
    mock_adobe_client.get_subscriptions_by_deployment.return_value = mock_adobe_subscriptions
    mocker.patch(f"{COMMAND_PATH}.SKUS_TO_PROCESS", ("65327701CA",))
    mocker.patch(f"{COMMAND_PATH}.get_product_items_by_skus", return_value=items_factory())
    mocker.patch(f"{COMMAND_PATH}.get_sku_price", return_value={"65327701CA01A12": 1.23})
    mocker.patch(f"{COMMAND_PATH}.get_sku_with_discount_level", return_value="65327701CA01A12")
    mock_create_agreement_sub = mocker.patch(f"{COMMAND_PATH}.create_agreement_subscription")
    mock_terminate_asset = mocker.patch(f"{COMMAND_PATH}.terminate_asset")

    call_command("migrate_assets_to_non_renewal_subs", dry_run=True)

    mock_create_agreement_sub.assert_not_called()
    mock_terminate_asset.assert_not_called()
    out_log = capsys.readouterr().out
    assert "Dry run mode - Create/Update subscription with:" in out_log
    assert "Dry run mode - asset AST-0535-8763-6274 has been set as terminated" in out_log


def test_handle_no_agreements(mocker, capsys):
    mock_get_agreements_by_query = mocker.patch(
        f"{COMMAND_PATH}.get_agreements_by_query", return_value=[]
    )
    mock_create_agreement_sub = mocker.patch(f"{COMMAND_PATH}.create_agreement_subscription")
    mock_terminate_asset = mocker.patch(f"{COMMAND_PATH}.terminate_asset")

    call_command("migrate_assets_to_non_renewal_subs")

    mock_get_agreements_by_query.assert_called_once()
    mock_create_agreement_sub.assert_not_called()
    mock_terminate_asset.assert_not_called()
    out_log = capsys.readouterr().out
    assert "Starting to process assets for agreement" not in out_log


def test_handle_adobe_customer_error(
    mocker, mock_adobe_client, mock_adobe_subscriptions, agreement, capsys
):
    mock_get_agreements_by_query = mocker.patch(
        f"{COMMAND_PATH}.get_agreements_by_query", return_value=[agreement]
    )
    mock_adobe_client.get_customer.side_effect = AdobeAPIError(404, {"message": "not found"})
    mock_adobe_client.get_subscriptions_by_deployment.return_value = mock_adobe_subscriptions
    mocker.patch(f"{COMMAND_PATH}.SKUS_TO_PROCESS", ("65327701CA",))
    mock_create_agreement_sub = mocker.patch(f"{COMMAND_PATH}.create_agreement_subscription")
    mock_terminate_asset = mocker.patch(f"{COMMAND_PATH}.terminate_asset")

    call_command("migrate_assets_to_non_renewal_subs")

    mock_get_agreements_by_query.assert_called_once()
    mock_adobe_client.get_customer.assert_called_once()
    mock_create_agreement_sub.assert_not_called()
    mock_terminate_asset.assert_not_called()
    out_log = capsys.readouterr().err
    assert "Error getting customer with ID a-client-id:" in out_log


def test_handle_adobe_subscription_error(
    mocker,
    mock_adobe_client,
    mock_mpt_client,
    mock_adobe_customer,
    mock_adobe_subscriptions,
    agreement,
    capsys,
    items_factory,
):
    mock_get_agreements_by_query = mocker.patch(
        f"{COMMAND_PATH}.get_agreements_by_query", return_value=[agreement]
    )
    mock_adobe_client.get_customer.return_value = mock_adobe_customer
    mock_adobe_client.get_subscriptions_by_deployment.side_effect = AdobeAPIError(
        500, {"message": "error"}
    )
    mock_create_agreement_sub = mocker.patch(f"{COMMAND_PATH}.create_agreement_subscription")
    mock_terminate_asset = mocker.patch(f"{COMMAND_PATH}.terminate_asset")

    call_command("migrate_assets_to_non_renewal_subs")

    mock_get_agreements_by_query.assert_called_once()
    mock_adobe_client.get_customer.assert_called_once()
    mock_create_agreement_sub.assert_not_called()
    mock_terminate_asset.assert_not_called()
    out_log = capsys.readouterr().err
    assert "Error getting Adobe subscriptions for agreement AGR-2119-4550-8674-5962:" in out_log


def test_handle_asset_sub_not_found_in_adobe(
    mocker, mock_adobe_client, mock_adobe_customer, mock_adobe_subscriptions, agreement, capsys
):
    mocker.patch(f"{COMMAND_PATH}.get_agreements_by_query", return_value=[agreement])
    mock_adobe_client.get_customer.return_value = mock_adobe_customer
    mock_adobe_subscriptions["items"][0]["subscriptionId"] = "fake-sub-id"
    mock_adobe_client.get_subscriptions_by_deployment.return_value = mock_adobe_subscriptions
    mocker.patch(f"{COMMAND_PATH}.SKUS_TO_PROCESS", ("65327701CA",))
    mock_create_agreement_sub = mocker.patch(f"{COMMAND_PATH}.create_agreement_subscription")
    mock_terminate_asset = mocker.patch(f"{COMMAND_PATH}.terminate_asset")

    call_command("migrate_assets_to_non_renewal_subs")

    mock_create_agreement_sub.assert_not_called()
    mock_terminate_asset.assert_not_called()
    out_log = capsys.readouterr().err
    assert "No subscription found for asset AST-0535-8763-6274" in out_log


def test_handle_subscription_processed(
    mocker,
    mock_adobe_client,
    mock_adobe_customer,
    mock_adobe_subscriptions,
    agreement,
    assets_factory,
    capsys,
    items_factory,
):
    asset = assets_factory(
        asset_id="fake-duplicated-sub-id", adobe_subscription_id="22414976d94999ab2c976bdd52b779NA"
    )[0]
    agreement["assets"].append(asset)
    mocker.patch(f"{COMMAND_PATH}.get_agreements_by_query", return_value=[agreement])
    mock_adobe_client.get_customer.return_value = mock_adobe_customer
    mock_adobe_client.get_subscriptions_by_deployment.return_value = mock_adobe_subscriptions
    mocker.patch(f"{COMMAND_PATH}.SKUS_TO_PROCESS", ("65327701CA",))
    mocker.patch(f"{COMMAND_PATH}.get_product_items_by_skus", return_value=items_factory())
    mocker.patch(f"{COMMAND_PATH}.get_sku_price", return_value={"65327701CA01A12": 1.23})
    mocker.patch(f"{COMMAND_PATH}.get_sku_with_discount_level", return_value="65327701CA01A12")
    mock_create_agreement_sub = mocker.patch(f"{COMMAND_PATH}.create_agreement_subscription")
    mock_terminate_asset = mocker.patch(f"{COMMAND_PATH}.terminate_asset")

    call_command("migrate_assets_to_non_renewal_subs")

    mock_create_agreement_sub.assert_called_once()
    mock_terminate_asset.assert_has_calls([
        mocker.call("AST-0535-8763-6274"),
        mocker.call("fake-duplicated-sub-id"),
    ])
    out_log = capsys.readouterr().out
    assert "Duplicate subscription for asset fake-duplicated-sub-id" in out_log


def test_handle_create_subscription_error(
    mocker,
    mock_adobe_client,
    mock_adobe_customer,
    mock_adobe_subscriptions,
    agreement,
    capsys,
    items_factory,
):
    mocker.patch(f"{COMMAND_PATH}.get_agreements_by_query", return_value=[agreement])
    mock_adobe_client.get_customer.return_value = mock_adobe_customer
    mock_adobe_client.get_subscriptions_by_deployment.return_value = mock_adobe_subscriptions
    mocker.patch(f"{COMMAND_PATH}.SKUS_TO_PROCESS", ("65327701CA",))
    mocker.patch(f"{COMMAND_PATH}.get_product_items_by_skus", return_value=items_factory())
    mocker.patch(f"{COMMAND_PATH}.get_sku_price", return_value={"65327701CA01A12": 1.23})
    mocker.patch(f"{COMMAND_PATH}.get_sku_with_discount_level", return_value="65327701CA01A12")
    mock_create_agreement_sub = mocker.patch(
        f"{COMMAND_PATH}.create_agreement_subscription",
        side_effect=MPTAPIError(400, {"message": "bad request"}),
    )
    mock_terminate_asset = mocker.patch(f"{COMMAND_PATH}.terminate_asset")

    call_command("migrate_assets_to_non_renewal_subs")

    mock_create_agreement_sub.assert_called_once()
    mock_terminate_asset.assert_not_called()
    out_log = capsys.readouterr().err
    assert "Error creating subscription 22414976d94999ab2c976bdd52b779NA" in out_log


def test_handle_update_subscription(
    mocker,
    mock_adobe_client,
    mock_mpt_client,
    mock_adobe_customer,
    mock_adobe_subscriptions,
    agreement,
    capsys,
    items_factory,
):
    agreement["subscriptions"][0]["externalIds"]["vendor"] = "22414976d94999ab2c976bdd52b779NA"
    mocker.patch(f"{COMMAND_PATH}.get_agreements_by_query", return_value=[agreement])
    mock_adobe_client.get_customer.return_value = mock_adobe_customer
    mock_adobe_client.get_subscriptions_by_deployment.return_value = mock_adobe_subscriptions
    mocker.patch(f"{COMMAND_PATH}.SKUS_TO_PROCESS", ("65327701CA",))
    product_items = items_factory()
    mocker.patch(f"{COMMAND_PATH}.get_product_items_by_skus", return_value=product_items)
    mocker.patch(f"{COMMAND_PATH}.get_sku_price", return_value={"65327701CA01A12": 1.23})
    mocker.patch(f"{COMMAND_PATH}.get_sku_with_discount_level", return_value="65327701CA01A12")
    mock_create_agreement_sub = mocker.patch(f"{COMMAND_PATH}.create_agreement_subscription")
    mock_update_agreement_sub = mocker.patch(f"{COMMAND_PATH}.update_agreement_subscription")
    mock_terminate_asset = mocker.patch(f"{COMMAND_PATH}.terminate_asset")

    call_command("migrate_assets_to_non_renewal_subs")

    mock_create_agreement_sub.assert_not_called()
    mock_update_agreement_sub.assert_called_once_with(
        mock_mpt_client,
        "SUB-1000-2000-3000",
        parameters={
            "fulfillment": [
                {"externalId": "adobeSKU", "value": "65327701CA01A12"},
                {"externalId": "currentQuantity", "value": "222"},
                {"externalId": "renewalQuantity", "value": "10"},
                {"externalId": "renewalDate", "value": "2026-10-11"},
            ]
        },
        lines=[
            {
                "quantity": "222",
                "item": {
                    "id": "ITM-1234-1234-1234-0001",
                    "name": "Awesome product",
                    "externalIds": {"vendor": "65304578CA"},
                    "terms": {"period": "1y", "model": "quantity"},
                    "status": "Published",
                },
                "price": {"unitPP": 1.23},
            }
        ],
    )
    mock_terminate_asset.assert_called_once_with("AST-0535-8763-6274")
    out_log = capsys.readouterr().out
    assert "Subscription SUB-1000-2000-3000 has been updated with:" in out_log
    assert "Agreement AGR-2119-4550-8674-5962 has been updated." in out_log


def test_handle_update_subscription_error(
    mocker,
    mock_adobe_client,
    mock_mpt_client,
    mock_adobe_customer,
    mock_adobe_subscriptions,
    agreement,
    capsys,
    items_factory,
):
    agreement["subscriptions"][0]["externalIds"]["vendor"] = "22414976d94999ab2c976bdd52b779NA"
    mocker.patch(f"{COMMAND_PATH}.get_agreements_by_query", return_value=[agreement])
    mock_adobe_client.get_customer.return_value = mock_adobe_customer
    mock_adobe_client.get_subscriptions_by_deployment.return_value = mock_adobe_subscriptions
    mocker.patch(f"{COMMAND_PATH}.SKUS_TO_PROCESS", ("65327701CA",))
    product_items = items_factory()
    mocker.patch(f"{COMMAND_PATH}.get_product_items_by_skus", return_value=product_items)
    mocker.patch(f"{COMMAND_PATH}.get_sku_price", return_value={"65327701CA01A12": 1.23})
    mocker.patch(f"{COMMAND_PATH}.get_sku_with_discount_level", return_value="65327701CA01A12")
    mock_create_agreement_sub = mocker.patch(f"{COMMAND_PATH}.create_agreement_subscription")
    mock_update_agreement_sub = mocker.patch(
        f"{COMMAND_PATH}.update_agreement_subscription",
        side_effect=MPTAPIError(400, {"message": "bad request"}),
    )
    mock_terminate_asset = mocker.patch(f"{COMMAND_PATH}.terminate_asset")

    call_command("migrate_assets_to_non_renewal_subs")

    mock_create_agreement_sub.assert_not_called()
    mock_update_agreement_sub.assert_called_once()
    mock_terminate_asset.assert_not_called()
    out_log = capsys.readouterr().err
    assert "Error updating subscription SUB-1000-2000-3000" in out_log


def test_handle_terminate_error(
    mocker,
    mock_adobe_client,
    mock_adobe_customer,
    mock_adobe_subscriptions,
    agreement,
    capsys,
    items_factory,
):
    mocker.patch(f"{COMMAND_PATH}.get_agreements_by_query", return_value=[agreement])
    mock_adobe_client.get_customer.return_value = mock_adobe_customer
    mock_adobe_client.get_subscriptions_by_deployment.return_value = mock_adobe_subscriptions
    mocker.patch(f"{COMMAND_PATH}.SKUS_TO_PROCESS", ("65327701CA",))
    mocker.patch(f"{COMMAND_PATH}.get_product_items_by_skus", return_value=items_factory())
    mocker.patch(f"{COMMAND_PATH}.get_sku_price", return_value={"65327701CA01A12": 1.23})
    mocker.patch(f"{COMMAND_PATH}.get_sku_with_discount_level", return_value="65327701CA01A12")
    mocker.patch(f"{COMMAND_PATH}.create_agreement_subscription")
    mock_terminate_asset = mocker.patch(
        f"{COMMAND_PATH}.terminate_asset", side_effect=MPTAPIError(400, {"message": "bad request"})
    )

    call_command("migrate_assets_to_non_renewal_subs")

    mock_terminate_asset.assert_called_once()
    out_log = capsys.readouterr().err
    assert "Failed to terminate asset AST-0535-8763-6274" in out_log
