import copy

import pytest

from adobe_vipm.adobe.constants import (
    ORDER_STATUS_DESCRIPTION,
    ORDER_TYPE_NEW,
    ORDER_TYPE_PREVIEW,
    STATUS_ACCOUNT_ALREADY_EXISTS,
    STATUS_INVALID_ADDRESS,
    STATUS_INVALID_FIELDS,
    STATUS_INVALID_MINIMUM_QUANTITY,
    STATUS_PENDING,
    STATUS_PROCESSED,
    UNRECOVERABLE_ORDER_STATUSES,
)
from adobe_vipm.adobe.errors import AdobeAPIError, AdobeError
from adobe_vipm.flows.constants import (
    ERR_3YC_NO_MINIMUMS,
    ERR_3YC_QUANTITY_CONSUMABLES,
    ERR_3YC_QUANTITY_LICENSES,
    ERR_ADOBE_ADDRESS,
    ERR_ADOBE_COMPANY_NAME,
    ERR_ADOBE_CONTACT,
    MPT_ORDER_STATUS_COMPLETED,
    MPT_ORDER_STATUS_PROCESSING,
    MPT_ORDER_STATUS_QUERYING,
    PARAM_3YC_CONSUMABLES,
    PARAM_3YC_LICENSES,
    PARAM_AGREEMENT_TYPE,
    PARAM_CONTACT,
    PARAM_MEMBERSHIP_ID,
    TEMPLATE_NAME_PURCHASE,
)
from adobe_vipm.flows.fulfillment import fulfill_order
from adobe_vipm.flows.fulfillment.purchase import create_customer_account
from adobe_vipm.flows.utils import (
    get_ordering_parameter,
    set_adobe_customer_id,
)


def test_no_customer(
    mocker,
    agreement,
    order_factory,
    order_parameters_factory,
    fulfillment_parameters_factory,
    adobe_order_factory,
    adobe_items_factory,
    adobe_subscription_factory,
    items_factory,
    subscriptions_factory,
    pricelist_items_factory,
):
    """
    Tests the processing of a purchase order including:
        * customer creation
        * order creation
        * subscription creation
        * order completion
        * usage of right templates
    """

    mocked_get_template = mocker.patch(
        "adobe_vipm.flows.fulfillment.shared.get_product_template_or_default",
        side_effect=[{"id": "TPL-0000"}, {"id": "TPL-1111"}],
    )

    mocker.patch("adobe_vipm.flows.helpers.get_agreement", return_value=agreement)
    mocked_create_customer_account = mocker.patch(
        "adobe_vipm.flows.fulfillment.purchase.create_customer_account",
        return_value=order_factory(
            fulfillment_parameters=fulfillment_parameters_factory(
                customer_id="a-client-id"
            ),
        ),
    )

    adobe_order = adobe_order_factory(
        ORDER_TYPE_NEW,
        status=STATUS_PROCESSED,
        items=adobe_items_factory(subscription_id="a-sub-id"),
    )
    adobe_preview_order = adobe_order_factory(ORDER_TYPE_PREVIEW)

    adobe_subscription = adobe_subscription_factory()

    mocked_adobe_client = mocker.MagicMock()
    mocked_adobe_client.create_preview_order.return_value = adobe_preview_order
    mocked_adobe_client.create_new_order.return_value = adobe_order
    mocked_adobe_client.get_order.return_value = adobe_order
    mocked_adobe_client.get_subscription.return_value = adobe_subscription
    mocker.patch(
        "adobe_vipm.flows.fulfillment.purchase.get_adobe_client",
        return_value=mocked_adobe_client,
    )

    mocked_mpt_client = mocker.MagicMock()
    mocked_update_order = mocker.patch(
        "adobe_vipm.flows.fulfillment.shared.update_order",
        side_effect=[
            order_factory(
                fulfillment_parameters=fulfillment_parameters_factory(
                    customer_id="a-client-id",
                    retry_count="1",
                ),
                external_ids={"vendor": adobe_order["orderId"]},
            ),
            order_factory(
                fulfillment_parameters=fulfillment_parameters_factory(
                    customer_id="a-client-id",
                    retry_count="0",
                ),
                external_ids={"vendor": adobe_order["orderId"]},
            ),
            order_factory(
                fulfillment_parameters=fulfillment_parameters_factory(
                    customer_id="a-client-id",
                    retry_count="0",
                ),
                external_ids={"vendor": adobe_order["orderId"]},
            ),
            order_factory(
                fulfillment_parameters=fulfillment_parameters_factory(
                    customer_id="a-client-id",
                    retry_count="0",
                    next_sync_date="2024-01-01",
                ),
                external_ids={"vendor": adobe_order["orderId"]},
            ),
        ],
    )

    subscription = subscriptions_factory(commitment_date="2024-01-01")[0]
    mocked_create_subscription = mocker.patch(
        "adobe_vipm.flows.fulfillment.shared.create_subscription",
        return_value=subscription,
    )
    mocker.patch(
        "adobe_vipm.flows.fulfillment.shared.get_product_items_by_skus",
        return_value=items_factory(),
    )
    mocker.patch(
        "adobe_vipm.flows.fulfillment.shared.get_pricelist_items_by_product_items",
        return_value=pricelist_items_factory(),
    )
    mocked_process_order = mocker.patch(
        "adobe_vipm.flows.fulfillment.shared.set_processing_template",
    )
    mocked_complete_order = mocker.patch(
        "adobe_vipm.flows.fulfillment.shared.complete_order",
    )

    order = order_factory()
    order_with_customer_param = order_factory(
        fulfillment_parameters=fulfillment_parameters_factory(customer_id="a-client-id")
    )

    fulfill_order(mocked_mpt_client, order)

    authorization_id = order["authorization"]["id"]

    mocked_create_customer_account.assert_called_once_with(
        mocked_mpt_client,
        order,
    )
    mocked_adobe_client.create_preview_order.assert_called_once_with(
        authorization_id,
        "a-client-id",
        order_with_customer_param["id"],
        order_with_customer_param["lines"],
    )

    assert mocked_update_order.mock_calls[0].args == (
        mocked_mpt_client,
        order["id"],
    )
    assert mocked_update_order.mock_calls[0].kwargs == {
        "externalIds": {
            "vendor": adobe_order["orderId"],
        },
    }
    assert mocked_update_order.mock_calls[1].args == (
        mocked_mpt_client,
        order["id"],
    )
    assert mocked_update_order.mock_calls[1].kwargs == {
        "parameters": {
            "fulfillment": fulfillment_parameters_factory(
                customer_id="a-client-id",
                retry_count="0",
                next_sync_date="2024-01-02",
            ),
            "ordering": order_parameters_factory(),
        },
    }
    assert mocked_update_order.mock_calls[2].args == (
        mocked_mpt_client,
        order["id"],
    )
    assert mocked_update_order.mock_calls[2].kwargs == {
        "lines": [
            {
                "id": order["lines"][0]["id"],
                "price": {
                    "unitPP": 1234.55,
                },
            }
        ],
    }
    assert mocked_update_order.mock_calls[3].args == (
        mocked_mpt_client,
        order["id"],
    )
    assert mocked_update_order.mock_calls[3].kwargs == {
        "parameters": {
            "fulfillment": fulfillment_parameters_factory(
                customer_id="a-client-id",
                retry_count="0",
                next_sync_date="2024-01-02",
            ),
            "ordering": order_parameters_factory(),
        },
    }

    # mocked_update_agreement.assert_called_once_with(
    #     externalIds={"vendor": "a-client-id"},
    # )

    mocked_create_subscription.assert_called_once_with(
        mocked_mpt_client,
        order["id"],
        {
            "name": "Subscription for Awesome product",
            "parameters": {
                "fulfillment": [
                    {
                        "externalId": "adobeSKU",
                        "value": adobe_subscription["offerId"],
                    },
                ],
            },
            "externalIds": {"vendor": adobe_subscription["subscriptionId"]},
            "lines": [
                {
                    "id": order["lines"][0]["id"],
                },
            ],
            "startDate": adobe_subscription["creationDate"],
            "commitmentDate": adobe_subscription["renewalDate"],
        },
    )
    mocked_process_order.assert_called_once_with(
        mocked_mpt_client,
        order["id"],
        {"id": "TPL-0000"},
    )
    mocked_complete_order.assert_called_once_with(
        mocked_mpt_client,
        order["id"],
        {"id": "TPL-1111"},
    )
    mocked_adobe_client.get_order.assert_called_once_with(
        authorization_id, "a-client-id", adobe_order["orderId"]
    )
    mocked_adobe_client.get_subscription.assert_called_once_with(
        authorization_id,
        "a-client-id",
        adobe_subscription["subscriptionId"],
    )
    assert mocked_get_template.mock_calls[0].args == (
        mocked_mpt_client,
        order["agreement"]["product"]["id"],
        MPT_ORDER_STATUS_PROCESSING,
        TEMPLATE_NAME_PURCHASE,
    )

    assert mocked_get_template.mock_calls[1].args == (
        mocked_mpt_client,
        order["agreement"]["product"]["id"],
        MPT_ORDER_STATUS_COMPLETED,
        TEMPLATE_NAME_PURCHASE,
    )


def test_no_customer_subscription_already_created(
    mocker,
    agreement,
    order_factory,
    order_parameters_factory,
    fulfillment_parameters_factory,
    adobe_order_factory,
    adobe_items_factory,
    adobe_subscription_factory,
    items_factory,
    subscriptions_factory,
    pricelist_items_factory,
):
    mocked_get_template = mocker.patch(
        "adobe_vipm.flows.fulfillment.shared.get_product_template_or_default",
        side_effect=[{"id": "TPL-0000"}, {"id": "TPL-1111"}],
    )

    mocker.patch("adobe_vipm.flows.helpers.get_agreement", return_value=agreement)
    mocked_create_customer_account = mocker.patch(
        "adobe_vipm.flows.fulfillment.purchase.create_customer_account",
        return_value=order_factory(
            fulfillment_parameters=fulfillment_parameters_factory(
                customer_id="a-client-id"
            ),
        ),
    )

    adobe_order = adobe_order_factory(
        ORDER_TYPE_NEW,
        status=STATUS_PROCESSED,
        items=adobe_items_factory(subscription_id="a-sub-id"),
    )
    adobe_preview_order = adobe_order_factory(ORDER_TYPE_PREVIEW)

    adobe_subscription = adobe_subscription_factory()

    mocked_adobe_client = mocker.MagicMock()
    mocked_adobe_client.create_preview_order.return_value = adobe_preview_order
    mocked_adobe_client.create_new_order.return_value = adobe_order
    mocked_adobe_client.get_order.return_value = adobe_order
    mocked_adobe_client.get_subscription.return_value = adobe_subscription
    mocker.patch(
        "adobe_vipm.flows.fulfillment.purchase.get_adobe_client",
        return_value=mocked_adobe_client,
    )

    mocked_mpt_client = mocker.MagicMock()
    mocked_update_order = mocker.patch(
        "adobe_vipm.flows.fulfillment.shared.update_order",
        side_effect=[
            order_factory(
                fulfillment_parameters=fulfillment_parameters_factory(
                    customer_id="a-client-id",
                    retry_count="1",
                ),
                external_ids={"vendor": adobe_order["orderId"]},
            ),
            order_factory(
                fulfillment_parameters=fulfillment_parameters_factory(
                    customer_id="a-client-id",
                    retry_count="0",
                ),
                external_ids={"vendor": adobe_order["orderId"]},
            ),
            order_factory(
                fulfillment_parameters=fulfillment_parameters_factory(
                    customer_id="a-client-id",
                    retry_count="0",
                ),
                external_ids={"vendor": adobe_order["orderId"]},
            ),
            order_factory(
                fulfillment_parameters=fulfillment_parameters_factory(
                    customer_id="a-client-id",
                    retry_count="0",
                    next_sync_date="2024-01-01",
                ),
                external_ids={"vendor": adobe_order["orderId"]},
            ),
        ],
    )

    subscription = subscriptions_factory(commitment_date="2024-01-01")[0]
    mocker.patch(
        "adobe_vipm.flows.fulfillment.shared.get_subscription_by_external_id",
        return_value=subscription,
    )
    mocker.patch(
        "adobe_vipm.flows.fulfillment.shared.get_product_items_by_skus",
        return_value=items_factory(),
    )
    mocker.patch(
        "adobe_vipm.flows.fulfillment.shared.get_pricelist_items_by_product_items",
        return_value=pricelist_items_factory(),
    )
    mocked_process_order = mocker.patch(
        "adobe_vipm.flows.fulfillment.shared.set_processing_template",
    )
    mocked_complete_order = mocker.patch(
        "adobe_vipm.flows.fulfillment.shared.complete_order",
    )

    order = order_factory()
    order_with_customer_param = order_factory(
        fulfillment_parameters=fulfillment_parameters_factory(customer_id="a-client-id")
    )

    fulfill_order(mocked_mpt_client, order)

    authorization_id = order["authorization"]["id"]

    mocked_create_customer_account.assert_called_once_with(
        mocked_mpt_client,
        order,
    )
    mocked_adobe_client.create_preview_order.assert_called_once_with(
        authorization_id,
        "a-client-id",
        order_with_customer_param["id"],
        order_with_customer_param["lines"],
    )

    assert mocked_update_order.mock_calls[0].args == (
        mocked_mpt_client,
        order["id"],
    )
    assert mocked_update_order.mock_calls[0].kwargs == {
        "externalIds": {
            "vendor": adobe_order["orderId"],
        },
    }
    assert mocked_update_order.mock_calls[1].args == (
        mocked_mpt_client,
        order["id"],
    )
    assert mocked_update_order.mock_calls[1].kwargs == {
        "parameters": {
            "fulfillment": fulfillment_parameters_factory(
                customer_id="a-client-id",
                retry_count="0",
                next_sync_date="2024-01-02",
            ),
            "ordering": order_parameters_factory(),
        },
    }
    assert mocked_update_order.mock_calls[2].args == (
        mocked_mpt_client,
        order["id"],
    )
    assert mocked_update_order.mock_calls[2].kwargs == {
        "lines": [
            {
                "id": order["lines"][0]["id"],
                "price": {
                    "unitPP": 1234.55,
                },
            }
        ],
    }
    assert mocked_update_order.mock_calls[3].args == (
        mocked_mpt_client,
        order["id"],
    )
    assert mocked_update_order.mock_calls[3].kwargs == {
        "parameters": {
            "fulfillment": fulfillment_parameters_factory(
                customer_id="a-client-id",
                retry_count="0",
                next_sync_date="2024-01-02",
            ),
            "ordering": order_parameters_factory(),
        },
    }

    mocked_process_order.assert_called_once_with(
        mocked_mpt_client,
        order["id"],
        {"id": "TPL-0000"},
    )
    mocked_complete_order.assert_called_once_with(
        mocked_mpt_client,
        order["id"],
        {"id": "TPL-1111"},
    )
    mocked_adobe_client.get_order.assert_called_once_with(
        authorization_id, "a-client-id", adobe_order["orderId"]
    )
    mocked_adobe_client.get_subscription.assert_called_once_with(
        authorization_id,
        "a-client-id",
        adobe_subscription["subscriptionId"],
    )
    assert mocked_get_template.mock_calls[0].args == (
        mocked_mpt_client,
        order["agreement"]["product"]["id"],
        MPT_ORDER_STATUS_PROCESSING,
        TEMPLATE_NAME_PURCHASE,
    )

    assert mocked_get_template.mock_calls[1].args == (
        mocked_mpt_client,
        order["agreement"]["product"]["id"],
        MPT_ORDER_STATUS_COMPLETED,
        TEMPLATE_NAME_PURCHASE,
    )


def test_customer_already_created(
    mocker,
    agreement,
    order_factory,
    order_parameters_factory,
    fulfillment_parameters_factory,
    adobe_order_factory,
):
    """
    Tests the processing of a purchase order with the customer already created.
    Adobe returns that the order is still processing.
    """
    mocker.patch("adobe_vipm.flows.helpers.get_agreement", return_value=agreement)
    mocked_create_customer_account = mocker.patch(
        "adobe_vipm.flows.fulfillment.purchase.create_customer_account",
    )

    adobe_preview_order = adobe_order_factory(ORDER_TYPE_PREVIEW)
    adobe_order = adobe_order_factory(ORDER_TYPE_NEW, status=STATUS_PENDING)

    mocked_adobe_client = mocker.MagicMock()
    mocked_adobe_client.create_preview_order.return_value = adobe_preview_order
    mocked_adobe_client.create_new_order.return_value = adobe_order
    mocked_adobe_client.get_order.return_value = adobe_order
    mocker.patch(
        "adobe_vipm.flows.fulfillment.purchase.get_adobe_client",
        return_value=mocked_adobe_client,
    )

    mocked_mpt_client = mocker.MagicMock()
    mocked_update_order = mocker.patch(
        "adobe_vipm.flows.fulfillment.shared.update_order",
        return_value=order_factory(
            fulfillment_parameters=fulfillment_parameters_factory(
                customer_id="a-client-id",
            ),
            external_ids={"vendor": adobe_order["orderId"]},
        ),
    )
    order = order_factory(
        fulfillment_parameters=fulfillment_parameters_factory(customer_id="a-client-id")
    )

    fulfill_order(mocked_mpt_client, order)

    authorization_id = order["authorization"]["id"]

    mocked_create_customer_account.assert_not_called()
    mocked_adobe_client.create_preview_order.assert_called_once_with(
        authorization_id,
        "a-client-id",
        order["id"],
        order["lines"],
    )

    assert mocked_update_order.mock_calls[0].args == (
        mocked_mpt_client,
        order["id"],
    )
    assert mocked_update_order.mock_calls[0].kwargs == {
        "externalIds": {
            "vendor": adobe_order["orderId"],
        },
    }
    assert mocked_update_order.mock_calls[1].args == (
        mocked_mpt_client,
        order["id"],
    )
    assert mocked_update_order.mock_calls[1].kwargs == {
        "parameters": {
            "fulfillment": fulfillment_parameters_factory(
                customer_id="a-client-id",
                retry_count="1",
            ),
            "ordering": order_parameters_factory(),
        },
    }


def test_create_customer_fails(
    mocker,
    order_factory,
):
    """
    Tests the processing of a purchase order. It fails on customer creation no
    order will be placed.
    """
    mocked_create_customer_account = mocker.patch(
        "adobe_vipm.flows.fulfillment.purchase.create_customer_account",
        return_value=None,
    )
    mocked_adobe_client = mocker.MagicMock()
    mocker.patch(
        "adobe_vipm.flows.fulfillment.purchase.get_adobe_client",
        return_value=mocked_adobe_client,
    )
    mocked_mpt_client = mocker.MagicMock()

    order = order_factory()

    fulfill_order(mocked_mpt_client, order)

    mocked_create_customer_account.assert_called_once()
    mocked_adobe_client.create_preview_order.assert_not_called()
    mocked_adobe_client.create_new_order.assert_not_called()


def test_create_adobe_preview_order_error(
    mocker,
    order_factory,
    fulfillment_parameters_factory,
    adobe_api_error_factory,
):
    """
    Tests the processing of a purchase order. It fails on adobe preview
    order creation. The purchase order will be failed.
    """
    mocker.patch(
        "adobe_vipm.flows.fulfillment.purchase.create_customer_account",
        return_value=None,
    )

    adobe_error = AdobeError(
        adobe_api_error_factory("9999", "Error while creating a preview order")
    )

    mocked_adobe_client = mocker.MagicMock()
    mocked_adobe_client.create_preview_order.side_effect = adobe_error
    mocker.patch(
        "adobe_vipm.flows.fulfillment.purchase.get_adobe_client",
        return_value=mocked_adobe_client,
    )

    mocked_fail_order = mocker.patch("adobe_vipm.flows.fulfillment.shared.fail_order")

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


def test_customer_and_order_already_created_adobe_order_not_ready(
    mocker,
    order_factory,
    order_parameters_factory,
    fulfillment_parameters_factory,
):
    """
    Tests the continuation of processing a purchase order since in the
    previous attemp the order has been created but not yet processed
    on Adobe side. The RetryCount fullfilment paramter must be incremented.
    The purchase order will not be completed and the processing will be stopped.
    """
    mocked_update_order = mocker.patch(
        "adobe_vipm.flows.fulfillment.shared.update_order",
    )
    mocked_complete_order = mocker.patch(
        "adobe_vipm.flows.fulfillment.shared.complete_order",
    )
    mocked_adobe_client = mocker.MagicMock()
    mocked_adobe_client.get_order.return_value = {"status": "1002"}
    mocker.patch(
        "adobe_vipm.flows.fulfillment.purchase.get_adobe_client",
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

    mocked_adobe_client.get_subscription.assert_not_called()
    mocked_update_order.assert_called_once_with(
        mocked_mpt_client,
        order["id"],
        parameters={
            "ordering": order_parameters_factory(),
            "fulfillment": fulfillment_parameters_factory(
                customer_id="a-client-id",
                retry_count="1",
            ),
        },
    )
    mocked_complete_order.assert_not_called()


def test_customer_already_created_order_already_created_max_retries_reached(
    mocker,
    order_factory,
    fulfillment_parameters_factory,
):
    """
    Tests the processing of a purchase order when the allowed maximum number of
    attemps has been reached.
    The order will be failed with a message saying that this maximum has been reached.
    """
    mocked_fail_order = mocker.patch(
        "adobe_vipm.flows.fulfillment.shared.fail_order",
    )
    mocked_adobe_client = mocker.MagicMock()
    mocked_adobe_client.get_order.return_value = {"status": "1002"}
    mocker.patch(
        "adobe_vipm.flows.fulfillment.purchase.get_adobe_client",
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

    mocked_adobe_client.get_subscription.assert_not_called()
    mocked_fail_order.assert_called_once_with(
        mocked_mpt_client,
        order["id"],
        "Max processing attemps reached (10).",
    )


@pytest.mark.parametrize(
    "order_status",
    UNRECOVERABLE_ORDER_STATUSES,
)
def test_customer_already_created_order_already_created_unrecoverable_status(
    mocker,
    order_factory,
    fulfillment_parameters_factory,
    order_status,
):
    """
    Tests the processing of a purchase order when the Adobe order has been processed unsuccessfully.
    The purchase order will be failed and with a message that describe the error returned by Adobe.
    """
    mocked_fail_order = mocker.patch(
        "adobe_vipm.flows.fulfillment.shared.fail_order",
    )
    mocked_adobe_client = mocker.MagicMock()
    mocked_adobe_client.get_order.return_value = {"status": order_status}
    mocker.patch(
        "adobe_vipm.flows.fulfillment.purchase.get_adobe_client",
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

    mocked_adobe_client.get_subscription.assert_not_called()
    mocked_fail_order.assert_called_once_with(
        mocked_mpt_client,
        order["id"],
        ORDER_STATUS_DESCRIPTION[order_status],
    )


def test_customer_already_created_order_already_created_unexpected_status(
    mocker,
    order_factory,
    fulfillment_parameters_factory,
):
    """
    Tests the processing of a purchase order when the Adobe order has been processed unsuccessfully
    and the status of the order returned by Adobe is not documented.
    The purchase order will be failed and with a message that explain that Adobe returned an
    unexpected error.
    """
    mocked_fail_order = mocker.patch(
        "adobe_vipm.flows.fulfillment.shared.fail_order",
    )
    mocked_adobe_client = mocker.MagicMock()
    mocked_adobe_client.get_order.return_value = {"status": "9999"}
    mocker.patch(
        "adobe_vipm.flows.fulfillment.purchase.get_adobe_client",
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

    mocked_adobe_client.get_subscription.assert_not_called()
    mocked_fail_order.assert_called_once_with(
        mocked_mpt_client,
        order["id"],
        "Unexpected status (9999) received from Adobe.",
    )


def test_create_customer_account(
    mocker,
    order,
    order_parameters_factory,
    fulfillment_parameters_factory,
):
    """
    Test create a customer account in Adobe.
    Customer data is available as ordering parameters.
    """
    mocked_adobe_client = mocker.MagicMock()
    mocked_adobe_client.create_customer_account.return_value = {
        "customerId": "adobe-customer-id",
    }
    mocked_mpt_client = mocker.MagicMock()
    mocker.patch(
        "adobe_vipm.flows.fulfillment.purchase.get_adobe_client",
        return_value=mocked_adobe_client,
    )
    mocked_update_agreement = mocker.patch(
        "adobe_vipm.flows.fulfillment.shared.update_agreement",
    )
    mocked_update_order = mocker.patch(
        "adobe_vipm.flows.fulfillment.shared.update_order",
        return_value=copy.deepcopy(order),
    )
    order = set_adobe_customer_id(order, "adobe-customer-id")

    updated_order = create_customer_account(
        mocked_mpt_client,
        order,
    )

    mocked_adobe_client.create_customer_account.assert_called_once_with(
        order["authorization"]["id"],
        order["agreement"]["seller"]["id"],
        order["agreement"]["id"],
        {
            param["externalId"]: param.get("value")
            for param in order_parameters_factory()
            if param["externalId"] not in (PARAM_MEMBERSHIP_ID, PARAM_AGREEMENT_TYPE)
        },
    )

    mocked_update_order.assert_called_once_with(
        mocked_mpt_client,
        order["id"],
        parameters={
            "ordering": order_parameters_factory(),
            "fulfillment": fulfillment_parameters_factory(
                customer_id="adobe-customer-id"
            ),
        },
    )
    mocked_update_agreement.assert_called_once_with(
        mocked_mpt_client,
        order["agreement"]["id"],
        externalIds={"vendor": "adobe-customer-id"},
    )
    assert updated_order == order


def test_create_customer_account_empty_order_parameters(
    mocker,
    order,
    order_parameters_factory,
    fulfillment_parameters_factory,
):
    """
    Test create a customer account in Adobe.
    Customer data must be taken getting the buyer associated with the order.
    """
    mocked_adobe_client = mocker.MagicMock()
    mocked_adobe_client.create_customer_account.return_value = {
        "customerId": "adobe-customer-id",
    }
    mocked_mpt_client = mocker.MagicMock()
    mocker.patch(
        "adobe_vipm.flows.fulfillment.purchase.get_adobe_client",
        return_value=mocked_adobe_client,
    )
    mocked_update_order_customer_id = mocker.patch(
        "adobe_vipm.flows.fulfillment.shared.update_order",
        return_value=copy.deepcopy(order),
    )

    mocked_update_order_customer_params = mocker.patch(
        "adobe_vipm.flows.helpers.update_order",
        return_value=copy.deepcopy(order),
    )

    order["parameters"]["ordering"] = order_parameters_factory(
        company_name="",
        address={},
        contact={},
    )

    create_customer_account(mocked_mpt_client, order)

    mocked_adobe_client.create_customer_account.assert_called_once_with(
        order["authorization"]["id"],
        order["agreement"]["seller"]["id"],
        order["agreement"]["id"],
        {
            param["externalId"]: param.get("value")
            for param in order_parameters_factory()
            if param["externalId"] not in (PARAM_MEMBERSHIP_ID, PARAM_AGREEMENT_TYPE)
        },
    )

    mocked_update_order_customer_params.assert_called_once_with(
        mocked_mpt_client,
        order["id"],
        parameters={
            "ordering": order_parameters_factory(),
            "fulfillment": fulfillment_parameters_factory(),
        },
    )

    mocked_update_order_customer_id.assert_called_once_with(
        mocked_mpt_client,
        order["id"],
        parameters={
            "ordering": order_parameters_factory(),
            "fulfillment": fulfillment_parameters_factory(
                customer_id="adobe-customer-id"
            ),
        },
    )


def test_create_customer_account_address_error(
    mocker,
    order,
    order_parameters_factory,
    fulfillment_parameters_factory,
    adobe_api_error_factory,
):
    """
    Test address validation error handling when create a customer account in Adobe.
    """
    mocker.patch(
        "adobe_vipm.flows.fulfillment.shared.get_product_template_or_default",
        return_value={"id": "TPL-0000"},
    )
    mocked_adobe_client = mocker.MagicMock()
    adobe_error = AdobeAPIError(
        400,
        adobe_api_error_factory(
            code=STATUS_INVALID_ADDRESS,
            message="Invalid address",
            details=["detail1", "detail2"],
        ),
    )
    mocked_adobe_client.create_customer_account.side_effect = adobe_error
    mocked_mpt_client = mocker.MagicMock()
    mocker.patch(
        "adobe_vipm.flows.fulfillment.purchase.get_adobe_client",
        return_value=mocked_adobe_client,
    )
    mocked_query_order = mocker.patch(
        "adobe_vipm.flows.fulfillment.shared.query_order",
        return_value=copy.deepcopy(order),
    )

    updated_order = create_customer_account(
        mocked_mpt_client,
        order,
    )

    ordering_parameters = order_parameters_factory()
    address_param = next(filter(lambda x: x["name"] == "Address", ordering_parameters))
    address_param["error"] = ERR_ADOBE_ADDRESS.to_dict(
        title=address_param["name"],
        details=str(adobe_error),
    )
    address_param["constraints"] = {
        "hidden": False,
        "required": True,
    }
    mocked_query_order.assert_called_once_with(
        mocked_mpt_client,
        order["id"],
        parameters={
            "ordering": ordering_parameters,
            "fulfillment": fulfillment_parameters_factory(),
        },
        template={"id": "TPL-0000"},
    )
    assert updated_order is None


@pytest.mark.parametrize(
    ("param_external_id", "error_constant", "error_details"),
    [
        ("contact", ERR_ADOBE_CONTACT, "companyProfile.contacts[0].firstName"),
        ("companyName", ERR_ADOBE_COMPANY_NAME, "companyProfile.companyName"),
    ],
)
def test_create_customer_account_fields_error(
    mocker,
    order,
    order_parameters_factory,
    fulfillment_parameters_factory,
    adobe_api_error_factory,
    param_external_id,
    error_constant,
    error_details,
):
    """
    Test fields validation error handling when create a customer account in Adobe.
    """
    mocked_get_template = mocker.patch(
        "adobe_vipm.flows.fulfillment.shared.get_product_template_or_default",
        return_value={"id": "TPL-0000"},
    )

    mocked_adobe_client = mocker.MagicMock()
    adobe_error = AdobeAPIError(
        400,
        adobe_api_error_factory(
            code=STATUS_INVALID_FIELDS,
            message="Invalid fields",
            details=[error_details],
        ),
    )
    mocked_adobe_client.create_customer_account.side_effect = adobe_error
    mocked_mpt_client = mocker.MagicMock()
    mocker.patch(
        "adobe_vipm.flows.fulfillment.purchase.get_adobe_client",
        return_value=mocked_adobe_client,
    )
    mocked_query_order = mocker.patch(
        "adobe_vipm.flows.fulfillment.shared.query_order",
        return_value=copy.deepcopy(order),
    )

    updated_order = create_customer_account(
        mocked_mpt_client,
        order,
    )

    ordering_parameters = order_parameters_factory()
    param = next(
        filter(lambda x: x["externalId"] == param_external_id, ordering_parameters)
    )
    param["error"] = error_constant.to_dict(
        title=param["name"],
        details=str(adobe_error),
    )
    param["constraints"] = {
        "hidden": False,
        "required": True,
    }
    mocked_query_order.assert_called_once_with(
        mocked_mpt_client,
        order["id"],
        parameters={
            "ordering": ordering_parameters,
            "fulfillment": fulfillment_parameters_factory(),
        },
        template={"id": "TPL-0000"},
    )

    mocked_get_template.assert_called_once_with(
        mocked_mpt_client,
        mocker.ANY,
        MPT_ORDER_STATUS_QUERYING,
    )

    assert updated_order is None


def test_create_customer_account_other_error(
    mocker,
    order,
    adobe_api_error_factory,
):
    """
    Test unrecoverable error handling when create a customer account in Adobe.
    """
    mocked_adobe_client = mocker.MagicMock()
    adobe_error = AdobeAPIError(
        400,
        adobe_api_error_factory(
            code=STATUS_ACCOUNT_ALREADY_EXISTS,
            message="Account already exists.",
        ),
    )
    mocked_adobe_client.create_customer_account.side_effect = adobe_error
    mocked_mpt_client = mocker.MagicMock()
    mocker.patch(
        "adobe_vipm.flows.fulfillment.purchase.get_adobe_client",
        return_value=mocked_adobe_client,
    )
    mocked_fail_order = mocker.patch(
        "adobe_vipm.flows.fulfillment.shared.fail_order",
        return_value=copy.deepcopy(order),
    )

    updated_order = create_customer_account(
        mocked_mpt_client,
        order,
    )

    mocked_fail_order.assert_called_once_with(
        mocked_mpt_client,
        order["id"],
        str(adobe_error),
    )
    assert updated_order is None


def test_create_customer_account_3yc(
    mocker,
    order_factory,
    order_parameters_factory,
    fulfillment_parameters_factory,
):
    """
    Test create a customer account in Adobe with 3YC.
    Customer data is available as ordering parameters.
    """
    mocked_adobe_client = mocker.MagicMock()
    mocked_adobe_client.create_customer_account.return_value = {
        "customerId": "adobe-customer-id",
        "benefits": [
            {
                "type": "THREE_YEAR_COMMIT",
                "commitmentRequest": {
                    "status": "REQUESTED",
                },
            },
        ],
    }

    order = order_factory(
        order_parameters=order_parameters_factory(
            p3yc=["Yes"],
            p3yc_licenses=10,
        ),
    )

    mocked_mpt_client = mocker.MagicMock()
    mocker.patch(
        "adobe_vipm.flows.fulfillment.purchase.get_adobe_client",
        return_value=mocked_adobe_client,
    )
    mocked_update_order = mocker.patch(
        "adobe_vipm.flows.fulfillment.shared.update_order",
        return_value=copy.deepcopy(order),
    )

    updated_order = create_customer_account(
        mocked_mpt_client,
        order,
    )

    mocked_adobe_client.create_customer_account.assert_called_once_with(
        order["authorization"]["id"],
        order["agreement"]["seller"]["id"],
        order["agreement"]["id"],
        {
            param["externalId"]: param.get("value")
            for param in order_parameters_factory(p3yc=["Yes"], p3yc_licenses=10)
            if param["externalId"] not in (PARAM_MEMBERSHIP_ID, PARAM_AGREEMENT_TYPE)
        },
    )

    mocked_update_order.assert_called_once_with(
        mocked_mpt_client,
        order["id"],
        parameters={
            "ordering": order_parameters_factory(p3yc=["Yes"], p3yc_licenses=10),
            "fulfillment": fulfillment_parameters_factory(
                customer_id="adobe-customer-id",
                p3yc_commitment_request_status="REQUESTED",
            ),
        },
    )

    assert updated_order == order_factory(
        order_parameters=order_parameters_factory(
            p3yc=["Yes"],
            p3yc_licenses=10,
        ),
        fulfillment_parameters=fulfillment_parameters_factory(
            customer_id="adobe-customer-id",
            p3yc_commitment_request_status="REQUESTED",
        ),
    )


def test_create_customer_account_3yc_minimum_error(
    mocker,
    order,
    order_parameters_factory,
    fulfillment_parameters_factory,
    adobe_api_error_factory,
):
    mocker.patch(
        "adobe_vipm.flows.fulfillment.shared.get_product_template_or_default",
        return_value={"id": "TPL-0000"},
    )

    mocked_adobe_client = mocker.MagicMock()
    adobe_error = AdobeAPIError(
        400,
        adobe_api_error_factory(
            code=STATUS_INVALID_MINIMUM_QUANTITY,
            message="Minimum quantity out of range",
            details=["LICENSE", "CONSUMABLES"],
        ),
    )
    mocked_adobe_client.create_customer_account.side_effect = adobe_error
    mocked_mpt_client = mocker.MagicMock()
    mocker.patch(
        "adobe_vipm.flows.fulfillment.purchase.get_adobe_client",
        return_value=mocked_adobe_client,
    )
    mocked_query_order = mocker.patch(
        "adobe_vipm.flows.fulfillment.shared.query_order",
        return_value=copy.deepcopy(order),
    )

    updated_order = create_customer_account(
        mocked_mpt_client,
        order,
    )

    ordering_parameters = order_parameters_factory()
    consumables_param = next(
        filter(lambda x: x["externalId"] == PARAM_3YC_CONSUMABLES, ordering_parameters)
    )
    consumables_param["error"] = ERR_3YC_QUANTITY_CONSUMABLES.to_dict(
        title=consumables_param["name"],
    )
    consumables_param["constraints"] = {
        "hidden": False,
        "required": False,
    }
    licenses_param = next(
        filter(lambda x: x["externalId"] == PARAM_3YC_LICENSES, ordering_parameters)
    )
    licenses_param["error"] = ERR_3YC_QUANTITY_LICENSES.to_dict(
        title=licenses_param["name"],
    )
    licenses_param["constraints"] = {
        "hidden": False,
        "required": False,
    }

    mocked_query_order.assert_called_once_with(
        mocked_mpt_client,
        order["id"],
        parameters={
            "ordering": ordering_parameters,
            "fulfillment": fulfillment_parameters_factory(),
        },
        template={"id": "TPL-0000"},
    )
    assert updated_order is None


def test_create_customer_account_3yc_empty_minimums(
    mocker,
    order,
    adobe_api_error_factory,
):
    mocker.patch(
        "adobe_vipm.flows.fulfillment.shared.get_product_template_or_default",
        return_value={"id": "TPL-0000"},
    )
    mocked_adobe_client = mocker.MagicMock()
    adobe_error = AdobeAPIError(
        400,
        adobe_api_error_factory(
            code=STATUS_INVALID_MINIMUM_QUANTITY,
            message="Minimum quantity out of range",
            details=[],
        ),
    )
    mocked_adobe_client.create_customer_account.side_effect = adobe_error
    mocked_mpt_client = mocker.MagicMock()
    mocker.patch(
        "adobe_vipm.flows.fulfillment.purchase.get_adobe_client",
        return_value=mocked_adobe_client,
    )
    mocked_query_order = mocker.patch(
        "adobe_vipm.flows.fulfillment.shared.query_order",
        return_value=copy.deepcopy(order),
    )

    updated_order = create_customer_account(
        mocked_mpt_client,
        order,
    )

    param_licenses = get_ordering_parameter(order, PARAM_3YC_LICENSES)
    param_consumables = get_ordering_parameter(order, PARAM_3YC_CONSUMABLES)

    mocked_query_order.assert_called_once_with(
        mocked_mpt_client,
        order["id"],
        error=ERR_3YC_NO_MINIMUMS.to_dict(
            title_min_licenses=param_licenses["name"],
            title_min_consumables=param_consumables["name"],
        ),
        parameters=order["parameters"],
        template={"id": "TPL-0000"},
    )
    assert updated_order is None


def test_create_customer_account_from_licensee(
    mocker,
    agreement_factory,
    order,
    order_parameters_factory,
    fulfillment_parameters_factory,
):
    mocked_adobe_client = mocker.MagicMock()
    mocked_adobe_client.create_customer_account.return_value = {
        "customerId": "adobe-customer-id",
    }
    mocked_mpt_client = mocker.MagicMock()
    mocker.patch(
        "adobe_vipm.flows.fulfillment.purchase.get_adobe_client",
        return_value=mocked_adobe_client,
    )
    mocked_update_order_customer_id = mocker.patch(
        "adobe_vipm.flows.fulfillment.shared.update_order",
        return_value=copy.deepcopy(order),
    )

    mocked_update_order_customer_params = mocker.patch(
        "adobe_vipm.flows.helpers.update_order",
        return_value=copy.deepcopy(order),
    )

    address = {
        "country": "US",
        "state": "CA",
        "city": "New York",
        "addressLine1": "3601 Fifth Av",
        "addressLine2": "",
        "postCode": "94123",
    }

    contact = {
        "firstName": "Ringo",
        "lastName": "Mania",
        "email": "ringo.mania@scarafaggi.com",
        "phone": {
            "prefix": "+1",
            "number": "4082954078",
        },
    }

    order["agreement"] = agreement_factory(
        licensee_address=address,
        licensee_contact=contact,
    )

    order["parameters"]["ordering"] = order_parameters_factory(
        company_name="",
        address={},
        contact={},
    )

    create_customer_account(mocked_mpt_client, order)

    mocked_adobe_client.create_customer_account.assert_called_once_with(
        order["authorization"]["id"],
        order["agreement"]["seller"]["id"],
        order["agreement"]["id"],
        {
            param["externalId"]: param.get("value")
            for param in order_parameters_factory(
                company_name=order["agreement"]["licensee"]["name"],
                address=address,
                contact=contact,
            )
            if param["externalId"] not in (PARAM_MEMBERSHIP_ID, PARAM_AGREEMENT_TYPE)
        },
    )

    mocked_update_order_customer_params.assert_called_once_with(
        mocked_mpt_client,
        order["id"],
        parameters={
            "ordering": order_parameters_factory(
                company_name=order["agreement"]["licensee"]["name"],
                address=address,
                contact=contact,
            ),
            "fulfillment": fulfillment_parameters_factory(),
        },
    )

    mocked_update_order_customer_id.assert_called_once_with(
        mocked_mpt_client,
        order["id"],
        parameters={
            "ordering": order_parameters_factory(
                company_name=order["agreement"]["licensee"]["name"],
                address=address,
                contact=contact,
            ),
            "fulfillment": fulfillment_parameters_factory(
                customer_id="adobe-customer-id"
            ),
        },
    )


def test_create_customer_account_no_contact(
    mocker,
    order,
    order_parameters_factory,
    fulfillment_parameters_factory,
):
    mocker.patch(
        "adobe_vipm.flows.fulfillment.shared.get_product_template_or_default",
        return_value={"id": "TPL-0000"},
    )
    mocked_adobe_client = mocker.MagicMock()

    mocked_mpt_client = mocker.MagicMock()
    mocker.patch(
        "adobe_vipm.flows.fulfillment.purchase.get_adobe_client",
        return_value=mocked_adobe_client,
    )
    mocked_query_order = mocker.patch(
        "adobe_vipm.flows.fulfillment.shared.query_order",
        return_value=copy.deepcopy(order),
    )

    order["agreement"]["licensee"]["contact"] = None
    get_ordering_parameter(order, PARAM_CONTACT)["value"] = {}

    updated_order = create_customer_account(
        mocked_mpt_client,
        order,
    )

    ordering_params = order_parameters_factory()
    contact_param = get_ordering_parameter(
        {"parameters": {"ordering": ordering_params}}, PARAM_CONTACT
    )
    contact_param["value"] = {}
    contact_param["error"] =  ERR_ADOBE_CONTACT.to_dict(
        title=contact_param["name"],
        details="it is mandatory.",
    )

    mocked_query_order.assert_called_once_with(
        mocked_mpt_client,
        order["id"],
        parameters={
            "ordering": ordering_params,
            "fulfillment": fulfillment_parameters_factory(),
        },
        template={"id": "TPL-0000"},
    )
    assert updated_order is None
