import pytest


@pytest.fixture
def mock_fulfill_purchase_order(mocker):
    return mocker.patch(
        "adobe_vipm.flows.fulfillment.reseller_transfer.fulfill_purchase_order", spec=True
    )


@pytest.fixture
def mock_get_customer_id(mocker):
    return mocker.patch(
        "adobe_vipm.flows.fulfillment.reseller_transfer.get_adobe_customer_id", autospec=True
    )
