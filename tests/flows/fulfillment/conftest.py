import pytest

from adobe_vipm.adobe.constants import AdobeOrderStatus
from adobe_vipm.adobe.dataclasses import ReturnableOrderInfo

SUBSCRIPTION_ID = "6158e1cf0e4414a9b3a06d123969fdNA"


@pytest.fixture
def returnable_order_factory(adobe_order_factory, adobe_items_factory):
    def factory(order_id, creation_date, quantity, deployment_id=None):
        order = adobe_order_factory(
            order_type="NEW",
            order_id=order_id,
            items=adobe_items_factory(
                quantity=quantity,
                remaining_quantity=quantity,
                subscription_id=SUBSCRIPTION_ID,
                deployment_id=deployment_id,
            ),
            status=AdobeOrderStatus.COMPLETE.value,
            creation_date=creation_date,
        )
        return ReturnableOrderInfo(order=order, line=order["lineItems"][0], quantity=quantity)

    return factory


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
