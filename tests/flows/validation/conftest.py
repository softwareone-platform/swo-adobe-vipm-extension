import pytest


@pytest.fixture
def mock_update_order(mocker):
    return mocker.patch("adobe_vipm.flows.validation.transfer.update_order", spec=True)


@pytest.fixture
def mock_get_product_items_by_skus(mocker, items_factory):
    return mocker.patch(
        "adobe_vipm.flows.validation.transfer.get_product_items_by_skus",
        return_value=items_factory(),
        spec=True,
    )


@pytest.fixture
def mock_get_adobe_product_by_marketplace_sku(mocker, mock_get_sku_adobe_mapping_model):
    def get_adobe_product_by_marketplace_sku(sku):
        return mock_get_sku_adobe_mapping_model.from_short_id(sku, "COM")

    mocker.patch(
        "adobe_vipm.flows.helpers.get_adobe_product_by_marketplace_sku",
        new=get_adobe_product_by_marketplace_sku,
        spec=True,
    )
    return get_adobe_product_by_marketplace_sku


@pytest.fixture
def mock_get_agreement(mocker, mock_agreement):
    return mocker.patch(
        "adobe_vipm.flows.validation.transfer.get_agreement",
        return_value=mock_agreement,
        autospec=True,
    )


@pytest.fixture
def mock_get_preview_order(mocker):
    return mocker.patch("adobe_vipm.flows.validation.transfer.GetPreviewOrder", autospec=True)


@pytest.fixture
def mock_add_reseller_change_lines_to_order(mocker):
    return mocker.patch(
        "adobe_vipm.flows.validation.transfer.AddResellerChangeLinesToOrder", autospec=True
    )


@pytest.fixture
def mock_validate_reseller_change(mocker):
    return mocker.patch(
        "adobe_vipm.flows.validation.transfer.ValidateResellerChange", autospec=True
    )


@pytest.fixture
def mock_update_prices(mocker):
    return mocker.patch("adobe_vipm.flows.validation.transfer.UpdatePrices", autospec=True)


@pytest.fixture
def mock_send_error(mocker):
    return mocker.patch("adobe_vipm.flows.validation.transfer.send_error", autospec=True)
