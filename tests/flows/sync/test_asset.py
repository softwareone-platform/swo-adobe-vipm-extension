from freezegun import freeze_time


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
    mock_mpt_get_agreement_subscription,
    mock_mpt_update_agreement_subscription,
    mock_mpt_client,
    mock_mpt_update_agreement,
    mock_get_subscriptions_for_update,
    mocked_agreement_syncer,
    mock_mpt_update_asset,
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

    # ???: why are we testing the agreement syncer here?
    mocked_agreement_syncer.sync(sync_prices=False)

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
    mock_mpt_update_agreement.assert_has_calls([
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
    mock_get_subscriptions_for_update,
    mocked_agreement_syncer,
    mock_mpt_update_asset,
    mock_add_missing_subscriptions,
):
    asset_id = "AST-1111-2222-3333"
    mock_asset = assets_factory(asset_id=asset_id, adobe_subscription_id="sub-one-time-id")[0]
    mocker.patch("mpt_extension_sdk.mpt_http.mpt.get_asset_by_id", return_value=mock_asset)
    mock_lines = lines_factory(external_vendor_id="65304578CA")
    agreement = agreement_factory(lines=mock_lines, assets=[mock_asset], subscriptions=[])
    mocked_agreement_syncer._agreement = agreement
    mocked_agreement_syncer._dry_run = True
    adobe_subscription = adobe_subscription_factory(
        subscription_id="sub-one-time-id",
        offer_id="65304578CA01A12",
        used_quantity=6,
    )
    mocked_agreement_syncer._adobe_subscriptions = [adobe_subscription]
    mock_adobe_client.get_subscriptions.return_value = {"items": [adobe_subscription]}
    mocked_agreement_syncer._customer = adobe_customer_factory(coterm_date="2025-04-04")
    mock_get_subscriptions_for_update.return_value = []

    # ???: Why are we testing the agreement sync here?
    mocked_agreement_syncer.sync(sync_prices=False)

    mock_mpt_update_asset.assert_not_called()
