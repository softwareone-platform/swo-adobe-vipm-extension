from adobe_vipm.adobe.constants import ORDER_TYPE_PREVIEW
from adobe_vipm.flows.helpers import update_purchase_prices


def test_update_purchase_price(
    mocker,
    seller,
    order_factory,
    adobe_order_factory,
    items_factory,
    pricelist_items_factory,
):
    """
    Tests the update of unit purchase price based on sku with discount level
    returned in the adobe preview order looking at the pricelist.
    """
    m_mpt_client = mocker.MagicMock()
    adobe_preview_order = adobe_order_factory(ORDER_TYPE_PREVIEW)
    mocked_adobe_client = mocker.MagicMock()
    mocked_adobe_client.create_preview_order.return_value = adobe_preview_order
    not_for_sale_items = items_factory(external_vendor_id="65304578CA01A12")
    pricelist_items = pricelist_items_factory(unit_purchase_price=7892.11)
    order = order_factory()

    m_get_prod_items = mocker.patch(
        "adobe_vipm.flows.helpers.get_product_items_by_skus",
        return_value=not_for_sale_items,
    )
    m_get_pl_items = mocker.patch(
        "adobe_vipm.flows.helpers.get_pricelist_items_by_product_items",
        return_value=pricelist_items,
    )

    updated_order = update_purchase_prices(
        m_mpt_client,
        mocked_adobe_client,
        seller["address"]["country"],
        order,
    )

    assert updated_order["lines"][0]["price"]["unitPP"] == 7892.11

    m_get_prod_items.assert_called_once_with(
        m_mpt_client,
        order["agreement"]["product"]["id"],
        [adobe_preview_order["lineItems"][0]["offerId"]],
    )

    m_get_pl_items.assert_called_once_with(
        m_mpt_client,
        order["agreement"]["listing"]["priceList"]["id"],
        [not_for_sale_items[0]["id"]],
    )
