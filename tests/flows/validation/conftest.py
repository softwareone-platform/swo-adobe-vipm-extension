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
        return mock_get_sku_adobe_mapping_model.from_short_id(sku)

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
def mock_get_preview_order(
    mocker,
):
    return mocker.patch("adobe_vipm.flows.validation.transfer.GetPreviewOrder", autospec=True)
