def test_all_prices_found_in_airtable(
    price_manager_factory,
    mock_get_sku_price,
    mock_notify_missing_prices,
    mock_mpt_get_item_prices_by_pricelist_id,
):
    lines = [
        ({"item": {"id": "ITM-001"}}, "65304578CA01A12"),
        ({"item": {"id": "ITM-002"}}, "77777777CA01A12"),
    ]
    price_manager = price_manager_factory(lines=lines)
    mock_get_sku_price.return_value = {
        "65304578CA01A12": 100.00,
        "77777777CA01A12": 200.00,
    }

    result = price_manager.get_sku_prices_for_agreement_lines(
        skus=["65304578CA01A12", "77777777CA01A12"],
        product_id="PRD-1111-1111",
        currency="USD",
    )

    assert result == {"65304578CA01A12": 100.00, "77777777CA01A12": 200.00}
    mock_get_sku_price.assert_called_once_with(
        price_manager._adobe_customer,
        ["65304578CA01A12", "77777777CA01A12"],
        "PRD-1111-1111",
        "USD",
    )
    mock_mpt_get_item_prices_by_pricelist_id.assert_not_called()
    mock_notify_missing_prices.assert_not_called()


def test_missing_prices_recovered_from_mpt(
    price_manager_factory,
    mock_get_sku_price,
    mock_notify_missing_prices,
    mock_mpt_get_item_prices_by_pricelist_id,
):
    lines = [
        ({"item": {"id": "ITM-001"}}, "65304578CA01A12"),
        ({"item": {"id": "ITM-002"}}, "77777777CA01A12"),
    ]
    price_manager = price_manager_factory(lines=lines)
    mock_get_sku_price.return_value = {"65304578CA01A12": 100.00}
    mock_mpt_get_item_prices_by_pricelist_id.return_value = [{"unitPP": 200.00}]

    result = price_manager.get_sku_prices_for_agreement_lines(
        skus=["65304578CA01A12", "77777777CA01A12"],
        product_id="PRD-1111-1111",
        currency="USD",
    )

    assert result == {"65304578CA01A12": 100.00, "77777777CA01A12": 200.00}
    mock_mpt_get_item_prices_by_pricelist_id.assert_called_once_with(
        price_manager._mpt_client,
        "PRC-1234-5678",
        "ITM-002",
    )
    mock_notify_missing_prices.assert_called_once_with(
        "AGR-1234-5678",
        ["77777777CA01A12"],
        "PRD-1111-1111",
        "USD",
        None,
    )


def test_missing_prices_not_found_in_mpt(
    price_manager_factory,
    mock_get_sku_price,
    mock_notify_missing_prices,
    mock_mpt_get_item_prices_by_pricelist_id,
):
    lines = [
        ({"item": {"id": "ITM-001"}}, "65304578CA01A12"),
        ({"item": {"id": "ITM-002"}}, "77777777CA01A12"),
    ]
    price_manager = price_manager_factory(lines=lines)
    mock_get_sku_price.return_value = {"65304578CA01A12": 100.00}
    mock_mpt_get_item_prices_by_pricelist_id.return_value = []

    result = price_manager.get_sku_prices_for_agreement_lines(
        skus=["65304578CA01A12", "77777777CA01A12"],
        product_id="PRD-1111-1111",
        currency="USD",
    )

    assert result == {"65304578CA01A12": 100.00}
    mock_notify_missing_prices.assert_called_once_with(
        "AGR-1234-5678",
        ["77777777CA01A12"],
        "PRD-1111-1111",
        "USD",
        None,
    )
