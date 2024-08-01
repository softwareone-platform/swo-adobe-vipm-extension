from adobe_vipm.adobe.constants import ORDER_TYPE_PREVIEW
from adobe_vipm.flows.helpers import (
    update_purchase_prices,
    update_purchase_prices_for_transfer,
)


def test_update_purchase_price(
    mocker,
    order_factory,
    adobe_order_factory,
):
    """
    Tests the update of unit purchase price based on sku with discount level
    returned in the adobe preview order looking at the pricelist.
    """
    adobe_preview_order = adobe_order_factory(ORDER_TYPE_PREVIEW)
    mocked_adobe_client = mocker.MagicMock()
    mocked_adobe_client.create_preview_order.return_value = adobe_preview_order
    order = order_factory()
    mocker.patch(
        "adobe_vipm.flows.helpers.get_prices_for_skus",
        return_value={"65304578CA01A12": 7892.11},
    )
    updated_order = update_purchase_prices(
        mocked_adobe_client,
        order,
    )

    assert updated_order["lines"][0]["price"]["unitPP"] == 7892.11



def test_update_purchase_price_for_transfer(
    mocker,
    order_factory,
    adobe_preview_transfer_factory,
):
    mocker.patch(
        "adobe_vipm.flows.helpers.get_prices_for_skus",
        return_value={"65304578CA01A12": 7892.11},
    )
    order = order_factory()

    adobe_transfer_preview = adobe_preview_transfer_factory()

    updated_order = update_purchase_prices_for_transfer(
        order,
        adobe_transfer_preview,
    )

    assert updated_order["lines"][0]["price"]["unitPP"] == 7892.11
