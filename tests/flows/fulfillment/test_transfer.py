from datetime import date, datetime

import pytest
from freezegun import freeze_time

from adobe_vipm.adobe.constants import (
    ORDER_TYPE_NEW,
    ORDER_TYPE_PREVIEW,
    STATUS_3YC_COMMITTED,
    STATUS_3YC_EXPIRED,
    STATUS_INACTIVE_OR_GENERIC_FAILURE,
    STATUS_PENDING,
    STATUS_PROCESSED,
    STATUS_TRANSFER_INVALID_MEMBERSHIP,
    STATUS_TRANSFER_INVALID_MEMBERSHIP_OR_TRANSFER_IDS,
    UNRECOVERABLE_TRANSFER_STATUSES,
)
from adobe_vipm.adobe.errors import AdobeAPIError, AdobeError, AdobeHttpError
from adobe_vipm.flows.airtable import STATUS_SYNCHRONIZED
from adobe_vipm.flows.constants import (
    ERR_ADOBE_MEMBERSHIP_ID,
    ERR_ADOBE_MEMBERSHIP_NOT_FOUND,
    ERR_UPDATING_TRANSFER_ITEMS,
    MPT_ORDER_STATUS_COMPLETED,
    MPT_ORDER_STATUS_PROCESSING,
    PARAM_MEMBERSHIP_ID,
    TEMPLATE_NAME_BULK_MIGRATE,
    TEMPLATE_NAME_TRANSFER,
)
from adobe_vipm.flows.context import Context
from adobe_vipm.flows.fulfillment import fulfill_order
from adobe_vipm.flows.fulfillment.transfer import UpdateTransferStatus
from adobe_vipm.flows.utils import (
    get_ordering_parameter,
    set_ordering_parameter_error,
    split_phone_number,
)

pytestmark = pytest.mark.usefixtures("mock_adobe_config")


@freeze_time("2024-01-01")
def test_transfer(
    mocker,
    agreement,
    order_factory,
    transfer_order_parameters_factory,
    fulfillment_parameters_factory,
    adobe_preview_transfer_factory,
    adobe_transfer_factory,
    adobe_items_factory,
    adobe_subscription_factory,
    adobe_customer_factory,
    items_factory,
    subscriptions_factory,
):
    """
    Tests the processing of a transfer order including:
        * order creation
        * subscription creation
        * order completion
    """
    mocked_get_template = mocker.patch(
        "adobe_vipm.flows.fulfillment.shared.get_product_template_or_default",
        side_effect=[{"id": "TPL-0000"}, {"id": "TPL-1111"}],
    )
    mocker.patch(
        "adobe_vipm.flows.fulfillment.transfer.get_transfer_by_authorization_membership_or_customer",
        return_value=None,
    )
    mocker.patch("adobe_vipm.flows.helpers.get_agreement", return_value=agreement)

    adobe_transfer = adobe_transfer_factory(
        status=STATUS_PROCESSED,
        customer_id="a-client-id",
        items=adobe_items_factory(subscription_id="a-sub-id")
        + adobe_items_factory(line_number=2, subscription_id="inactive-sub-id")
        + adobe_items_factory(
            line_number=3, offer_id="99999999CA01A12", subscription_id="one-time-sub-id"
        ),
    )

    adobe_transfer_preview = adobe_preview_transfer_factory()
    adobe_customer = adobe_customer_factory()
    adobe_subscription = adobe_subscription_factory()
    adobe_inactive_subscription = adobe_subscription_factory(
        subscription_id="inactive-sub-id", status=STATUS_INACTIVE_OR_GENERIC_FAILURE
    )
    adobe_one_time_subscription = adobe_subscription_factory(
        subscription_id="one-time-sub-id",
    )

    mocked_adobe_client = mocker.MagicMock()
    mocked_adobe_client.preview_transfer.return_value = adobe_transfer_preview
    mocked_adobe_client.create_transfer.return_value = adobe_transfer
    mocked_adobe_client.get_customer.return_value = adobe_customer
    mocked_adobe_client.get_transfer.return_value = adobe_transfer
    mocked_adobe_client.get_subscription.side_effect = [
        adobe_subscription,
        adobe_inactive_subscription,
        adobe_one_time_subscription,
    ]
    mocked_adobe_client.update_subscription.return_value = adobe_subscription
    mocker.patch(
        "adobe_vipm.flows.fulfillment.transfer.get_adobe_client",
        return_value=mocked_adobe_client,
    )

    order = order_factory(
        order_parameters=transfer_order_parameters_factory(),
    )

    mocked_mpt_client = mocker.MagicMock()
    mocked_update_order = mocker.patch(
        "adobe_vipm.flows.fulfillment.shared.update_order",
    )
    mocked_update_agreement = mocker.patch(
        "adobe_vipm.flows.fulfillment.shared.update_agreement",
    )
    subscription = subscriptions_factory(commitment_date="2024-01-01")[0]
    mocked_create_subscription = mocker.patch(
        "adobe_vipm.flows.fulfillment.shared.create_subscription",
        return_value=subscription,
    )
    mocked_get_onetime = mocker.patch(
        "adobe_vipm.flows.utils.get_product_onetime_items_by_ids",
        return_value=items_factory(item_id=2, external_vendor_id="99999999CA"),
    )

    mocked_process_order = mocker.patch(
        "adobe_vipm.flows.fulfillment.shared.set_processing_template",
    )

    mocked_complete_order = mocker.patch(
        "adobe_vipm.flows.fulfillment.shared.complete_order"
    )
    mocked_sync_agreement = mocker.patch(
        "adobe_vipm.flows.fulfillment.transfer.sync_agreements_by_agreement_ids"
    )

    fulfill_order(mocked_mpt_client, order)

    authorization_id = order["authorization"]["id"]
    adobe_customer_address = adobe_customer["companyProfile"]["address"]
    adobe_customer_contact = adobe_customer["companyProfile"]["contacts"][0]

    mocked_adobe_client.preview_transfer.assert_called_once_with(
        authorization_id,
        "a-membership-id",
    )

    assert mocked_update_order.mock_calls[0].args == (
        mocked_mpt_client,
        order["id"],
    )
    assert mocked_update_order.mock_calls[0].kwargs == {
        "parameters": {
            "fulfillment": fulfillment_parameters_factory(
                due_date="2024-01-31",
            ),
            "ordering": order["parameters"]["ordering"],
        },
    }
    assert mocked_update_order.mock_calls[1].args == (
        mocked_mpt_client,
        order["id"],
    )
    assert mocked_update_order.mock_calls[1].kwargs == {
        "externalIds": {
            "vendor": adobe_transfer["transferId"],
        },
    }
    assert mocked_update_order.mock_calls[2].args == (
        mocked_mpt_client,
        order["id"],
    )
    assert mocked_update_order.mock_calls[2].kwargs == {
        "externalIds": {
            "vendor": adobe_transfer["transferId"],
        },
        "parameters": {
            "fulfillment": fulfillment_parameters_factory(
                customer_id="a-client-id",
                due_date="2024-01-31",
            ),
            "ordering": transfer_order_parameters_factory(
                company_name=adobe_customer["companyProfile"]["companyName"],
                address={
                    "country": adobe_customer_address["country"],
                    "state": adobe_customer_address["region"],
                    "city": adobe_customer_address["city"],
                    "addressLine1": adobe_customer_address["addressLine1"],
                    "addressLine2": adobe_customer_address["addressLine2"],
                    "postCode": adobe_customer_address["postalCode"],
                },
                contact={
                    "firstName": adobe_customer_contact["firstName"],
                    "lastName": adobe_customer_contact["lastName"],
                    "email": adobe_customer_contact["email"],
                    "phone": split_phone_number(
                        adobe_customer_contact.get("phoneNumber"),
                        adobe_customer_address["country"],
                    ),
                },
            ),
        },
    }

    assert mocked_update_order.mock_calls[3].args == (
        mocked_mpt_client,
        order["id"],
    )
    assert mocked_update_order.mock_calls[3].kwargs == {
        "parameters": {
            "fulfillment": fulfillment_parameters_factory(
                customer_id="a-client-id",
                due_date=None,
                next_sync_date="2024-01-02",
                coterm_date="2024-01-01",
            ),
            "ordering": transfer_order_parameters_factory(
                company_name=adobe_customer["companyProfile"]["companyName"],
                address={
                    "country": adobe_customer_address["country"],
                    "state": adobe_customer_address["region"],
                    "city": adobe_customer_address["city"],
                    "addressLine1": adobe_customer_address["addressLine1"],
                    "addressLine2": adobe_customer_address["addressLine2"],
                    "postCode": adobe_customer_address["postalCode"],
                },
                contact={
                    "firstName": adobe_customer_contact["firstName"],
                    "lastName": adobe_customer_contact["lastName"],
                    "email": adobe_customer_contact["email"],
                    "phone": split_phone_number(
                        adobe_customer_contact.get("phoneNumber"),
                        adobe_customer_address["country"],
                    ),
                },
            ),
        },
    }

    mocked_update_agreement.assert_called_once_with(
        mocked_mpt_client,
        order["agreement"]["id"],
        externalIds={"vendor": "a-client-id"},
    )

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
                    {
                        "externalId": "currentQuantity",
                        "value": str(adobe_subscription["currentQuantity"]),
                    },
                    {
                        "externalId": "renewalQuantity",
                        "value": str(
                            adobe_subscription["autoRenewal"]["renewalQuantity"]
                        ),
                    },
                    {
                        "externalId": "renewalDate",
                        "value": adobe_subscription["renewalDate"],
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
            "autoRenew": adobe_subscription["autoRenewal"]["enabled"],
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
        parameters={
            "fulfillment": fulfillment_parameters_factory(
                customer_id="a-client-id",
                due_date=None,
                next_sync_date="2024-01-02",
                coterm_date="2024-01-01",
            ),
            "ordering": transfer_order_parameters_factory(
                company_name=adobe_customer["companyProfile"]["companyName"],
                address={
                    "country": adobe_customer_address["country"],
                    "state": adobe_customer_address["region"],
                    "city": adobe_customer_address["city"],
                    "addressLine1": adobe_customer_address["addressLine1"],
                    "addressLine2": adobe_customer_address["addressLine2"],
                    "postCode": adobe_customer_address["postalCode"],
                },
                contact={
                    "firstName": adobe_customer_contact["firstName"],
                    "lastName": adobe_customer_contact["lastName"],
                    "email": adobe_customer_contact["email"],
                    "phone": split_phone_number(
                        adobe_customer_contact.get("phoneNumber"),
                        adobe_customer_address["country"],
                    ),
                },
            ),
        },
    )
    mocked_adobe_client.get_transfer.assert_called_once_with(
        authorization_id, "a-membership-id", adobe_transfer["transferId"]
    )

    assert mocked_adobe_client.get_subscription.mock_calls[0].args == (
        authorization_id,
        "a-client-id",
        adobe_subscription["subscriptionId"],
    )
    assert mocked_adobe_client.get_subscription.mock_calls[1].args == (
        authorization_id,
        "a-client-id",
        adobe_inactive_subscription["subscriptionId"],
    )
    assert mocked_get_template.mock_calls[0].args == (
        mocked_mpt_client,
        order["agreement"]["product"]["id"],
        MPT_ORDER_STATUS_PROCESSING,
        TEMPLATE_NAME_TRANSFER,
    )

    assert mocked_get_template.mock_calls[1].args == (
        mocked_mpt_client,
        order["agreement"]["product"]["id"],
        MPT_ORDER_STATUS_COMPLETED,
        TEMPLATE_NAME_TRANSFER,
    )
    mocked_get_onetime.assert_called_once_with(
        mocked_mpt_client,
        order["agreement"]["product"]["id"],
        [line["item"]["id"] for line in order["lines"]],
    )
    mocked_sync_agreement.assert_called_once_with(
        mocked_mpt_client,
        [order["agreement"]["id"]],
        False,
    )


@freeze_time("2025-01-01")
def test_transfer_not_ready(
    mocker,
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
    mocker.patch(
        "adobe_vipm.flows.fulfillment.transfer.get_transfer_by_authorization_membership_or_customer",
        return_value=None,
    )
    mocker.patch("adobe_vipm.flows.helpers.get_agreement", return_value=agreement)

    adobe_transfer = adobe_transfer_factory(status=STATUS_PENDING)

    mocked_adobe_client = mocker.MagicMock()
    mocked_adobe_client.create_transfer.return_value = adobe_transfer
    mocked_adobe_client.get_transfer.return_value = adobe_transfer
    mocker.patch(
        "adobe_vipm.flows.fulfillment.transfer.get_adobe_client",
        return_value=mocked_adobe_client,
    )

    mocked_mpt_client = mocker.MagicMock()
    mocked_update_order = mocker.patch(
        "adobe_vipm.flows.fulfillment.shared.update_order"
    )
    mocked_complete_order = mocker.patch(
        "adobe_vipm.flows.fulfillment.shared.complete_order"
    )

    order = order_factory(
        order_parameters=transfer_order_parameters_factory(),
        external_ids={"vendor": "a-transfer-id"},
    )

    fulfill_order(mocked_mpt_client, order)

    authorization_id = order["authorization"]["id"]

    assert mocked_update_order.mock_calls[0].args == (
        mocked_mpt_client,
        order["id"],
    )
    assert mocked_update_order.mock_calls[0].kwargs == {
        "parameters": {
            "fulfillment": fulfillment_parameters_factory(
                due_date="2025-01-31",
            ),
            "ordering": transfer_order_parameters_factory(),
        },
    }

    mocked_complete_order.assert_not_called()
    mocked_adobe_client.get_transfer.assert_called_once_with(
        authorization_id, "a-membership-id", adobe_transfer["transferId"]
    )


def test_transfer_unexpected_status(
    mocker,
    agreement,
    order_factory,
    transfer_order_parameters_factory,
    adobe_transfer_factory,
):
    """
    Tests the processing of a transfer order when the Adobe transfer has been processed
    unsuccessfully and the status of the transfer returned by Adobe is not documented.
    The transfer order will be failed with a message that explain that Adobe returned an
    unexpected error.
    """
    mocker.patch(
        "adobe_vipm.flows.fulfillment.transfer.get_transfer_by_authorization_membership_or_customer",
        return_value=None,
    )
    mocker.patch("adobe_vipm.flows.helpers.get_agreement", return_value=agreement)

    adobe_transfer = adobe_transfer_factory(status="9999")

    mocked_adobe_client = mocker.MagicMock()
    mocked_adobe_client.create_transfer.return_value = adobe_transfer
    mocked_adobe_client.get_transfer.return_value = adobe_transfer
    mocker.patch(
        "adobe_vipm.flows.fulfillment.transfer.get_adobe_client",
        return_value=mocked_adobe_client,
    )

    mocked_mpt_client = mocker.MagicMock()
    mocked_fail_order = mocker.patch("adobe_vipm.flows.fulfillment.shared.fail_order")

    order = order_factory(
        order_parameters=transfer_order_parameters_factory(),
        external_ids={"vendor": "a-transfer-id"},
    )

    fulfill_order(mocked_mpt_client, order)

    mocked_fail_order.assert_called_once_with(
        mocked_mpt_client,
        order["id"],
        "Unexpected status (9999) received from Adobe.",
        parameters=order["parameters"],
    )


def test_transfer_items_mismatch(
    mocker,
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
    mocker.patch(
        "adobe_vipm.flows.fulfillment.transfer.get_transfer_by_authorization_membership_or_customer",
        return_value=None,
    )
    mocker.patch("adobe_vipm.flows.helpers.get_agreement", return_value=agreement)

    adobe_transfer_preview = adobe_preview_transfer_factory(
        items=adobe_items_factory(offer_id="99999999CA01A12"),
    )

    mocked_adobe_client = mocker.MagicMock()
    mocked_adobe_client.preview_transfer.return_value = adobe_transfer_preview
    mocker.patch(
        "adobe_vipm.flows.fulfillment.transfer.get_adobe_client",
        return_value=mocked_adobe_client,
    )

    mocked_mpt_client = mocker.MagicMock()
    mocked_fail_order = mocker.patch("adobe_vipm.flows.fulfillment.shared.fail_order")

    order = order_factory(order_parameters=transfer_order_parameters_factory())

    fulfill_order(mocked_mpt_client, order)

    authorization_id = order["authorization"]["id"]

    mocked_adobe_client.preview_transfer.assert_called_once_with(
        authorization_id,
        "a-membership-id",
    )

    mocked_fail_order.assert_called_once_with(
        mocked_mpt_client,
        order["id"],
        "The items owned by the given membership don't match "
        "the order (sku or quantity): 99999999CA.",
        parameters=order["parameters"],
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
    agreement,
    order_factory,
    transfer_order_parameters_factory,
    adobe_api_error_factory,
    transfer_status,
):
    """
    Tests a transfer order when the membership id is not valid.
    """
    mocker.patch(
        "adobe_vipm.flows.fulfillment.shared.get_product_template_or_default",
        return_value={"id": "TPL-964-112"},
    )

    mocker.patch(
        "adobe_vipm.flows.fulfillment.transfer.get_transfer_by_authorization_membership_or_customer",
        return_value=None,
    )
    mocker.patch("adobe_vipm.flows.helpers.get_agreement", return_value=agreement)

    mocked_adobe_client = mocker.MagicMock()
    adobe_error = AdobeAPIError(
        400,
        adobe_api_error_factory(
            transfer_status,
            "some error",
        ),
    )
    mocked_adobe_client.preview_transfer.side_effect = adobe_error
    mocker.patch(
        "adobe_vipm.flows.fulfillment.transfer.get_adobe_client",
        return_value=mocked_adobe_client,
    )

    mocked_mpt_client = mocker.MagicMock()
    mocked_query_order = mocker.patch("adobe_vipm.flows.fulfillment.shared.query_order")

    order = order_factory(order_parameters=transfer_order_parameters_factory())

    fulfill_order(mocked_mpt_client, order)

    authorization_id = order["authorization"]["id"]

    mocked_adobe_client.preview_transfer.assert_called_once_with(
        authorization_id,
        "a-membership-id",
    )
    param = get_ordering_parameter(order, PARAM_MEMBERSHIP_ID)
    order = set_ordering_parameter_error(
        order,
        PARAM_MEMBERSHIP_ID,
        ERR_ADOBE_MEMBERSHIP_ID.to_dict(
            title=param["name"],
            details=str(adobe_error),
        ),
    )
    mocked_query_order.assert_called_once_with(
        mocked_mpt_client,
        order["id"],
        parameters=order["parameters"],
        template={"id": "TPL-964-112"},
    )


def test_transfer_membership_not_found(
    mocker,
    agreement,
    order_factory,
    transfer_order_parameters_factory,
):
    """
    Tests a transfer order when the membership id is not found.
    """
    mocker.patch(
        "adobe_vipm.flows.fulfillment.shared.get_product_template_or_default",
        return_value={"id": "TPL-964-112"},
    )

    mocker.patch(
        "adobe_vipm.flows.fulfillment.transfer.get_transfer_by_authorization_membership_or_customer",
        return_value=None,
    )
    mocker.patch("adobe_vipm.flows.helpers.get_agreement", return_value=agreement)

    mocked_adobe_client = mocker.MagicMock()
    adobe_error = AdobeHttpError(404, "Not found")
    mocked_adobe_client.preview_transfer.side_effect = adobe_error
    mocker.patch(
        "adobe_vipm.flows.fulfillment.transfer.get_adobe_client",
        return_value=mocked_adobe_client,
    )

    mocked_mpt_client = mocker.MagicMock()
    mocked_query_order = mocker.patch("adobe_vipm.flows.fulfillment.shared.query_order")

    order = order_factory(order_parameters=transfer_order_parameters_factory())

    fulfill_order(mocked_mpt_client, order)

    authorization_id = order["authorization"]["id"]

    mocked_adobe_client.preview_transfer.assert_called_once_with(
        authorization_id,
        "a-membership-id",
    )
    param = get_ordering_parameter(order, PARAM_MEMBERSHIP_ID)
    order = set_ordering_parameter_error(
        order,
        PARAM_MEMBERSHIP_ID,
        ERR_ADOBE_MEMBERSHIP_ID.to_dict(
            title=param["name"],
            details=ERR_ADOBE_MEMBERSHIP_NOT_FOUND,
        ),
    )
    mocked_query_order.assert_called_once_with(
        mocked_mpt_client,
        order["id"],
        parameters=order["parameters"],
        template={"id": "TPL-964-112"},
    )


@pytest.mark.parametrize("transfer_status", UNRECOVERABLE_TRANSFER_STATUSES)
def test_transfer_unrecoverable_status(
    mocker,
    agreement,
    order_factory,
    transfer_order_parameters_factory,
    adobe_api_error_factory,
    transfer_status,
):
    """
    Tests a transfer order when it cannot be processed.
    """
    mocker.patch(
        "adobe_vipm.flows.fulfillment.transfer.get_transfer_by_authorization_membership_or_customer",
        return_value=None,
    )
    mocker.patch("adobe_vipm.flows.helpers.get_agreement", return_value=agreement)

    mocked_adobe_client = mocker.MagicMock()
    adobe_error = AdobeAPIError(
        400,
        adobe_api_error_factory(
            transfer_status,
            "some error",
        ),
    )
    mocked_adobe_client.preview_transfer.side_effect = adobe_error
    mocker.patch(
        "adobe_vipm.flows.fulfillment.transfer.get_adobe_client",
        return_value=mocked_adobe_client,
    )

    mocked_mpt_client = mocker.MagicMock()
    mocked_fail_order = mocker.patch("adobe_vipm.flows.fulfillment.shared.fail_order")

    order = order_factory(order_parameters=transfer_order_parameters_factory())

    fulfill_order(mocked_mpt_client, order)

    authorization_id = order["authorization"]["id"]

    mocked_adobe_client.preview_transfer.assert_called_once_with(
        authorization_id,
        "a-membership-id",
    )
    mocked_fail_order.assert_called_once_with(
        mocked_mpt_client,
        order["id"],
        str(adobe_error),
        parameters=order["parameters"],
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
    mocker.patch(
        "adobe_vipm.flows.fulfillment.transfer.get_transfer_by_authorization_membership_or_customer",
        return_value=None,
    )
    mocker.patch("adobe_vipm.flows.helpers.get_agreement", return_value=agreement)

    adobe_transfer_preview = adobe_preview_transfer_factory()

    mocked_adobe_client = mocker.MagicMock()
    mocked_adobe_client.preview_transfer.return_value = adobe_transfer_preview
    mocked_adobe_client.create_transfer.side_effect = AdobeError("Unexpected error")

    mocker.patch(
        "adobe_vipm.flows.fulfillment.transfer.get_adobe_client",
        return_value=mocked_adobe_client,
    )

    mocked_mpt_client = mocker.MagicMock()
    mocked_fail_order = mocker.patch("adobe_vipm.flows.fulfillment.shared.fail_order")

    order = order_factory(order_parameters=transfer_order_parameters_factory())

    fulfill_order(mocked_mpt_client, order)

    mocked_fail_order.assert_called_once_with(
        mocked_mpt_client,
        order["id"],
        "Unexpected error",
        parameters=order["parameters"],
    )


@freeze_time("2012-01-14 12:00:01")
def test_fulfill_transfer_order_already_migrated(
    mocker,
    order_factory,
    items_factory,
    transfer_order_parameters_factory,
    fulfillment_parameters_factory,
    subscriptions_factory,
    adobe_transfer_factory,
    adobe_items_factory,
    adobe_authorizations_file,
    adobe_customer_factory,
    agreement,
    adobe_subscription_factory,
):
    mocked_get_template = mocker.patch(
        "adobe_vipm.flows.fulfillment.shared.get_product_template_or_default",
        side_effect=[{"id": "TPL-0000"}, {"id": "TPL-1111"}],
    )

    order_params = transfer_order_parameters_factory()
    order = order_factory(order_parameters=order_params)

    mocker.patch("adobe_vipm.flows.helpers.get_agreement", return_value=agreement)

    mocked_transfer = mocker.MagicMock()
    mocked_transfer.membership_id = "membership-id"
    mocked_transfer.customer_id = "customer-id"
    mocked_transfer.transfer_id = "transfer-id"
    mocked_transfer.customer_benefits_3yc_status = None

    adobe_customer = adobe_customer_factory()

    adobe_customer_address = adobe_customer["companyProfile"]["address"]
    adobe_customer_contact = adobe_customer["companyProfile"]["contacts"][0]

    updated_order = order_factory(
        fulfillment_parameters=fulfillment_parameters_factory(
            customer_id="a-client-id",
            due_date="2012-02-13",
        ),
        order_parameters=transfer_order_parameters_factory(
            company_name=adobe_customer["companyProfile"]["companyName"],
            address={
                "country": adobe_customer_address["country"],
                "state": adobe_customer_address["region"],
                "city": adobe_customer_address["city"],
                "addressLine1": adobe_customer_address["addressLine1"],
                "addressLine2": adobe_customer_address["addressLine2"],
                "postCode": adobe_customer_address["postalCode"],
            },
            contact={
                "firstName": adobe_customer_contact["firstName"],
                "lastName": adobe_customer_contact["lastName"],
                "email": adobe_customer_contact["email"],
                "phone": split_phone_number(
                    adobe_customer_contact.get("phoneNumber"),
                    adobe_customer_address["country"],
                ),
            },
        ),
        external_ids={"vendor": "transfer-id"},
    )

    m_client = mocker.MagicMock()

    mocked_get_transfer = mocker.patch(
        "adobe_vipm.flows.fulfillment.transfer.get_transfer_by_authorization_membership_or_customer",
        return_value=mocked_transfer,
    )

    mocker.patch(
        "adobe_vipm.flows.utils.get_product_onetime_items_by_ids",
        return_value=items_factory(item_id=2, external_vendor_id="99999999CA"),
    )

    mocker.patch(
        "adobe_vipm.flows.fulfillment.transfer.add_subscription",
        return_value=subscriptions_factory(commitment_date="2024-04-18")[0],
    )

    mocked_process_order = mocker.patch(
        "adobe_vipm.flows.fulfillment.shared.set_processing_template",
    )

    mocked_update_order = mocker.patch(
        "adobe_vipm.flows.fulfillment.shared.update_order",
    )

    mocked_complete_order = mocker.patch(
        "adobe_vipm.flows.fulfillment.shared.complete_order"
    )

    transfer_items = adobe_items_factory(subscription_id="sub-id")

    adobe_transfer = adobe_transfer_factory(items=transfer_items)
    adobe_subscription = adobe_subscription_factory(current_quantity=170)

    mocked_adobe_client = mocker.MagicMock()
    mocked_adobe_client.get_transfer.return_value = adobe_transfer
    mocked_adobe_client.get_customer.return_value = adobe_customer
    mocked_adobe_client.get_subscription.return_value = adobe_subscription
    mocked_adobe_client.get_subscriptions.return_value = {
        "items": [adobe_subscription],
    }

    mocker.patch(
        "adobe_vipm.flows.fulfillment.transfer.get_adobe_client",
        return_value=mocked_adobe_client,
    )

    fulfill_order(m_client, order)

    membership_id_param = get_ordering_parameter(updated_order, PARAM_MEMBERSHIP_ID)

    mocked_get_transfer.assert_called_once_with(
        order["agreement"]["product"]["id"],
        adobe_authorizations_file["authorizations"][0]["authorization_id"],
        membership_id_param["value"],
    )

    mocked_process_order.assert_called_once_with(
        m_client,
        order["id"],
        {"id": "TPL-0000"},
    )

    mocked_complete_order.assert_called_once_with(
        m_client,
        order["id"],
        {"id": "TPL-1111"},
        parameters={
            "ordering": updated_order["parameters"]["ordering"],
            "fulfillment": fulfillment_parameters_factory(
                customer_id="a-client-id",
                due_date=None,
                next_sync_date="2024-04-19",
                coterm_date="2024-04-18",
            ),
        },
    )

    assert mocked_update_order.mock_calls[0].args == (
        m_client,
        order["id"],
    )
    assert mocked_update_order.mock_calls[0].kwargs == {
        "parameters": {
            "fulfillment": fulfillment_parameters_factory(
                due_date="2012-02-13",
            ),
            "ordering": order["parameters"]["ordering"],
        },
    }

    assert mocked_update_order.mock_calls[1].args == (
        m_client,
        order["id"],
    )

    assert mocked_transfer.status == "synchronized"
    assert mocked_transfer.synchronized_at == datetime(2012, 1, 14, 12, 00, 1)
    assert mocked_transfer.mpt_order_id == order["id"]
    mocked_transfer.save.assert_called_once()

    assert mocked_get_template.mock_calls[0].args == (
        m_client,
        order["agreement"]["product"]["id"],
        MPT_ORDER_STATUS_PROCESSING,
        TEMPLATE_NAME_BULK_MIGRATE,
    )

    assert mocked_get_template.mock_calls[1].args == (
        m_client,
        order["agreement"]["product"]["id"],
        MPT_ORDER_STATUS_COMPLETED,
        TEMPLATE_NAME_BULK_MIGRATE,
    )

    mocked_adobe_client.update_subscription.assert_called_once_with(
        adobe_authorizations_file["authorizations"][0]["authorization_id"],
        mocked_transfer.customer_id,
        transfer_items[0]["subscriptionId"],
        auto_renewal=True,
    )


@freeze_time("2012-01-14 12:00:01")
def test_fulfill_transfer_order_already_migrated_error_order_line_updated(
    mocker,
    order_factory,
    items_factory,
    transfer_order_parameters_factory,
    fulfillment_parameters_factory,
    subscriptions_factory,
    adobe_transfer_factory,
    adobe_items_factory,
    adobe_authorizations_file,
    adobe_customer_factory,
    agreement,
    adobe_subscription_factory,
):
    mocker.patch(
        "adobe_vipm.flows.fulfillment.shared.get_product_template_or_default",
        side_effect=[{"id": "TPL-0000"}, {"id": "TPL-1111"}],
    )

    order_params = transfer_order_parameters_factory()
    order = order_factory(order_parameters=order_params)

    mocker.patch("adobe_vipm.flows.helpers.get_agreement", return_value=agreement)

    mocked_transfer = mocker.MagicMock()
    mocked_transfer.membership_id = "membership-id"
    mocked_transfer.customer_id = "customer-id"
    mocked_transfer.transfer_id = "transfer-id"
    mocked_transfer.customer_benefits_3yc_status = None

    adobe_customer = adobe_customer_factory()
    m_client = mocker.MagicMock()

    mocker.patch(
        "adobe_vipm.flows.fulfillment.transfer.get_transfer_by_authorization_membership_or_customer",
        return_value=mocked_transfer,
    )

    mocker.patch(
        "adobe_vipm.flows.utils.get_product_onetime_items_by_ids",
        return_value=items_factory(item_id=2, external_vendor_id="99999999CA"),
    )

    mocked_process_order = mocker.patch(
        "adobe_vipm.flows.fulfillment.shared.set_processing_template",
    )

    mocked_update_order = mocker.patch(
        "adobe_vipm.flows.fulfillment.shared.update_order",
    )

    transfer_items = adobe_items_factory(
        subscription_id="sub-id", renewal_date=date.today().isoformat()
    ) + adobe_items_factory(
        line_number=2,
        offer_id="99999999CA01A12",
        subscription_id="onetime-sub-id",
    )

    adobe_transfer = adobe_transfer_factory(items=transfer_items)
    adobe_subscription = adobe_subscription_factory()

    mocked_adobe_client = mocker.MagicMock()
    mocked_adobe_client.get_transfer.return_value = adobe_transfer
    mocked_adobe_client.get_customer.return_value = adobe_customer
    mocked_adobe_client.get_subscriptions.return_value = {
        "items": [adobe_subscription],
    }

    mocker.patch(
        "adobe_vipm.flows.fulfillment.transfer.get_adobe_client",
        return_value=mocked_adobe_client,
    )
    mocked_fail_order = mocker.patch("adobe_vipm.flows.fulfillment.shared.fail_order")

    fulfill_order(m_client, order)

    mocked_process_order.assert_called_once_with(
        m_client,
        order["id"],
        {"id": "TPL-0000"},
    )
    mocked_fail_order.assert_called_once_with(
        m_client,
        order["id"],
        ERR_UPDATING_TRANSFER_ITEMS.message,
        parameters=order["parameters"],
    )

    assert mocked_update_order.mock_calls[0].args == (
        m_client,
        order["id"],
    )
    assert mocked_update_order.mock_calls[0].kwargs == {
        "parameters": {
            "fulfillment": fulfillment_parameters_factory(
                due_date=None,
            ),
            "ordering": order["parameters"]["ordering"],
        },
    }


@freeze_time("2012-01-14 12:00:01")
def test_fulfill_transfer_order_already_migrated_3yc(
    mocker,
    order_factory,
    transfer_order_parameters_factory,
    fulfillment_parameters_factory,
    subscriptions_factory,
    adobe_transfer_factory,
    adobe_items_factory,
    adobe_authorizations_file,
    adobe_customer_factory,
    agreement,
    adobe_subscription_factory,
):
    mocked_get_template = mocker.patch(
        "adobe_vipm.flows.fulfillment.shared.get_product_template_or_default",
        side_effect=[{"id": "TPL-0000"}, {"id": "TPL-1111"}],
    )

    order_params = transfer_order_parameters_factory()
    order = order_factory(order_parameters=order_params)

    mocker.patch("adobe_vipm.flows.helpers.get_agreement", return_value=agreement)

    mocked_transfer = mocker.MagicMock()
    mocked_transfer.customer_id = "customer-id"
    mocked_transfer.transfer_id = "transfer-id"
    mocked_transfer.customer_benefits_3yc_status = STATUS_3YC_COMMITTED

    adobe_customer = adobe_customer_factory()

    adobe_customer_address = adobe_customer["companyProfile"]["address"]
    adobe_customer_contact = adobe_customer["companyProfile"]["contacts"][0]

    updated_order = order_factory(
        fulfillment_parameters=fulfillment_parameters_factory(
            customer_id="a-client-id",
            due_date="2012-02-14",
            next_sync_date="2024-08-05",
            coterm_date="2024-08-04",
        ),
        order_parameters=transfer_order_parameters_factory(
            company_name=adobe_customer["companyProfile"]["companyName"],
            address={
                "country": adobe_customer_address["country"],
                "state": adobe_customer_address["region"],
                "city": adobe_customer_address["city"],
                "addressLine1": adobe_customer_address["addressLine1"],
                "addressLine2": adobe_customer_address["addressLine2"],
                "postCode": adobe_customer_address["postalCode"],
            },
            contact={
                "firstName": adobe_customer_contact["firstName"],
                "lastName": adobe_customer_contact["lastName"],
                "email": adobe_customer_contact["email"],
                "phone": split_phone_number(
                    adobe_customer_contact.get("phoneNumber"),
                    adobe_customer_address["country"],
                ),
            },
        ),
        external_ids={"vendor": "transfer-id"},
    )

    m_client = mocker.MagicMock()

    mocked_get_transfer = mocker.patch(
        "adobe_vipm.flows.fulfillment.transfer.get_transfer_by_authorization_membership_or_customer",
        return_value=mocked_transfer,
    )

    mocker.patch(
        "adobe_vipm.flows.utils.get_product_onetime_items_by_ids",
        return_value=[],
    )

    mocker.patch(
        "adobe_vipm.flows.fulfillment.transfer.add_subscription",
        return_value=subscriptions_factory(commitment_date="2024-08-04")[0],
    )

    mocked_process_order = mocker.patch(
        "adobe_vipm.flows.fulfillment.shared.set_processing_template",
    )

    mocked_update_order = mocker.patch(
        "adobe_vipm.flows.fulfillment.shared.update_order",
    )

    mocked_complete_order = mocker.patch(
        "adobe_vipm.flows.fulfillment.shared.complete_order"
    )

    transfer_items = adobe_items_factory(subscription_id="sub-id")

    adobe_transfer = adobe_transfer_factory(items=transfer_items)
    adobe_subscription = adobe_subscription_factory(current_quantity=170)

    mocked_adobe_client = mocker.MagicMock()
    mocked_adobe_client.get_transfer.return_value = adobe_transfer
    mocked_adobe_client.get_customer.return_value = adobe_customer
    mocked_adobe_client.get_subscription.return_value = adobe_subscription
    mocked_adobe_client.get_subscriptions.return_value = {
        "items": [adobe_subscription],
    }

    mocker.patch(
        "adobe_vipm.flows.fulfillment.transfer.get_adobe_client",
        return_value=mocked_adobe_client,
    )

    fulfill_order(m_client, order)

    membership_id_param = get_ordering_parameter(updated_order, PARAM_MEMBERSHIP_ID)

    mocked_get_transfer.assert_called_once_with(
        order["agreement"]["product"]["id"],
        adobe_authorizations_file["authorizations"][0]["authorization_id"],
        membership_id_param["value"],
    )

    mocked_process_order.assert_called_once_with(
        m_client,
        order["id"],
        {"id": "TPL-0000"},
    )

    mocked_complete_order.assert_called_once_with(
        m_client,
        order["id"],
        {"id": "TPL-1111"},
        parameters={
            "ordering": updated_order["parameters"]["ordering"],
            "fulfillment": fulfillment_parameters_factory(
                customer_id="a-client-id",
                due_date=None,
                next_sync_date="2024-08-05",
                coterm_date="2024-08-04",
            ),
        },
    )

    assert mocked_update_order.mock_calls[0].args == (
        m_client,
        order["id"],
    )
    assert mocked_update_order.mock_calls[0].kwargs == {
        "parameters": {
            "fulfillment": fulfillment_parameters_factory(
                due_date="2012-02-13",
            ),
            "ordering": order["parameters"]["ordering"],
        },
    }

    assert mocked_update_order.mock_calls[1].args == (
        m_client,
        order["id"],
    )
    assert mocked_update_order.mock_calls[2].kwargs == {
        "externalIds": updated_order["externalIds"],
        "parameters": {
            "fulfillment": fulfillment_parameters_factory(
                customer_id="a-client-id",
                due_date=None,
                coterm_date="2024-08-04",
                next_sync_date="2024-08-05",
            ),
            "ordering": updated_order["parameters"]["ordering"],
        },
    }

    assert mocked_transfer.status == "synchronized"
    assert mocked_transfer.synchronized_at == datetime(2012, 1, 14, 12, 00, 1)
    assert mocked_transfer.mpt_order_id == order["id"]
    mocked_transfer.save.assert_called_once()

    assert mocked_get_template.mock_calls[0].args == (
        m_client,
        order["agreement"]["product"]["id"],
        MPT_ORDER_STATUS_PROCESSING,
        TEMPLATE_NAME_BULK_MIGRATE,
    )

    assert mocked_get_template.mock_calls[1].args == (
        m_client,
        order["agreement"]["product"]["id"],
        MPT_ORDER_STATUS_COMPLETED,
        TEMPLATE_NAME_BULK_MIGRATE,
    )

    mocked_adobe_client.update_subscription.assert_not_called()


@freeze_time("2012-01-14 12:00:01")
def test_fulfill_transfer_order_already_migrated_(
    mocker,
    order_factory,
    transfer_order_parameters_factory,
    fulfillment_parameters_factory,
    subscriptions_factory,
    adobe_transfer_factory,
    adobe_items_factory,
    adobe_authorizations_file,
    adobe_customer_factory,
    agreement,
    adobe_subscription_factory,
):
    mocked_get_template = mocker.patch(
        "adobe_vipm.flows.fulfillment.shared.get_product_template_or_default",
        side_effect=[{"id": "TPL-0000"}, {"id": "TPL-1111"}],
    )

    order_params = transfer_order_parameters_factory()
    order = order_factory(order_parameters=order_params)

    mocker.patch("adobe_vipm.flows.helpers.get_agreement", return_value=agreement)

    mocked_transfer = mocker.MagicMock()
    mocked_transfer.customer_id = "customer-id"
    mocked_transfer.transfer_id = "transfer-id"
    mocked_transfer.customer_benefits_3yc_status = STATUS_3YC_EXPIRED

    adobe_customer = adobe_customer_factory()

    adobe_customer_address = adobe_customer["companyProfile"]["address"]
    adobe_customer_contact = adobe_customer["companyProfile"]["contacts"][0]

    updated_order = order_factory(
        fulfillment_parameters=fulfillment_parameters_factory(
            customer_id="a-client-id",
            due_date="2025-01-01",
            next_sync_date="2024-08-05",
            coterm_date="2024-08-04",
        ),
        order_parameters=transfer_order_parameters_factory(
            company_name=adobe_customer["companyProfile"]["companyName"],
            address={
                "country": adobe_customer_address["country"],
                "state": adobe_customer_address["region"],
                "city": adobe_customer_address["city"],
                "addressLine1": adobe_customer_address["addressLine1"],
                "addressLine2": adobe_customer_address["addressLine2"],
                "postCode": adobe_customer_address["postalCode"],
            },
            contact={
                "firstName": adobe_customer_contact["firstName"],
                "lastName": adobe_customer_contact["lastName"],
                "email": adobe_customer_contact["email"],
                "phone": split_phone_number(
                    adobe_customer_contact.get("phoneNumber"),
                    adobe_customer_address["country"],
                ),
            },
        ),
        external_ids={"vendor": "transfer-id"},
    )

    m_client = mocker.MagicMock()

    mocked_get_transfer = mocker.patch(
        "adobe_vipm.flows.fulfillment.transfer.get_transfer_by_authorization_membership_or_customer",
        return_value=mocked_transfer,
    )

    mocker.patch(
        "adobe_vipm.flows.utils.get_product_onetime_items_by_ids",
        return_value=[],
    )

    mocker.patch(
        "adobe_vipm.flows.fulfillment.transfer.add_subscription",
        return_value=subscriptions_factory(commitment_date="2024-08-04")[0],
    )

    mocked_process_order = mocker.patch(
        "adobe_vipm.flows.fulfillment.shared.set_processing_template",
    )

    mocked_update_order = mocker.patch(
        "adobe_vipm.flows.fulfillment.shared.update_order",
    )

    mocker.patch("adobe_vipm.flows.fulfillment.shared.complete_order")

    transfer_items = adobe_items_factory(subscription_id="sub-id")

    adobe_transfer = adobe_transfer_factory(status=STATUS_PENDING, items=transfer_items)
    adobe_subscription = adobe_subscription_factory(
        status=STATUS_PENDING, current_quantity=170
    )

    mocked_adobe_client = mocker.MagicMock()
    mocked_adobe_client.get_transfer.return_value = adobe_transfer
    mocked_adobe_client.get_customer.return_value = adobe_customer
    mocked_adobe_client.get_subscription.return_value = adobe_subscription
    mocked_adobe_client.get_subscriptions.return_value = {
        "items": [adobe_subscription],
    }

    mocker.patch(
        "adobe_vipm.flows.fulfillment.transfer.get_adobe_client",
        return_value=mocked_adobe_client,
    )

    fulfill_order(m_client, order)

    membership_id_param = get_ordering_parameter(updated_order, PARAM_MEMBERSHIP_ID)

    mocked_get_transfer.assert_called_once_with(
        order["agreement"]["product"]["id"],
        adobe_authorizations_file["authorizations"][0]["authorization_id"],
        membership_id_param["value"],
    )

    mocked_process_order.assert_called_once_with(
        m_client,
        order["id"],
        {"id": "TPL-0000"},
    )

    assert mocked_update_order.mock_calls[1].args == (
        m_client,
        order["id"],
    )

    assert mocked_transfer.status == "synchronized"
    assert mocked_transfer.synchronized_at == datetime(2012, 1, 14, 12, 00, 1)
    assert mocked_transfer.mpt_order_id == order["id"]
    mocked_transfer.save.assert_called_once()

    assert mocked_get_template.mock_calls[0].args == (
        m_client,
        order["agreement"]["product"]["id"],
        MPT_ORDER_STATUS_PROCESSING,
        TEMPLATE_NAME_BULK_MIGRATE,
    )

    assert mocked_get_template.mock_calls[1].args == (
        m_client,
        order["agreement"]["product"]["id"],
        MPT_ORDER_STATUS_COMPLETED,
        TEMPLATE_NAME_BULK_MIGRATE,
    )

    mocked_adobe_client.update_subscription.assert_not_called()


def test_fulfill_transfer_order_migration_running(
    mocker,
    order_factory,
    transfer_order_parameters_factory,
    adobe_authorizations_file,
    agreement,
):
    mocker.patch(
        "adobe_vipm.flows.fulfillment.shared.get_product_template_or_default",
        return_value={"id": "TPL-964-112"},
    )

    order_params = transfer_order_parameters_factory()
    order = order_factory(order_parameters=order_params)

    mocker.patch("adobe_vipm.flows.helpers.get_agreement", return_value=agreement)

    mocked_transfer = mocker.MagicMock()
    mocked_transfer.status = "running"
    mocked_transfer.customer_id = "customer-id"
    mocked_transfer.transfer_id = "transfer-id"

    m_client = mocker.MagicMock()

    mocked_get_transfer = mocker.patch(
        "adobe_vipm.flows.fulfillment.transfer.get_transfer_by_authorization_membership_or_customer",
        return_value=mocked_transfer,
    )

    mocked_query_order = mocker.patch("adobe_vipm.flows.fulfillment.shared.query_order")

    mocker.patch(
        "adobe_vipm.flows.fulfillment.transfer.get_adobe_client",
    )

    fulfill_order(m_client, order)

    membership_param = get_ordering_parameter(order, PARAM_MEMBERSHIP_ID)

    mocked_get_transfer.assert_called_once_with(
        order["agreement"]["product"]["id"],
        adobe_authorizations_file["authorizations"][0]["authorization_id"],
        membership_param["value"],
    )

    param = get_ordering_parameter(order, PARAM_MEMBERSHIP_ID)
    order = set_ordering_parameter_error(
        order,
        PARAM_MEMBERSHIP_ID,
        ERR_ADOBE_MEMBERSHIP_ID.to_dict(
            title=param["name"],
            details="Migration in progress, retry later",
        ),
    )
    mocked_query_order.assert_called_once_with(
        m_client,
        order["id"],
        parameters=order["parameters"],
        template={"id": "TPL-964-112"},
    )


def test_fulfill_transfer_order_migration_synchronized(
    mocker,
    order_factory,
    transfer_order_parameters_factory,
    adobe_authorizations_file,
    agreement,
):
    mocker.patch(
        "adobe_vipm.flows.fulfillment.shared.get_product_template_or_default",
        return_value={"id": "TPL-964-112"},
    )

    order_params = transfer_order_parameters_factory()
    order = order_factory(order_parameters=order_params)

    mocker.patch("adobe_vipm.flows.helpers.get_agreement", return_value=agreement)

    mocked_transfer = mocker.MagicMock()
    mocked_transfer.status = "synchronized"
    mocked_transfer.customer_id = "customer-id"
    mocked_transfer.transfer_id = "transfer-id"

    m_client = mocker.MagicMock()

    mocked_get_transfer = mocker.patch(
        "adobe_vipm.flows.fulfillment.transfer.get_transfer_by_authorization_membership_or_customer",
        return_value=mocked_transfer,
    )

    mocked_fail_order = mocker.patch("adobe_vipm.flows.fulfillment.shared.fail_order")

    mocker.patch(
        "adobe_vipm.flows.fulfillment.transfer.get_adobe_client",
    )

    fulfill_order(m_client, order)

    membership_param = get_ordering_parameter(order, PARAM_MEMBERSHIP_ID)

    mocked_get_transfer.assert_called_once_with(
        order["agreement"]["product"]["id"],
        adobe_authorizations_file["authorizations"][0]["authorization_id"],
        membership_param["value"],
    )

    mocked_fail_order.assert_called_once_with(
        m_client,
        order["id"],
        "Membership has already been migrated.",
        parameters=order["parameters"],
    )


@freeze_time("2024-01-01")
def test_transfer_3yc_customer(
    mocker,
    agreement,
    order_factory,
    transfer_order_parameters_factory,
    fulfillment_parameters_factory,
    adobe_preview_transfer_factory,
    adobe_transfer_factory,
    adobe_items_factory,
    adobe_subscription_factory,
    adobe_customer_factory,
    adobe_commitment_factory,
    items_factory,
    subscriptions_factory,
):
    """
    Tests the processing of a transfer order which customer has 3YC including:
        * order creation
        * subscription creation
        * order completion
    """
    mocker.patch(
        "adobe_vipm.flows.fulfillment.shared.get_product_template_or_default",
        return_value={"id": "TPL-1111"},
    )
    mocker.patch(
        "adobe_vipm.flows.fulfillment.transfer.get_transfer_by_authorization_membership_or_customer",
        return_value=None,
    )
    mocker.patch("adobe_vipm.flows.helpers.get_agreement", return_value=agreement)

    adobe_transfer = adobe_transfer_factory(
        status=STATUS_PROCESSED,
        customer_id="a-client-id",
        items=adobe_items_factory(subscription_id="a-sub-id"),
    )
    adobe_3yc_commitment = adobe_commitment_factory(licenses=15, consumables=37)
    adobe_transfer_preview = adobe_preview_transfer_factory()
    adobe_customer = adobe_customer_factory(commitment=adobe_3yc_commitment)
    adobe_subscription = adobe_subscription_factory()

    mocked_adobe_client = mocker.MagicMock()
    mocked_adobe_client.preview_transfer.return_value = adobe_transfer_preview
    mocked_adobe_client.create_transfer.return_value = adobe_transfer
    mocked_adobe_client.get_customer.return_value = adobe_customer
    mocked_adobe_client.get_transfer.return_value = adobe_transfer
    mocked_adobe_client.get_subscription.return_value = adobe_subscription
    mocker.patch(
        "adobe_vipm.flows.fulfillment.transfer.get_adobe_client",
        return_value=mocked_adobe_client,
    )

    mocked_mpt_client = mocker.MagicMock()
    mocked_update_order = mocker.patch(
        "adobe_vipm.flows.fulfillment.shared.update_order"
    )
    subscription = subscriptions_factory(commitment_date="2024-01-01")[0]
    mocked_create_subscription = mocker.patch(
        "adobe_vipm.flows.fulfillment.shared.create_subscription",
        return_value=subscription,
    )
    mocker.patch(
        "adobe_vipm.flows.utils.get_product_onetime_items_by_ids",
        return_value=[],
    )

    mocked_complete_order = mocker.patch(
        "adobe_vipm.flows.fulfillment.shared.complete_order"
    )
    mocked_sync_agreement = mocker.patch(
        "adobe_vipm.flows.fulfillment.transfer.sync_agreements_by_agreement_ids"
    )

    order = order_factory(order_parameters=transfer_order_parameters_factory())

    fulfill_order(mocked_mpt_client, order)

    authorization_id = order["authorization"]["id"]
    adobe_customer_address = adobe_customer["companyProfile"]["address"]
    adobe_customer_contact = adobe_customer["companyProfile"]["contacts"][0]

    mocked_adobe_client.preview_transfer.assert_called_once_with(
        authorization_id,
        "a-membership-id",
    )

    assert mocked_update_order.mock_calls[0].args == (
        mocked_mpt_client,
        order["id"],
    )
    assert mocked_update_order.mock_calls[0].kwargs == {
        "parameters": {
            "fulfillment": fulfillment_parameters_factory(
                due_date="2024-01-31",
            ),
            "ordering": order["parameters"]["ordering"],
        },
    }

    assert mocked_update_order.mock_calls[1].args == (
        mocked_mpt_client,
        order["id"],
    )
    assert mocked_update_order.mock_calls[1].kwargs == {
        "externalIds": {
            "vendor": adobe_transfer["transferId"],
        },
    }
    assert mocked_update_order.mock_calls[2].args == (
        mocked_mpt_client,
        order["id"],
    )
    assert mocked_update_order.mock_calls[2].kwargs == {
        "externalIds": {
            "vendor": adobe_transfer["transferId"],
        },
        "parameters": {
            "fulfillment": fulfillment_parameters_factory(
                customer_id="a-client-id",
                due_date="2024-01-31",
                p3yc_enroll_status=adobe_3yc_commitment["status"],
                p3yc_start_date=adobe_3yc_commitment["startDate"],
                p3yc_end_date=adobe_3yc_commitment["endDate"],
            ),
            "ordering": transfer_order_parameters_factory(
                company_name=adobe_customer["companyProfile"]["companyName"],
                address={
                    "country": adobe_customer_address["country"],
                    "state": adobe_customer_address["region"],
                    "city": adobe_customer_address["city"],
                    "addressLine1": adobe_customer_address["addressLine1"],
                    "addressLine2": adobe_customer_address["addressLine2"],
                    "postCode": adobe_customer_address["postalCode"],
                },
                contact={
                    "firstName": adobe_customer_contact["firstName"],
                    "lastName": adobe_customer_contact["lastName"],
                    "email": adobe_customer_contact["email"],
                    "phone": split_phone_number(
                        adobe_customer_contact.get("phoneNumber"),
                        adobe_customer_address["country"],
                    ),
                },
                p3yc=None,
                p3yc_licenses="15",
                p3yc_consumables="37",
            ),
        },
    }

    assert mocked_update_order.mock_calls[3].args == (
        mocked_mpt_client,
        order["id"],
    )
    assert mocked_update_order.mock_calls[3].kwargs == {
        "parameters": {
            "fulfillment": fulfillment_parameters_factory(
                customer_id="a-client-id",
                due_date=None,
                p3yc_enroll_status=adobe_3yc_commitment["status"],
                p3yc_start_date=adobe_3yc_commitment["startDate"],
                p3yc_end_date=adobe_3yc_commitment["endDate"],
                next_sync_date="2024-01-02",
                coterm_date="2024-01-01",
            ),
            "ordering": transfer_order_parameters_factory(
                company_name=adobe_customer["companyProfile"]["companyName"],
                address={
                    "country": adobe_customer_address["country"],
                    "state": adobe_customer_address["region"],
                    "city": adobe_customer_address["city"],
                    "addressLine1": adobe_customer_address["addressLine1"],
                    "addressLine2": adobe_customer_address["addressLine2"],
                    "postCode": adobe_customer_address["postalCode"],
                },
                contact={
                    "firstName": adobe_customer_contact["firstName"],
                    "lastName": adobe_customer_contact["lastName"],
                    "email": adobe_customer_contact["email"],
                    "phone": split_phone_number(
                        adobe_customer_contact.get("phoneNumber"),
                        adobe_customer_address["country"],
                    ),
                },
                p3yc=None,
                p3yc_licenses="15",
                p3yc_consumables="37",
            ),
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
                    {
                        "externalId": "currentQuantity",
                        "value": str(adobe_subscription["currentQuantity"]),
                    },
                    {
                        "externalId": "renewalQuantity",
                        "value": str(
                            adobe_subscription["autoRenewal"]["renewalQuantity"]
                        ),
                    },
                    {
                        "externalId": "renewalDate",
                        "value": adobe_subscription["renewalDate"],
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
            "autoRenew": adobe_subscription["autoRenewal"]["enabled"],
        },
    )
    mocked_complete_order.assert_called_once_with(
        mocked_mpt_client,
        order["id"],
        {"id": "TPL-1111"},
        parameters={
            "fulfillment": fulfillment_parameters_factory(
                customer_id="a-client-id",
                due_date=None,
                p3yc_enroll_status=adobe_3yc_commitment["status"],
                p3yc_start_date=adobe_3yc_commitment["startDate"],
                p3yc_end_date=adobe_3yc_commitment["endDate"],
                next_sync_date="2024-01-02",
                coterm_date="2024-01-01",
            ),
            "ordering": transfer_order_parameters_factory(
                company_name=adobe_customer["companyProfile"]["companyName"],
                address={
                    "country": adobe_customer_address["country"],
                    "state": adobe_customer_address["region"],
                    "city": adobe_customer_address["city"],
                    "addressLine1": adobe_customer_address["addressLine1"],
                    "addressLine2": adobe_customer_address["addressLine2"],
                    "postCode": adobe_customer_address["postalCode"],
                },
                contact={
                    "firstName": adobe_customer_contact["firstName"],
                    "lastName": adobe_customer_contact["lastName"],
                    "email": adobe_customer_contact["email"],
                    "phone": split_phone_number(
                        adobe_customer_contact.get("phoneNumber"),
                        adobe_customer_address["country"],
                    ),
                },
                p3yc=None,
                p3yc_licenses="15",
                p3yc_consumables="37",
            ),
        },
    )
    mocked_adobe_client.get_transfer.assert_called_once_with(
        authorization_id, "a-membership-id", adobe_transfer["transferId"]
    )
    mocked_adobe_client.get_subscription.assert_called_once_with(
        authorization_id,
        "a-client-id",
        adobe_subscription["subscriptionId"],
    )
    mocked_sync_agreement.assert_called_once_with(
        mocked_mpt_client,
        [order["agreement"]["id"]],
        False,
    )


@freeze_time("2012-01-14 12:00:01")
def test_fulfill_transfer_order_already_migrated_all_items_expired_create_new_order(
    mocker,
    order_factory,
    items_factory,
    transfer_order_parameters_factory,
    fulfillment_parameters_factory,
    subscriptions_factory,
    adobe_transfer_factory,
    adobe_items_factory,
    adobe_authorizations_file,
    adobe_customer_factory,
    adobe_order_factory,
    agreement,
):
    order_params = transfer_order_parameters_factory()
    order = order_factory(order_parameters=order_params)

    mocker.patch("adobe_vipm.flows.helpers.get_agreement", return_value=agreement)

    mocked_transfer = mocker.MagicMock()
    mocked_transfer.membership_id = "membership-id"
    mocked_transfer.customer_id = "customer-id"
    mocked_transfer.transfer_id = "transfer-id"
    mocked_transfer.customer_benefits_3yc_status = None

    adobe_customer = adobe_customer_factory()

    adobe_customer_address = adobe_customer["companyProfile"]["address"]
    adobe_customer_contact = adobe_customer["companyProfile"]["contacts"][0]

    updated_order = order_factory(
        fulfillment_parameters=fulfillment_parameters_factory(
            customer_id="a-client-id",
            due_date="2012-02-13",
        ),
        order_parameters=transfer_order_parameters_factory(
            company_name=adobe_customer["companyProfile"]["companyName"],
            address={
                "country": adobe_customer_address["country"],
                "state": adobe_customer_address["region"],
                "city": adobe_customer_address["city"],
                "addressLine1": adobe_customer_address["addressLine1"],
                "addressLine2": adobe_customer_address["addressLine2"],
                "postCode": adobe_customer_address["postalCode"],
            },
            contact={
                "firstName": adobe_customer_contact["firstName"],
                "lastName": adobe_customer_contact["lastName"],
                "email": adobe_customer_contact["email"],
                "phone": split_phone_number(
                    adobe_customer_contact.get("phoneNumber"),
                    adobe_customer_address["country"],
                ),
            },
        ),
        external_ids={"vendor": "transfer-id"},
    )

    m_client = mocker.MagicMock()

    mocked_get_transfer = mocker.patch(
        "adobe_vipm.flows.fulfillment.transfer.get_transfer_by_authorization_membership_or_customer",
        return_value=mocked_transfer,
    )

    mocker.patch(
        "adobe_vipm.flows.utils.get_product_onetime_items_by_ids",
        return_value=items_factory(item_id=2, external_vendor_id="99999999CA"),
    )

    mocked_process_order = mocker.patch(
        "adobe_vipm.flows.fulfillment.shared.set_processing_template",
    )

    mocked_update_order = mocker.patch(
        "adobe_vipm.flows.fulfillment.shared.update_order",
    )
    mocker.patch(
        "adobe_vipm.flows.fulfillment.shared.get_product_template_or_default",
        side_effect=[{"id": "TPL-0000"}, {"id": "TPL-1111"}],
    )

    transfer_items = adobe_items_factory(
        subscription_id="sub-id",
        status=STATUS_INACTIVE_OR_GENERIC_FAILURE,
        offer_id="65304990CA",
    )

    adobe_transfer = adobe_transfer_factory(items=transfer_items)
    new_order = adobe_order_factory(order_type=ORDER_TYPE_NEW, status=STATUS_PENDING)

    mocked_adobe_client = mocker.MagicMock()
    mocked_adobe_client.get_transfer.return_value = adobe_transfer
    mocked_adobe_client.get_customer.return_value = adobe_customer

    adobe_preview_order = adobe_order_factory(ORDER_TYPE_PREVIEW)
    mocked_adobe_client.create_preview_order.return_value = adobe_preview_order
    mocked_adobe_client.create_new_order.return_value = new_order

    mocker.patch(
        "adobe_vipm.flows.fulfillment.transfer.get_adobe_client",
        return_value=mocked_adobe_client,
    )
    mocker.patch(
        "adobe_vipm.flows.helpers.get_adobe_client",
        return_value=mocked_adobe_client,
    )
    mocker.patch(
        "adobe_vipm.flows.fulfillment.shared.get_adobe_client",
        return_value=mocked_adobe_client,
    )

    fulfill_order(m_client, order)

    membership_id_param = get_ordering_parameter(updated_order, PARAM_MEMBERSHIP_ID)

    mocked_get_transfer.assert_called_once_with(
        order["agreement"]["product"]["id"],
        adobe_authorizations_file["authorizations"][0]["authorization_id"],
        membership_id_param["value"],
    )

    mocked_process_order.assert_called_once_with(
        m_client,
        order["id"],
        {"id": "TPL-0000"},
    )

    assert mocked_update_order.mock_calls[0].args == (
        m_client,
        order["id"],
    )
    assert mocked_update_order.mock_calls[0].kwargs == {
        "parameters": {
            "fulfillment": fulfillment_parameters_factory(
                due_date="2012-02-13",
            ),
            "ordering": order["parameters"]["ordering"],
        },
    }

    assert mocked_update_order.mock_calls[2].args == (
        m_client,
        order["id"],
    )
    assert mocked_update_order.mock_calls[2].kwargs == {
        "externalIds": {"vendor": new_order["orderId"]}
    }


@freeze_time("2012-01-14 12:00:01")
def test_update_transfer_status_step(
    mocker,
    order_factory,
    items_factory,
    transfer_order_parameters_factory,
    fulfillment_parameters_factory,
    subscriptions_factory,
    adobe_transfer_factory,
    adobe_items_factory,
    adobe_authorizations_file,
    adobe_customer_factory,
    adobe_order_factory,
    agreement,
):
    order_params = transfer_order_parameters_factory()
    order = order_factory(order_parameters=order_params)
    context = Context(
        order=order,
        authorization_id=order["authorization"]["id"],
        downsize_lines=order["lines"],
    )
    mocked_transfer = mocker.MagicMock()
    mocked_transfer.membership_id = "membership-id"
    mocked_transfer.customer_id = "customer-id"
    mocked_transfer.transfer_id = "transfer-id"
    mocked_transfer.customer_benefits_3yc_status = None

    mocked_client = mocker.MagicMock()
    mocked_next_step = mocker.MagicMock()

    step = UpdateTransferStatus(transfer=mocked_transfer, status=STATUS_SYNCHRONIZED)
    step(mocked_client, context, mocked_next_step)

    assert mocked_transfer.status == "synchronized"
    assert mocked_transfer.synchronized_at == datetime(2012, 1, 14, 12, 00, 1)
    assert mocked_transfer.mpt_order_id == order["id"]
    mocked_next_step.assert_called_once_with(mocked_client, context)
