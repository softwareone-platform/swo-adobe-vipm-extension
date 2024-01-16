import pytest

from adobe_vipm.adobe.errors import AdobeError
from adobe_vipm.flows.constants import (
    ORDER_STATUS_DESCRIPTION,
    STATUS_PENDING,
    UNRECOVERABLE_ORDER_STATUSES,
)
from adobe_vipm.flows.fulfillment import fulfill_order


def test_fulfill_order_purchase_no_customer(
    mocker,
    settings,
    seller,
    order_factory,
    fulfillment_parameters_factory,
):
    settings.EXTENSION_CONFIG["COMPLETED_TEMPLATE_ID"] = "TPL-1111"
    mocked_get_seller = mocker.patch(
        "adobe_vipm.flows.fulfillment.get_seller",
        return_value=seller,
    )
    mocked_create_customer_account = mocker.patch(
        "adobe_vipm.flows.fulfillment.create_customer_account",
        return_value=order_factory(
            fulfillment_parameters=fulfillment_parameters_factory(
                customer_id="a-client-id"
            ),
        ),
    )
    mocked_adobe_client = mocker.MagicMock()
    mocked_adobe_client.create_preview_order.return_value = {"preview": "order"}
    mocked_adobe_client.create_new_order.return_value = {"orderId": "an-order-id"}
    mocked_adobe_client.get_order.return_value = {
        "status": "1000",
        "lineItems": [
            {
                "subscriptionId": "a-sub-id",
                "lineNumber": 1,
            },
        ],
    }
    mocked_adobe_client.get_subscription.return_value = {
        "offerId": "65304578CA0412",
        "creationDate": "a-creation-date",
    }
    mocker.patch(
        "adobe_vipm.flows.fulfillment.get_adobe_client",
        return_value=mocked_adobe_client,
    )
    mocked_mpt_client = mocker.MagicMock()
    mocked_update_order = mocker.patch(
        "adobe_vipm.flows.fulfillment.update_order",
        return_value=order_factory(
            fulfillment_parameters=fulfillment_parameters_factory(
                customer_id="a-client-id",
            ),
            external_ids={"vendor": "an-order-id"},
        ),
    )
    mocked_create_subscription = mocker.patch(
        "adobe_vipm.flows.fulfillment.create_subscription",
    )
    mocked_complete_order = mocker.patch(
        "adobe_vipm.flows.fulfillment.complete_order",
    )

    order = order_factory()

    fulfill_order(mocked_mpt_client, order)

    seller_country = seller["address"]["country"]

    mocked_get_seller.assert_called_once_with(mocked_mpt_client, seller["id"])
    mocked_create_customer_account.assert_called_once_with(
        mocked_mpt_client,
        seller_country,
        order,
    )
    mocked_adobe_client.create_preview_order.assert_called_once_with(
        seller_country,
        "a-client-id",
        order_factory(
            fulfillment_parameters=fulfillment_parameters_factory(
                customer_id="a-client-id"
            )
        ),
    )

    mocked_update_order.assert_called_once_with(
        mocked_mpt_client,
        order["id"],
        {
            "externalIDs": {
                "vendor": "an-order-id",
            },
        },
    )
    mocked_create_subscription.assert_called_once_with(
        mocked_mpt_client,
        order["id"],
        {
            "name": "Subscription for 65304578CA0412",
            "parameters": {
                "fulfillment": [
                    {
                        "name": "SubscriptionId",
                        "value": "a-sub-id",
                    },
                ],
            },
            "items": [
                {
                    "lineNumber": 1,
                },
            ],
            "startDate": "a-creation-date",
        },
    )
    mocked_complete_order.assert_called_once_with(
        mocked_mpt_client,
        order["id"],
        "TPL-1111",
    )
    mocked_adobe_client.get_order.assert_called_once_with(
        seller_country,
        "a-client-id",
        "an-order-id",
    )
    mocked_adobe_client.get_subscription.assert_called_once_with(
        seller_country,
        "a-client-id",
        "a-sub-id",
    )


def test_fulfill_order_purchase_customer_already_created(
    mocker,
    seller,
    order_factory,
    order_parameters_factory,
    fulfillment_parameters_factory,
):
    mocked_get_seller = mocker.patch(
        "adobe_vipm.flows.fulfillment.get_seller",
        return_value=seller,
    )
    mocked_create_customer_account = mocker.patch(
        "adobe_vipm.flows.fulfillment.create_customer_account",
        return_value=None,
    )
    mocked_adobe_client = mocker.MagicMock()
    mocked_adobe_client.create_preview_order.return_value = {"preview": "order"}
    mocked_adobe_client.create_new_order.return_value = {"orderId": "an-order-id"}
    mocked_adobe_client.get_order.return_value = {"status": STATUS_PENDING}
    mocker.patch(
        "adobe_vipm.flows.fulfillment.get_adobe_client",
        return_value=mocked_adobe_client,
    )
    mocked_mpt_client = mocker.MagicMock()
    mocked_update_order = mocker.patch(
        "adobe_vipm.flows.fulfillment.update_order",
        return_value=order_factory(
            fulfillment_parameters=fulfillment_parameters_factory(
                customer_id="a-client-id",
            ),
            external_ids={"vendor": "an-order-id"},
        ),
    )

    order = order_factory(
        fulfillment_parameters=fulfillment_parameters_factory(customer_id="a-client-id")
    )

    fulfill_order(mocked_mpt_client, order)

    seller_country = seller["address"]["country"]

    mocked_get_seller.assert_called_once_with(mocked_mpt_client, seller["id"])
    mocked_create_customer_account.assert_not_called()
    mocked_adobe_client.create_preview_order.assert_called_once_with(
        seller_country,
        "a-client-id",
        order_factory(
            fulfillment_parameters=fulfillment_parameters_factory(
                customer_id="a-client-id"
            )
        ),
    )

    assert mocked_update_order.mock_calls[0].args == (
        mocked_mpt_client,
        order["id"],
        {
            "externalIDs": {
                "vendor": "an-order-id",
            },
        },
    )
    assert mocked_update_order.mock_calls[1].args == (
        mocked_mpt_client,
        order["id"],
        {
            "parameters": {
                "fulfillment": fulfillment_parameters_factory(
                    customer_id="a-client-id",
                    retry_count="1",
                ),
                "order": order_parameters_factory(),
            },
        },
    )


def test_fulfill_order_purchase_create_customer_fails(
    mocker,
    seller,
    order_factory,
):
    mocker.patch(
        "adobe_vipm.flows.fulfillment.get_seller",
        return_value=seller,
    )
    mocked_create_customer_account = mocker.patch(
        "adobe_vipm.flows.fulfillment.create_customer_account",
        return_value=None,
    )
    mocked_adobe_client = mocker.MagicMock()
    mocker.patch(
        "adobe_vipm.flows.fulfillment.get_adobe_client",
        return_value=mocked_adobe_client,
    )
    mocked_mpt_client = mocker.MagicMock()

    order = order_factory()

    fulfill_order(mocked_mpt_client, order)

    mocked_create_customer_account.assert_called_once()
    mocked_adobe_client.create_preview_order.assert_not_called()


def test_fulfill_order_purchase_create_adobe_error(
    mocker,
    seller,
    order_factory,
    fulfillment_parameters_factory,
):
    mocker.patch(
        "adobe_vipm.flows.fulfillment.get_seller",
        return_value=seller,
    )
    mocker.patch(
        "adobe_vipm.flows.fulfillment.create_customer_account",
        return_value=None,
    )

    adobe_error = AdobeError(
        {
            "code": "9999",
            "message": "Error while creating a preview order",
        },
    )

    mocked_adobe_client = mocker.MagicMock()
    mocked_adobe_client.create_preview_order.side_effect = adobe_error
    mocker.patch(
        "adobe_vipm.flows.fulfillment.get_adobe_client",
        return_value=mocked_adobe_client,
    )

    mocked_fail_order = mocker.patch("adobe_vipm.flows.fulfillment.fail_order")

    mocked_mpt_client = mocker.MagicMock()

    order = order_factory(
        fulfillment_parameters=fulfillment_parameters_factory(customer_id="a-client-id")
    )

    fulfill_order(mocked_mpt_client, order)

    mocked_fail_order.assert_called_once_with(
        mocked_mpt_client,
        order["id"],
        str(adobe_error),
    )


def test_fulfill_order_purchase_customer_and_order_already_created_adobe_order_not_ready(
    mocker,
    seller,
    order_factory,
    order_parameters_factory,
    fulfillment_parameters_factory,
):
    mocked_get_seller = mocker.patch(
        "adobe_vipm.flows.fulfillment.get_seller",
        return_value=seller,
    )
    mocked_update_order = mocker.patch(
        "adobe_vipm.flows.fulfillment.update_order",
    )
    mocked_complete_order = mocker.patch(
        "adobe_vipm.flows.fulfillment.complete_order",
    )
    mocked_adobe_client = mocker.MagicMock()
    mocked_adobe_client.get_order.return_value = {"status": "1002"}
    mocker.patch(
        "adobe_vipm.flows.fulfillment.get_adobe_client",
        return_value=mocked_adobe_client,
    )
    mocked_mpt_client = mocker.MagicMock()

    order = order_factory(
        fulfillment_parameters=fulfillment_parameters_factory(
            customer_id="a-client-id",
        ),
        external_ids={"vendor": "an-order-id"},
    )

    fulfill_order(mocked_mpt_client, order)

    mocked_get_seller.assert_called_once_with(mocked_mpt_client, seller["id"])
    mocked_adobe_client.get_subscription.assert_not_called()
    mocked_update_order.assert_called_once_with(
        mocked_mpt_client,
        order["id"],
        {
            "parameters": {
                "order": order_parameters_factory(),
                "fulfillment": fulfillment_parameters_factory(
                    customer_id="a-client-id",
                    retry_count="1",
                ),
            }
        },
    )
    mocked_complete_order.assert_not_called()


def test_fulfill_order_purchase_customer_already_created_order_already_created_max_retries_reached(
    mocker,
    seller,
    order_factory,
    fulfillment_parameters_factory,
):
    mocked_get_seller = mocker.patch(
        "adobe_vipm.flows.fulfillment.get_seller",
        return_value=seller,
    )
    mocked_fail_order = mocker.patch(
        "adobe_vipm.flows.fulfillment.fail_order",
    )
    mocked_adobe_client = mocker.MagicMock()
    mocked_adobe_client.get_order.return_value = {"status": "1002"}
    mocker.patch(
        "adobe_vipm.flows.fulfillment.get_adobe_client",
        return_value=mocked_adobe_client,
    )
    mocked_mpt_client = mocker.MagicMock()

    order = order_factory(
        fulfillment_parameters=fulfillment_parameters_factory(
            customer_id="a-client-id",
            retry_count=10,
        ),
        external_ids={"vendor": "an-order-id"},
    )

    fulfill_order(mocked_mpt_client, order)

    mocked_get_seller.assert_called_once_with(mocked_mpt_client, seller["id"])
    mocked_adobe_client.get_subscription.assert_not_called()
    mocked_fail_order.assert_called_once_with(
        mocked_mpt_client,
        order["id"],
        "Max processing attemps reached (10)",
    )


@pytest.mark.parametrize(
    "order_status",
    UNRECOVERABLE_ORDER_STATUSES,
)
def test_fulfill_order_purchase_customer_already_created_order_already_created_unrecoverable_status(
    mocker,
    seller,
    order_factory,
    fulfillment_parameters_factory,
    order_status,
):
    mocked_get_seller = mocker.patch(
        "adobe_vipm.flows.fulfillment.get_seller",
        return_value=seller,
    )
    mocked_fail_order = mocker.patch(
        "adobe_vipm.flows.fulfillment.fail_order",
    )
    mocked_adobe_client = mocker.MagicMock()
    mocked_adobe_client.get_order.return_value = {"status": order_status}
    mocker.patch(
        "adobe_vipm.flows.fulfillment.get_adobe_client",
        return_value=mocked_adobe_client,
    )
    mocked_mpt_client = mocker.MagicMock()

    order = order_factory(
        fulfillment_parameters=fulfillment_parameters_factory(
            customer_id="a-client-id",
            retry_count=10,
        ),
        external_ids={"vendor": "an-order-id"},
    )

    fulfill_order(mocked_mpt_client, order)

    mocked_get_seller.assert_called_once_with(mocked_mpt_client, seller["id"])
    mocked_adobe_client.get_subscription.assert_not_called()
    mocked_fail_order.assert_called_once_with(
        mocked_mpt_client,
        order["id"],
        ORDER_STATUS_DESCRIPTION[order_status],
    )


def test_fulfill_order_purchase_customer_already_created_order_already_created_unexpected_status(
    mocker,
    seller,
    order_factory,
    fulfillment_parameters_factory,
):
    mocked_get_seller = mocker.patch(
        "adobe_vipm.flows.fulfillment.get_seller",
        return_value=seller,
    )
    mocked_fail_order = mocker.patch(
        "adobe_vipm.flows.fulfillment.fail_order",
    )
    mocked_adobe_client = mocker.MagicMock()
    mocked_adobe_client.get_order.return_value = {"status": "9999"}
    mocker.patch(
        "adobe_vipm.flows.fulfillment.get_adobe_client",
        return_value=mocked_adobe_client,
    )
    mocked_mpt_client = mocker.MagicMock()

    order = order_factory(
        fulfillment_parameters=fulfillment_parameters_factory(
            customer_id="a-client-id",
            retry_count=10,
        ),
        external_ids={"vendor": "an-order-id"},
    )

    fulfill_order(mocked_mpt_client, order)

    mocked_get_seller.assert_called_once_with(mocked_mpt_client, seller["id"])
    mocked_adobe_client.get_subscription.assert_not_called()
    mocked_fail_order.assert_called_once_with(
        mocked_mpt_client,
        order["id"],
        "Unexpected status (9999) received from Adobe.",
    )


def test_fulfill_order_upsizing(
    mocker,
    settings,
    seller,
    order_factory,
    items_factory,
    fulfillment_parameters_factory,
    subscriptions_factory,
):
    settings.EXTENSION_CONFIG["COMPLETED_TEMPLATE_ID"] = "TPL-1111"
    mocked_get_seller = mocker.patch(
        "adobe_vipm.flows.fulfillment.get_seller",
        return_value=seller,
    )
    mocked_adobe_client = mocker.MagicMock()
    mocked_adobe_client.create_preview_order.return_value = {"preview": "order"}
    mocked_adobe_client.create_new_order.return_value = {"orderId": "an-order-id"}
    mocked_adobe_client.get_order.return_value = {
        "status": "1000",
        "lineItems": [
            {
                "subscriptionId": "a-sub-id",
                "lineNumber": 1,
            },
        ],
    }
    mocked_adobe_client.get_subscription.return_value = {
        "offerId": "65304578CA0412",
        "creationDate": "a-creation-date",
    }
    mocker.patch(
        "adobe_vipm.flows.fulfillment.get_adobe_client",
        return_value=mocked_adobe_client,
    )
    mocked_mpt_client = mocker.MagicMock()
    mocked_update_order = mocker.patch(
        "adobe_vipm.flows.fulfillment.update_order",
        return_value=order_factory(
            order_type="Change",
            items=items_factory(
                old_quantity=10,
                quantity=20,
            ),
            subscriptions=subscriptions_factory(
                items=items_factory(quantity=10),
            ),
            agreement_fulfillment_parameters=fulfillment_parameters_factory(
                customer_id="a-client-id",
            ),
            order_parameters=[],
            external_ids={"vendor": "an-order-id"},
        ),
    )

    mocked_update_subscription = mocker.patch(
        "adobe_vipm.flows.fulfillment.update_subscription",
    )
    mocked_complete_order = mocker.patch(
        "adobe_vipm.flows.fulfillment.complete_order",
    )

    order = order_factory(
        order_type="Change",
        items=items_factory(
            old_quantity=10,
            quantity=20,
        ),
        agreement_fulfillment_parameters=fulfillment_parameters_factory(
            customer_id="a-client-id",
        ),
        order_parameters=[],
    )

    fulfill_order(mocked_mpt_client, order)

    seller_country = seller["address"]["country"]

    mocked_get_seller.assert_called_once_with(mocked_mpt_client, seller["id"])
    mocked_adobe_client.create_preview_order.assert_called_once_with(
        seller_country,
        "a-client-id",
        order_factory(
            order_type="Change",
            items=items_factory(
                old_quantity=10,
                quantity=20,
            ),
            agreement_fulfillment_parameters=fulfillment_parameters_factory(
                customer_id="a-client-id",
            ),
            order_parameters=[],
        ),
    )

    assert mocked_update_order.mock_calls[0].args == (
        mocked_mpt_client,
        order["id"],
        {
            "externalIDs": {
                "vendor": "an-order-id",
            },
        },
    )

    subscription = subscriptions_factory(
        items=items_factory(quantity=20),
    )[0]

    mocked_update_subscription.assert_called_once_with(
        mocked_mpt_client,
        order["id"],
        subscription["id"],
        {"items": subscription["items"]},
    )
    mocked_complete_order.assert_called_once_with(
        mocked_mpt_client,
        order["id"],
        "TPL-1111",
    )


def test_fulfill_order_upsizing_order_already_created_adobe_order_not_ready(
    mocker,
    seller,
    order_factory,
    items_factory,
    fulfillment_parameters_factory,
):
    mocked_get_seller = mocker.patch(
        "adobe_vipm.flows.fulfillment.get_seller",
        return_value=seller,
    )
    mocked_update_order = mocker.patch(
        "adobe_vipm.flows.fulfillment.update_order",
    )
    mocked_complete_order = mocker.patch(
        "adobe_vipm.flows.fulfillment.complete_order",
    )
    mocked_adobe_client = mocker.MagicMock()
    mocked_adobe_client.get_order.return_value = {"status": "1002"}
    mocker.patch(
        "adobe_vipm.flows.fulfillment.get_adobe_client",
        return_value=mocked_adobe_client,
    )
    mocked_mpt_client = mocker.MagicMock()

    order = order_factory(
        order_type="Change",
        items=items_factory(
            old_quantity=10,
            quantity=20,
        ),
        agreement_fulfillment_parameters=fulfillment_parameters_factory(
            customer_id="a-client-id",
        ),
        order_parameters=[],
        external_ids={"vendor": "an-order-id"},
    )

    fulfill_order(mocked_mpt_client, order)

    mocked_get_seller.assert_called_once_with(mocked_mpt_client, seller["id"])
    mocked_adobe_client.get_subscription.assert_not_called()
    mocked_update_order.assert_called_once_with(
        mocked_mpt_client,
        order["id"],
        {
            "parameters": {
                "fulfillment": fulfillment_parameters_factory(
                    retry_count="1",
                ),
                "order": [],
            }
        },
    )
    mocked_complete_order.assert_not_called()


def test_fulfill_order_upsizing_create_adobe_error(
    mocker,
    seller,
    order_factory,
    items_factory,
    fulfillment_parameters_factory,
):
    mocker.patch(
        "adobe_vipm.flows.fulfillment.get_seller",
        return_value=seller,
    )

    adobe_error = AdobeError(
        {
            "code": "9999",
            "message": "Error while creating a preview order",
        },
    )

    mocked_adobe_client = mocker.MagicMock()
    mocked_adobe_client.create_preview_order.side_effect = adobe_error
    mocker.patch(
        "adobe_vipm.flows.fulfillment.get_adobe_client",
        return_value=mocked_adobe_client,
    )

    mocked_fail_order = mocker.patch("adobe_vipm.flows.fulfillment.fail_order")

    mocked_mpt_client = mocker.MagicMock()

    order = order_factory(
        order_type="Change",
        items=items_factory(
            old_quantity=10,
            quantity=20,
        ),
        agreement_fulfillment_parameters=fulfillment_parameters_factory(
            customer_id="a-client-id",
        ),
        order_parameters=[],
    )

    fulfill_order(mocked_mpt_client, order)

    mocked_fail_order.assert_called_once_with(
        mocked_mpt_client,
        order["id"],
        str(adobe_error),
    )


def test_fulfill_order_change_new_item(
    mocker,
    settings,
    seller,
    order_factory,
    items_factory,
    fulfillment_parameters_factory,
    subscriptions_factory,
):
    settings.EXTENSION_CONFIG["COMPLETED_TEMPLATE_ID"] = "TPL-1111"
    mocked_get_seller = mocker.patch(
        "adobe_vipm.flows.fulfillment.get_seller",
        return_value=seller,
    )
    mocked_adobe_client = mocker.MagicMock()
    mocked_adobe_client.create_preview_order.return_value = {"preview": "order"}
    mocked_adobe_client.create_new_order.return_value = {"orderId": "an-order-id"}
    mocked_adobe_client.get_order.return_value = {
        "status": "1000",
        "lineItems": [
            {
                "subscriptionId": "a-sub-id",
                "lineNumber": 1,
            },
        ],
    }
    mocked_adobe_client.get_subscription.return_value = {
        "offerId": "00000000CA0412",
        "creationDate": "a-creation-date",
    }
    mocker.patch(
        "adobe_vipm.flows.fulfillment.get_adobe_client",
        return_value=mocked_adobe_client,
    )
    mocked_mpt_client = mocker.MagicMock()
    mocked_update_order = mocker.patch(
        "adobe_vipm.flows.fulfillment.update_order",
        return_value=order_factory(
            order_type="Change",
            items=items_factory(
                product_item_id="00000000C",
                old_quantity=0,
                quantity=15,
            ),
            subscriptions=subscriptions_factory(
                items=items_factory(quantity=10),
            ),
            agreement_fulfillment_parameters=fulfillment_parameters_factory(
                customer_id="a-client-id",
            ),
            order_parameters=[],
            external_ids={"vendor": "an-order-id"},
        ),
    )

    mocked_create_subscription = mocker.patch(
        "adobe_vipm.flows.fulfillment.create_subscription",
    )
    mocked_complete_order = mocker.patch(
        "adobe_vipm.flows.fulfillment.complete_order",
    )

    order = order_factory(
        order_type="Change",
        items=items_factory(
            product_item_id="00000000C",
            old_quantity=0,
            quantity=15,
        ),
        agreement_fulfillment_parameters=fulfillment_parameters_factory(
            customer_id="a-client-id",
        ),
        order_parameters=[],
    )

    fulfill_order(mocked_mpt_client, order)

    seller_country = seller["address"]["country"]

    mocked_get_seller.assert_called_once_with(mocked_mpt_client, seller["id"])
    mocked_adobe_client.create_preview_order.assert_called_once_with(
        seller_country,
        "a-client-id",
        order_factory(
            order_type="Change",
            items=items_factory(
                product_item_id="00000000C",
                old_quantity=0,
                quantity=15,
            ),
            agreement_fulfillment_parameters=fulfillment_parameters_factory(
                customer_id="a-client-id",
            ),
            order_parameters=[],
        ),
    )

    assert mocked_update_order.mock_calls[0].args == (
        mocked_mpt_client,
        order["id"],
        {
            "externalIDs": {
                "vendor": "an-order-id",
            },
        },
    )

    mocked_create_subscription.assert_called_once_with(
        mocked_mpt_client,
        order["id"],
        {
            "name": "Subscription for 00000000CA0412",
            "parameters": {
                "fulfillment": [
                    {
                        "name": "SubscriptionId",
                        "value": "a-sub-id",
                    },
                ],
            },
            "items": [
                {
                    "lineNumber": 1,
                },
            ],
            "startDate": "a-creation-date",
        },
    )
    mocked_complete_order.assert_called_once_with(
        mocked_mpt_client,
        order["id"],
        "TPL-1111",
    )
