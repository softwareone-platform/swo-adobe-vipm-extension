import pytest

from adobe_vipm.adobe.constants import (
    STATUS_PENDING,
    STATUS_PROCESSED,
    STATUS_TRANSFER_INVALID_MEMBERSHIP,
    STATUS_TRANSFER_INVALID_MEMBERSHIP_OR_TRANSFER_IDS,
    UNRECOVERABLE_TRANSFER_STATUSES,
)
from adobe_vipm.adobe.errors import AdobeAPIError, AdobeError
from adobe_vipm.flows.constants import ERR_ADOBE_MEMBERSHIP_ID, PARAM_MEMBERSHIP_ID
from adobe_vipm.flows.fulfillment import fulfill_order
from adobe_vipm.flows.utils import get_ordering_parameter, set_ordering_parameter_error


def test_transfer(
    mocker,
    settings,
    seller,
    agreement,
    order_factory,
    transfer_order_parameters_factory,
    fulfillment_parameters_factory,
    adobe_preview_transfer_factory,
    adobe_transfer_factory,
    adobe_items_factory,
    adobe_subscription_factory,
):
    """
    Tests the processing of a transfer order including:
        * order creation
        * subscription creation
        * order completion
    """

    settings.EXTENSION_CONFIG["COMPLETED_TEMPLATE_ID"] = "TPL-1111"

    mocker.patch("adobe_vipm.flows.shared.get_agreement", return_value=agreement)

    adobe_transfer = adobe_transfer_factory(
        status=STATUS_PROCESSED,
        customer_id="a-client-id",
        items=adobe_items_factory(subscription_id="a-sub-id"),
    )

    adobe_transfer_preview = adobe_preview_transfer_factory()

    adobe_subscription = adobe_subscription_factory()

    mocked_adobe_client = mocker.MagicMock()
    mocked_adobe_client.preview_transfer.return_value = adobe_transfer_preview
    mocked_adobe_client.create_transfer.return_value = adobe_transfer
    mocked_adobe_client.get_transfer.return_value = adobe_transfer
    mocked_adobe_client.get_subscription.return_value = adobe_subscription
    mocker.patch(
        "adobe_vipm.flows.fulfillment.get_adobe_client",
        return_value=mocked_adobe_client,
    )

    mocked_mpt_client = mocker.MagicMock()
    mocked_update_order = mocker.patch("adobe_vipm.flows.fulfillment.update_order")
    mocked_create_subscription = mocker.patch(
        "adobe_vipm.flows.fulfillment.create_subscription"
    )
    mocked_complete_order = mocker.patch("adobe_vipm.flows.fulfillment.complete_order")

    order = order_factory(order_parameters=transfer_order_parameters_factory())

    fulfill_order(mocked_mpt_client, order)

    seller_country = seller["address"]["country"]

    mocked_adobe_client.preview_transfer.assert_called_once_with(
        seller_country,
        "a-membership-id",
    )

    assert mocked_update_order.mock_calls[0].args == (
        mocked_mpt_client,
        order["id"],
    )
    assert mocked_update_order.mock_calls[0].kwargs == {
        "externalIds": {
            "vendor": adobe_transfer["transferId"],
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
            "ordering": transfer_order_parameters_factory(),
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
    mocked_complete_order.assert_called_once_with(
        mocked_mpt_client,
        order["id"],
        "TPL-1111",
    )
    mocked_adobe_client.get_transfer.assert_called_once_with(
        seller_country, "a-membership-id", adobe_transfer["transferId"]
    )
    mocked_adobe_client.get_subscription.assert_called_once_with(
        seller_country,
        "a-client-id",
        adobe_subscription["subscriptionId"],
    )


def test_transfer_not_ready(
    mocker,
    seller,
    agreement,
    order_factory,
    transfer_order_parameters_factory,
    fulfillment_parameters_factory,
    adobe_transfer_factory,
):
    """
    Tests the continuation of processing a transfer order since in the
    previous attemp the order has been created but not yet processed
    on Adobe side. The RetryCount fullfilment paramter must be incremented.
    The transfer order will not be completed and the processing will be stopped.
    """
    mocker.patch("adobe_vipm.flows.shared.get_agreement", return_value=agreement)

    adobe_transfer = adobe_transfer_factory(status=STATUS_PENDING)

    mocked_adobe_client = mocker.MagicMock()
    mocked_adobe_client.create_transfer.return_value = adobe_transfer
    mocked_adobe_client.get_transfer.return_value = adobe_transfer
    mocker.patch(
        "adobe_vipm.flows.fulfillment.get_adobe_client",
        return_value=mocked_adobe_client,
    )

    mocked_mpt_client = mocker.MagicMock()
    mocked_update_order = mocker.patch("adobe_vipm.flows.fulfillment.update_order")
    mocked_complete_order = mocker.patch("adobe_vipm.flows.fulfillment.complete_order")

    order = order_factory(
        order_parameters=transfer_order_parameters_factory(),
        external_ids={"vendor": "a-transfer-id"},
    )

    fulfill_order(mocked_mpt_client, order)

    seller_country = seller["address"]["country"]

    assert mocked_update_order.mock_calls[0].args == (
        mocked_mpt_client,
        order["id"],
    )
    assert mocked_update_order.mock_calls[0].kwargs == {
        "parameters": {
            "fulfillment": fulfillment_parameters_factory(
                retry_count="1",
            ),
            "ordering": transfer_order_parameters_factory(),
        },
    }

    mocked_complete_order.assert_not_called()
    mocked_adobe_client.get_transfer.assert_called_once_with(
        seller_country, "a-membership-id", adobe_transfer["transferId"]
    )


def test_transfer_unexpected_status(
    mocker,
    seller,
    agreement,
    order_factory,
    transfer_order_parameters_factory,
    fulfillment_parameters_factory,
    adobe_transfer_factory,
):
    """
    Tests the processing of a transfer order when the Adobe transfer has been processed
    unsuccessfully and the status of the transfer returned by Adobe is not documented.
    The transfer order will be failed with a message that explain that Adobe returned an
    unexpected error.
    """
    mocker.patch("adobe_vipm.flows.shared.get_agreement", return_value=agreement)

    adobe_transfer = adobe_transfer_factory(status="9999")

    mocked_adobe_client = mocker.MagicMock()
    mocked_adobe_client.create_transfer.return_value = adobe_transfer
    mocked_adobe_client.get_transfer.return_value = adobe_transfer
    mocker.patch(
        "adobe_vipm.flows.fulfillment.get_adobe_client",
        return_value=mocked_adobe_client,
    )

    mocked_mpt_client = mocker.MagicMock()
    mocked_fail_order = mocker.patch("adobe_vipm.flows.fulfillment.fail_order")

    order = order_factory(
        order_parameters=transfer_order_parameters_factory(),
        external_ids={"vendor": "a-transfer-id"},
    )

    fulfill_order(mocked_mpt_client, order)

    mocked_fail_order.assert_called_once_with(
        mocked_mpt_client,
        order["id"],
        "Unexpected status (9999) received from Adobe.",
    )


def test_transfer_items_mismatch(
    mocker,
    seller,
    agreement,
    order_factory,
    transfer_order_parameters_factory,
    adobe_preview_transfer_factory,
    adobe_items_factory,
):
    """
    Tests a transfer order when the items contained in the order don't match
    the subscriptions owned by a given membership id.
    """
    mocker.patch("adobe_vipm.flows.shared.get_agreement", return_value=agreement)

    adobe_transfer_preview = adobe_preview_transfer_factory(
        items=adobe_items_factory(offer_id="99999999CA01A12"),
    )

    mocked_adobe_client = mocker.MagicMock()
    mocked_adobe_client.preview_transfer.return_value = adobe_transfer_preview
    mocker.patch(
        "adobe_vipm.flows.fulfillment.get_adobe_client",
        return_value=mocked_adobe_client,
    )

    mocked_mpt_client = mocker.MagicMock()
    mocked_fail_order = mocker.patch("adobe_vipm.flows.fulfillment.fail_order")

    order = order_factory(order_parameters=transfer_order_parameters_factory())

    fulfill_order(mocked_mpt_client, order)

    seller_country = seller["address"]["country"]

    mocked_adobe_client.preview_transfer.assert_called_once_with(
        seller_country,
        "a-membership-id",
    )

    mocked_fail_order.assert_called_once_with(
        mocked_mpt_client,
        order["id"],
        "The items owned by the given membership don't match "
        "the order (sku or quantity): 99999999CA.",
    )


@pytest.mark.parametrize(
    "transfer_status",
    [
        STATUS_TRANSFER_INVALID_MEMBERSHIP,
        STATUS_TRANSFER_INVALID_MEMBERSHIP_OR_TRANSFER_IDS,
    ],
)
def test_transfer_invalid_membership(
    mocker,
    settings,
    seller,
    agreement,
    order_factory,
    transfer_order_parameters_factory,
    adobe_api_error_factory,
    transfer_status,
):
    """
    Tests a transfer order when the membership id is not valid.
    """
    settings.EXTENSION_CONFIG["QUERYING_TEMPLATE_ID"] = "TPL-964-112"
    mocker.patch("adobe_vipm.flows.shared.get_agreement", return_value=agreement)

    mocked_adobe_client = mocker.MagicMock()
    adobe_error = AdobeAPIError(
        adobe_api_error_factory(
            transfer_status,
            "some error",
        )
    )
    mocked_adobe_client.preview_transfer.side_effect = adobe_error
    mocker.patch(
        "adobe_vipm.flows.fulfillment.get_adobe_client",
        return_value=mocked_adobe_client,
    )

    mocked_mpt_client = mocker.MagicMock()
    mocked_query_order = mocker.patch("adobe_vipm.flows.fulfillment.query_order")

    order = order_factory(order_parameters=transfer_order_parameters_factory())

    fulfill_order(mocked_mpt_client, order)

    seller_country = seller["address"]["country"]

    mocked_adobe_client.preview_transfer.assert_called_once_with(
        seller_country,
        "a-membership-id",
    )
    param = get_ordering_parameter(order, PARAM_MEMBERSHIP_ID)
    order = set_ordering_parameter_error(
        order,
        PARAM_MEMBERSHIP_ID,
        ERR_ADOBE_MEMBERSHIP_ID.to_dict(
            title=param["title"],
            details=str(adobe_error),
        ),
    )
    mocked_query_order.assert_called_once_with(
        mocked_mpt_client,
        order["id"],
        parameters=order["parameters"],
        templateId="TPL-964-112",
    )


@pytest.mark.parametrize("transfer_status", UNRECOVERABLE_TRANSFER_STATUSES)
def test_transfer_unrecoverable_status(
    mocker,
    seller,
    agreement,
    order_factory,
    transfer_order_parameters_factory,
    adobe_api_error_factory,
    transfer_status,
):
    """
    Tests a transfer order when it cannot be processed.
    """
    mocker.patch("adobe_vipm.flows.shared.get_agreement", return_value=agreement)

    mocked_adobe_client = mocker.MagicMock()
    adobe_error = AdobeAPIError(
        adobe_api_error_factory(
            transfer_status,
            "some error",
        )
    )
    mocked_adobe_client.preview_transfer.side_effect = adobe_error
    mocker.patch(
        "adobe_vipm.flows.fulfillment.get_adobe_client",
        return_value=mocked_adobe_client,
    )

    mocked_mpt_client = mocker.MagicMock()
    mocked_fail_order = mocker.patch("adobe_vipm.flows.fulfillment.fail_order")

    order = order_factory(order_parameters=transfer_order_parameters_factory())

    fulfill_order(mocked_mpt_client, order)

    seller_country = seller["address"]["country"]

    mocked_adobe_client.preview_transfer.assert_called_once_with(
        seller_country,
        "a-membership-id",
    )
    mocked_fail_order.assert_called_once_with(
        mocked_mpt_client,
        order["id"],
        str(adobe_error),
    )


def test_create_transfer_fail(
    mocker,
    agreement,
    order_factory,
    transfer_order_parameters_factory,
    adobe_preview_transfer_factory,
):
    """
    Tests generic failure on transfer order creation.
    """
    mocker.patch("adobe_vipm.flows.shared.get_agreement", return_value=agreement)

    adobe_transfer_preview = adobe_preview_transfer_factory()

    mocked_adobe_client = mocker.MagicMock()
    mocked_adobe_client.preview_transfer.return_value = adobe_transfer_preview
    mocked_adobe_client.create_transfer.side_effect = AdobeError("Unexpected error")

    mocker.patch(
        "adobe_vipm.flows.fulfillment.get_adobe_client",
        return_value=mocked_adobe_client,
    )

    mocked_mpt_client = mocker.MagicMock()
    mocked_fail_order = mocker.patch("adobe_vipm.flows.fulfillment.fail_order")

    order = order_factory(order_parameters=transfer_order_parameters_factory())

    fulfill_order(mocked_mpt_client, order)

    mocked_fail_order.assert_called_once_with(
        mocked_mpt_client,
        order["id"],
        "Unexpected error",
    )
