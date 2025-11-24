from freezegun import freeze_time

from adobe_vipm.flows.sync.asset import AssetsSyncer


@freeze_time("2025-06-23")
def test_asset_syncer_sync(
    mocker,
    mock_mpt_client,
    adobe_subscription_factory,
    adobe_customer_factory,
    agreement_factory,
    assets_factory,
    lines_factory,
    mock_mpt_update_asset,
):
    asset_id = "AST-1111-2222-3333"
    mock_asset = assets_factory(asset_id=asset_id, adobe_subscription_id="sub-one-time-id")[0]
    mock_mpt_get_asset_by_id = mocker.patch(
        "mpt_extension_sdk.mpt_http.mpt.get_asset_by_id", return_value=mock_asset
    )
    mock_lines = lines_factory(external_vendor_id="65304578CA")
    agreement = agreement_factory(lines=mock_lines, assets=[mock_asset], subscriptions=[])
    adobe_subscription = adobe_subscription_factory(
        subscription_id="sub-one-time-id",
        offer_id="65304578CA01A12",
        used_quantity=6,
    )
    mock_customer = adobe_customer_factory(coterm_date="2025-04-04")
    assets_syncer = AssetsSyncer(
        mock_mpt_client, agreement["id"], [mock_asset], mock_customer, [adobe_subscription]
    )

    assets_syncer.sync(dry_run=False)  # act

    mock_mpt_get_asset_by_id.assert_called_once_with(mock_mpt_client, asset_id)
    mock_mpt_update_asset.assert_called_once_with(
        mock_mpt_client,
        asset_id,
        parameters={
            "fulfillment": [
                {"externalId": "usedQuantity", "value": "6"},
                {"externalId": "lastSyncDate", "value": "2025-06-23"},
            ]
        },
    )


def test_asset_syncer_sync_asset_without_external_id(
    mocker,
    mock_mpt_client,
    adobe_subscription_factory,
    adobe_customer_factory,
    agreement_factory,
    assets_factory,
    lines_factory,
    mock_mpt_update_asset,
    caplog,
):
    asset_id = "AST-1111-2222-3333"
    mock_asset = assets_factory(asset_id=asset_id, adobe_subscription_id="sub-one-time-id")[0]
    mock_asset["externalIds"] = {}
    mock_mpt_get_asset_by_id = mocker.patch(
        "mpt_extension_sdk.mpt_http.mpt.get_asset_by_id", return_value=mock_asset
    )
    mock_lines = lines_factory(external_vendor_id="65304578CA")
    agreement = agreement_factory(lines=mock_lines, assets=[mock_asset], subscriptions=[])
    adobe_subscription = adobe_subscription_factory(
        subscription_id="sub-one-time-id",
        offer_id="65304578CA01A12",
        used_quantity=6,
    )
    mock_customer = adobe_customer_factory(coterm_date="2025-04-04")
    assets_syncer = AssetsSyncer(
        mock_mpt_client, agreement["id"], [mock_asset], mock_customer, [adobe_subscription]
    )

    assets_syncer.sync(dry_run=False)  # act

    mock_mpt_get_asset_by_id.assert_called_once_with(mock_mpt_client, asset_id)
    mock_mpt_update_asset.assert_not_called()
    assert (
        "No vendor subscription found for asset AST-1111-2222-3333: asset.externalIds.vendor "
        "is empty" in caplog.text
    )


@freeze_time("2025-06-23")
def test_sync_agreement_update_asset_dry_run(
    mocker,
    mock_mpt_client,
    adobe_subscription_factory,
    adobe_customer_factory,
    agreement_factory,
    assets_factory,
    lines_factory,
    mock_mpt_update_asset,
):
    asset_id = "AST-1111-2222-3333"
    mock_asset = assets_factory(asset_id=asset_id, adobe_subscription_id="sub-one-time-id")[0]
    mock_mpt_get_asset_by_id = mocker.patch(
        "mpt_extension_sdk.mpt_http.mpt.get_asset_by_id", return_value=mock_asset
    )
    mock_lines = lines_factory(external_vendor_id="65304578CA")
    agreement = agreement_factory(lines=mock_lines, assets=[mock_asset], subscriptions=[])
    adobe_subscription = adobe_subscription_factory(
        subscription_id="sub-one-time-id",
        offer_id="65304578CA01A12",
        used_quantity=6,
    )
    mock_customer = adobe_customer_factory(coterm_date="2025-04-04")
    assets_syncer = AssetsSyncer(
        mock_mpt_client, agreement["id"], [mock_asset], mock_customer, [adobe_subscription]
    )

    assets_syncer.sync(dry_run=True)  # act

    mock_mpt_get_asset_by_id.assert_called_once()
    mock_mpt_update_asset.assert_not_called()
