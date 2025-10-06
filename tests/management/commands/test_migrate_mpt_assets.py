from unittest.mock import Mock

import pytest
from django.core.management import call_command

from adobe_vipm.adobe.errors import AdobeAPIError
from adobe_vipm.flows.constants import Param
from adobe_vipm.flows.errors import MPTAPIError
from adobe_vipm.management.commands.migrate_mpt_assets import Command


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


@pytest.fixture
def mock_agreement_missing_asset_external_id(agreement):
    agreement["assets"][0]["externalIds"] = {}
    return agreement


def test_add_arguments():
    parser = Mock()

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
    mock_setup_client,
    mock_agreement_missing_asset_external_id,
    mock_adobe_subscriptions,
    capsys,
):
    mock_get_agreements_by_query = mocker.patch(
        "adobe_vipm.management.commands.migrate_mpt_assets.get_agreements_by_query",
        return_value=[mock_agreement_missing_asset_external_id],
    )
    mock_adobe_client.get_subscriptions_by_deployment.return_value = mock_adobe_subscriptions
    mock_update_asset = mocker.patch(
        "adobe_vipm.management.commands.migrate_mpt_assets.update_asset"
    )

    call_command("migrate_mpt_assets", agreements=[mock_agreement_missing_asset_external_id["id"]])

    mock_get_agreements_by_query.assert_called_once()
    mock_adobe_client.get_subscriptions_by_deployment.assert_called_once()
    asset = mock_agreement_missing_asset_external_id["assets"][0]
    expected_parameters_data = {
        "fulfillment": [
            {
                "externalId": Param.ADOBE_SKU.value,
                "value": "65327701CA01A12",
            },
            {
                "externalId": Param.CURRENT_QUANTITY.value,
                "value": "222",
            },
            {
                "externalId": Param.USED_QUANTITY.value,
                "value": "23",
            },
        ]
    }
    expected_external_id_data = {"vendor": "22414976d94999ab2c976bdd52b779NA"}
    mock_update_asset.assert_called_once_with(
        mock_setup_client,
        asset["id"],
        parameters=expected_parameters_data,
        externalIds=expected_external_id_data,
    )
    out_log = capsys.readouterr().out
    assert (
        f"Asset AST-0535-8763-6274 updated with: \n"
        f"parameters: {expected_parameters_data} \n"
        f"externalIds: {expected_external_id_data} \n" in out_log
    )


def test_handle_dry_run(
    mocker,
    mock_adobe_client,
    mock_setup_client,
    mock_agreement_missing_asset_external_id,
    mock_adobe_subscriptions,
    capsys,
):
    mock_get_agreements_by_query = mocker.patch(
        "adobe_vipm.management.commands.migrate_mpt_assets.get_agreements_by_query",
        return_value=[mock_agreement_missing_asset_external_id],
    )
    mock_adobe_client.get_subscriptions_by_deployment.return_value = mock_adobe_subscriptions
    mock_update_asset = mocker.patch(
        "adobe_vipm.management.commands.migrate_mpt_assets.update_asset"
    )

    call_command(
        "migrate_mpt_assets",
        agreements=[mock_agreement_missing_asset_external_id["id"]],
        dry_run=True,
    )
    mock_get_agreements_by_query.assert_called_once()

    mock_get_agreements_by_query.assert_called_once()
    mock_adobe_client.get_subscriptions_by_deployment.assert_called_once()
    mock_update_asset.assert_not_called()
    expected_parameters = {
        "fulfillment": [
            {
                "externalId": Param.ADOBE_SKU.value,
                "value": "65327701CA01A12",
            },
            {
                "externalId": Param.CURRENT_QUANTITY.value,
                "value": "222",
            },
            {
                "externalId": Param.USED_QUANTITY.value,
                "value": "23",
            },
        ]
    }
    expected_external_id = {"vendor": "22414976d94999ab2c976bdd52b779NA"}
    out_log = capsys.readouterr().out
    assert (
        f"Dry run mode - Asset AST-0535-8763-6274 updated with: \n"
        f"parameters: {expected_parameters} \n"
        f"externalIds: {expected_external_id} \n"
    ) in out_log


def test_handle_no_agreements(mocker, mock_adobe_client, mock_setup_client):
    mock_get_agreements_by_query = mocker.patch(
        "adobe_vipm.management.commands.migrate_mpt_assets.get_agreements_by_query", return_value=[]
    )

    call_command("migrate_mpt_assets")

    expected_select_rql = (
        "select=-*,id,externalIds,authorization.id,assets,assets.parameters,parameters"
        "&in(product.id,(['PRD-1111-1111']))&eq(status,Active)"
    )
    mock_get_agreements_by_query.assert_called_once_with(
        mock_setup_client, expected_select_rql, limit=100
    )
    mock_adobe_client.assert_not_called()


def test_handle_no_assets(
    mocker, mock_adobe_client, mock_setup_client, agreement, mock_adobe_subscriptions
):
    mock_get_agreements_by_query = mocker.patch(
        "adobe_vipm.management.commands.migrate_mpt_assets.get_agreements_by_query",
        return_value=[agreement],
    )
    mock_update_asset = mocker.patch(
        "adobe_vipm.management.commands.migrate_mpt_assets.update_asset"
    )

    call_command("migrate_mpt_assets", agreements=[agreement["id"]])

    mock_get_agreements_by_query.assert_called_once()
    mock_adobe_client.get_subscriptions_by_deployment.assert_called_once_with(
        "AUT-4785-7184", customer_id="P1005259806", deployment_id=""
    )
    mock_update_asset.assert_not_called()


def test_handle_no_adobe_subscriptions(
    mocker, mock_adobe_client, mock_agreement_missing_asset_external_id, capsys
):
    mock_get_agreement_by_query = mocker.patch(
        "adobe_vipm.management.commands.migrate_mpt_assets.get_agreements_by_query",
        return_value=[mock_agreement_missing_asset_external_id],
    )
    mock_adobe_client.get_subscriptions_by_deployment.return_value = {"items": []}
    mock_get_parameter = mocker.patch(
        "adobe_vipm.management.commands.migrate_mpt_assets.get_parameter",
        return_value={"value": "fake_value"},
    )
    mock_update_asset = mocker.patch(
        "adobe_vipm.management.commands.migrate_mpt_assets.update_asset"
    )

    call_command("migrate_mpt_assets", agreements=[mock_agreement_missing_asset_external_id["id"]])

    mock_get_agreement_by_query.assert_called_once()
    mock_adobe_client.get_subscriptions_by_deployment.assert_called_once()
    asset = mock_agreement_missing_asset_external_id["assets"][0]
    mock_get_parameter.assert_has_calls([
        mocker.call(Param.PHASE_FULFILLMENT, asset, Param.ADOBE_SKU),
        mocker.call(Param.PHASE_FULFILLMENT, asset, Param.CURRENT_QUANTITY),
    ])
    mock_update_asset.assert_not_called()
    err_log = capsys.readouterr().err
    assert "Error updating asset AST-0535-8763-6274: subscription not found in Adobe" in err_log


def test_handle_get_adobe_subscriptions_api_error(
    mocker,
    mock_adobe_client,
    mock_setup_client,
    mock_agreement_missing_asset_external_id,
    adobe_api_error_factory,
    capsys,
):
    mocker.patch(
        "adobe_vipm.management.commands.migrate_mpt_assets.get_agreements_by_query",
        return_value=[mock_agreement_missing_asset_external_id],
    )
    mock_adobe_client.get_subscriptions_by_deployment.side_effect = AdobeAPIError(
        400, adobe_api_error_factory("1234", "api error")
    )
    mock_update_asset = mocker.patch(
        "adobe_vipm.management.commands.migrate_mpt_assets.update_asset"
    )

    call_command(
        "migrate_mpt_assets",
        agreements=[mock_agreement_missing_asset_external_id["id"]],
    )

    err_log = capsys.readouterr().err
    assert "Error getting Adobe subscriptions for agreement AGR-2119-4550-8674-5962" in err_log
    mock_update_asset.assert_not_called()


def test_handle_update_mpt_assets_api_error(
    mocker,
    mock_adobe_client,
    mock_setup_client,
    mock_agreement_missing_asset_external_id,
    mock_adobe_subscriptions,
    mpt_error_factory,
    capsys,
) -> None:
    mocker.patch(
        "adobe_vipm.management.commands.migrate_mpt_assets.get_agreements_by_query",
        return_value=[mock_agreement_missing_asset_external_id],
    )
    mock_adobe_client.get_subscriptions_by_deployment.return_value = mock_adobe_subscriptions
    mock_update_asset = mocker.patch(
        "adobe_vipm.management.commands.migrate_mpt_assets.update_asset",
        side_effect=MPTAPIError(500, mpt_error_factory(500, "Internal Server Error", "Oops!")),
    )

    call_command(
        "migrate_mpt_assets",
        agreements=[mock_agreement_missing_asset_external_id["id"]],
    )

    err_log = capsys.readouterr().err
    assert "Error updating asset AST-0535-8763-6274" in err_log
    mock_update_asset.assert_called_once()
