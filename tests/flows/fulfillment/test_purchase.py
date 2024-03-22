import copy

import pytest

from adobe_vipm.adobe.constants import (
    ORDER_STATUS_DESCRIPTION,
    ORDER_TYPE_NEW,
    ORDER_TYPE_PREVIEW,
    STATUS_ACCOUNT_ALREADY_EXISTS,
    STATUS_INVALID_ADDRESS,
    STATUS_INVALID_FIELDS,
    STATUS_PENDING,
    STATUS_PROCESSED,
    UNRECOVERABLE_ORDER_STATUSES,
)
from adobe_vipm.adobe.errors import AdobeAPIError, AdobeError
from adobe_vipm.flows.constants import (
    ERR_ADOBE_ADDRESS,
    ERR_ADOBE_COMPANY_NAME,
    ERR_ADOBE_CONTACT,
    ERR_ADOBE_PREFERRED_LANGUAGE,
)
from adobe_vipm.flows.fulfillment import fulfill_order
from adobe_vipm.flows.fulfillment.purchase import create_customer_account
from adobe_vipm.flows.utils import set_adobe_customer_id


def test_no_customer(
    mocker,
    settings,
    buyer,
    seller,
    agreement,
    order_factory,
    order_parameters_factory,
    fulfillment_parameters_factory,
    adobe_order_factory,
    adobe_items_factory,
    adobe_subscription_factory,
    items_factory,
    subscriptions_factory,
):
    """
    Tests the processing of a purchase order including:
        * customer creation
        * order creation
        * subscription creation
        * order completion
    """

    settings.EXTENSION_CONFIG["COMPLETED_TEMPLATE_ID"] = "TPL-1111"

    mocker.patch("adobe_vipm.flows.helpers.get_agreement", return_value=agreement)
    mocker.patch("adobe_vipm.flows.fulfillment.purchase.get_buyer", return_value=buyer)
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
        ],
    )
    subscription = subscriptions_factory()[0]
    mocked_create_subscription = mocker.patch(
        "adobe_vipm.flows.fulfillment.shared.create_subscription",
        return_value=subscription,
    )
    mocker.patch(
        "adobe_vipm.flows.fulfillment.shared.get_product_items_by_skus",
        return_value=items_factory(),
    )
    mocker.patch(
        "adobe_vipm.flows.fulfillment.shared.get_pricelist_item_by_product_item",
        return_value={
            "unitPP": 200.12,
        },
    )
    mocked_update_subscription = mocker.patch(
        "adobe_vipm.flows.fulfillment.shared.update_subscription",
    )
    mocked_complete_order = mocker.patch(
        "adobe_vipm.flows.fulfillment.shared.complete_order",
    )

    order = order_factory()
    order_with_customer_param = order_factory(
        fulfillment_parameters=fulfillment_parameters_factory(customer_id="a-client-id")
    )

    fulfill_order(mocked_mpt_client, order)

    seller_country = seller["address"]["country"]

    mocked_create_customer_account.assert_called_once_with(
        mocked_mpt_client,
        seller_country,
        buyer,
        order,
    )
    mocked_adobe_client.create_preview_order.assert_called_once_with(
        seller_country,
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
            ),
            "ordering": order_parameters_factory(),
        },
    }
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
        },
    )
    mocked_update_subscription.assert_called_once_with(
        mocked_mpt_client,
        order["id"],
        subscription["id"],
        parameters={
            "fulfillment": [
                {
                    "externalId": "adobeSKU",
                    "value": adobe_subscription["offerId"],
                },
            ],
        },
        price={
            "unitPP": 200.12,
        },
    )
    mocked_complete_order.assert_called_once_with(
        mocked_mpt_client,
        order["id"],
        "TPL-1111",
    )
    mocked_adobe_client.get_order.assert_called_once_with(
        seller_country, "a-client-id", adobe_order["orderId"]
    )
    mocked_adobe_client.get_subscription.assert_called_once_with(
        seller_country,
        "a-client-id",
        adobe_subscription["subscriptionId"],
    )


def test_customer_already_created(
    mocker,
    seller,
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

    seller_country = seller["address"]["country"]

    mocked_create_customer_account.assert_not_called()
    mocked_adobe_client.create_preview_order.assert_called_once_with(
        seller_country,
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
    seller,
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
    seller,
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
    seller,
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
    buyer,
    order,
    order_parameters_factory,
    fulfillment_parameters_factory,
):
    """
    Test create a customer account in Adobe.
    Customer data is available as ordering parameters.
    """
    mocked_adobe_client = mocker.MagicMock()
    mocked_adobe_client.create_customer_account.return_value = "adobe-customer-id"
    mocked_mpt_client = mocker.MagicMock()
    mocker.patch(
        "adobe_vipm.flows.fulfillment.purchase.get_adobe_client",
        return_value=mocked_adobe_client,
    )
    mocked_update_order = mocker.patch(
        "adobe_vipm.flows.fulfillment.shared.update_order",
        return_value=copy.deepcopy(order),
    )
    order = set_adobe_customer_id(order, "adobe-customer-id")

    updated_order = create_customer_account(
        mocked_mpt_client,
        "US",
        buyer,
        order,
    )

    mocked_adobe_client.create_customer_account.assert_called_once_with(
        "US",
        order["agreement"]["id"],
        {param["externalId"]: param["value"] for param in order_parameters_factory()},
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
    assert updated_order == order


def test_create_customer_account_empty_order_parameters(
    mocker,
    buyer,
    order,
    order_parameters_factory,
    fulfillment_parameters_factory,
):
    """
    Test create a customer account in Adobe.
    Customer data must be taken getting the buyer associated with the order.
    """
    mocked_adobe_client = mocker.MagicMock()
    mocked_adobe_client.create_customer_account.return_value = "adobe-customer-id"
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
        preferred_language="",
        address={},
        contact={},
    )

    create_customer_account(
        mocked_mpt_client,
        "US",
        buyer,
        order,
    )

    mocked_adobe_client.create_customer_account.assert_called_once_with(
        "US",
        order["agreement"]["id"],
        {param["externalId"]: param["value"] for param in order_parameters_factory()},
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
    buyer,
    order,
    order_parameters_factory,
    fulfillment_parameters_factory,
    adobe_api_error_factory,
    settings,
):
    """
    Test address validation error handling when create a customer account in Adobe.
    """
    settings.EXTENSION_CONFIG["QUERYING_TEMPLATE_ID"] = "TPL-0000"
    mocked_adobe_client = mocker.MagicMock()
    adobe_error = AdobeAPIError(
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
        "US",
        buyer,
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
        "optional": False,
    }
    mocked_query_order.assert_called_once_with(
        mocked_mpt_client,
        order["id"],
        parameters={
            "ordering": ordering_parameters,
            "fulfillment": fulfillment_parameters_factory(),
        },
        templateId="TPL-0000",
    )
    assert updated_order is None


@pytest.mark.parametrize(
    ("param_external_id", "error_constant", "error_details"),
    [
        ("contact", ERR_ADOBE_CONTACT, "companyProfile.contacts[0].firstName"),
        ("companyName", ERR_ADOBE_COMPANY_NAME, "companyProfile.companyName"),
        (
            "preferredLanguage",
            ERR_ADOBE_PREFERRED_LANGUAGE,
            "companyProfile.preferredLanguage",
        ),
    ],
)
def test_create_customer_account_fields_error(
    mocker,
    buyer,
    order,
    order_parameters_factory,
    fulfillment_parameters_factory,
    adobe_api_error_factory,
    settings,
    param_external_id,
    error_constant,
    error_details,
):
    """
    Test fields validation error handling when create a customer account in Adobe.
    """
    settings.EXTENSION_CONFIG["QUERYING_TEMPLATE_ID"] = "TPL-0000"
    mocked_adobe_client = mocker.MagicMock()
    adobe_error = AdobeAPIError(
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
        "US",
        buyer,
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
        "optional": False,
    }
    mocked_query_order.assert_called_once_with(
        mocked_mpt_client,
        order["id"],
        parameters={
            "ordering": ordering_parameters,
            "fulfillment": fulfillment_parameters_factory(),
        },
        templateId="TPL-0000",
    )
    assert updated_order is None


def test_create_customer_account_other_error(
    mocker,
    buyer,
    order,
    adobe_api_error_factory,
):
    """
    Test unrecoverable error handling when create a customer account in Adobe.
    """
    mocked_adobe_client = mocker.MagicMock()
    adobe_error = AdobeAPIError(
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
        "US",
        buyer,
        order,
    )

    mocked_fail_order.assert_called_once_with(
        mocked_mpt_client,
        order["id"],
        str(adobe_error),
    )
    assert updated_order is None
