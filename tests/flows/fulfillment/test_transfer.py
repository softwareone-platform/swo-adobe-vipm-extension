from datetime import date, datetime

import pytest
from freezegun import freeze_time

from adobe_vipm.adobe.constants import (
    ORDER_TYPE_NEW,
    ORDER_TYPE_PREVIEW,
    UNRECOVERABLE_TRANSFER_STATUSES,
    AdobeStatus,
    ThreeYearCommitmentStatus,
)
from adobe_vipm.adobe.errors import AdobeAPIError, AdobeError, AdobeHttpError
from adobe_vipm.airtable.models import (
    STATUS_GC_CREATED,
    STATUS_GC_ERROR,
    STATUS_GC_PENDING,
    STATUS_GC_TRANSFERRED,
    STATUS_SYNCHRONIZED,
)
from adobe_vipm.flows.constants import (
    ERR_ADOBE_MEMBERSHIP_ID,
    ERR_ADOBE_MEMBERSHIP_NOT_FOUND,
    ERR_ADOBE_TRANSFER_PREVIEW,
    ERR_MEMBERSHIP_HAS_BEEN_TRANSFERED,
    ERR_MEMBERSHIP_ITEMS_DONT_MATCH,
    ERR_UNEXPECTED_ADOBE_ERROR_STATUS,
    ERR_UPDATING_TRANSFER_ITEMS,
    ERR_VIPM_UNHANDLED_EXCEPTION,
    MPT_ORDER_STATUS_COMPLETED,
    MPT_ORDER_STATUS_PROCESSING,
    TEMPLATE_NAME_BULK_MIGRATE,
    TEMPLATE_NAME_TRANSFER,
    Param,
)
from adobe_vipm.flows.context import Context
from adobe_vipm.flows.fulfillment import fulfill_order
from adobe_vipm.flows.fulfillment.transfer import (
    SyncGCMainAgreement,
    UpdateTransferStatus,
)
from adobe_vipm.flows.utils import (
    get_ordering_parameter,
    set_ordering_parameter_error,
    split_phone_number,
)
from adobe_vipm.flows.utils.order import reset_order_error
from adobe_vipm.flows.utils.parameter import reset_ordering_parameters_error

pytestmark = pytest.mark.usefixtures("mock_adobe_config")


@pytest.fixture(autouse=True)
def mocked_send_mpt_notification(mocker):
    return mocker.patch("adobe_vipm.flows.fulfillment.shared.send_mpt_notification", spec=True)


@pytest.fixture(autouse=True)
def send_gc_mpt_notification(mocker):
    return mocker.patch("adobe_vipm.flows.fulfillment.transfer.send_gc_mpt_notification", spec=True)


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
    mocker.patch(
        "adobe_vipm.flows.fulfillment.transfer.get_gc_main_agreement",
        return_value=None,
    )
    mocker.patch(
        "adobe_vipm.flows.fulfillment.transfer.get_gc_agreement_deployments_by_main_agreement",
        return_value=None,
    )

    adobe_transfer = adobe_transfer_factory(
        status=AdobeStatus.PROCESSED.value,
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
        subscription_id="inactive-sub-id",
        status=AdobeStatus.INACTIVE_OR_GENERIC_FAILURE.value,
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
        "adobe_vipm.flows.utils.order.get_product_onetime_items_by_ids",
        return_value=items_factory(item_id=2, external_vendor_id="99999999CA"),
    )

    mocked_process_order = mocker.patch(
        "adobe_vipm.flows.fulfillment.shared.set_processing_template",
    )

    mocked_complete_order = mocker.patch("adobe_vipm.flows.fulfillment.shared.complete_order")
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
                        "value": str(adobe_subscription["autoRenewal"]["renewalQuantity"]),
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


@freeze_time("2024-01-01")
def test_transfer_with_no_profile_address(
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
    # TODO: For mocking without checking for calls, this could be refactored into one line through
    # @pytest.mark.usefixtures().
    mocker.patch(
        "adobe_vipm.flows.fulfillment.transfer.get_transfer_by_authorization_membership_or_customer",
        return_value=None,
    )
    mocker.patch("adobe_vipm.flows.helpers.get_agreement", return_value=agreement)
    mocker.patch(
        "adobe_vipm.flows.fulfillment.transfer.get_gc_main_agreement",
        return_value=None,
    )
    mocker.patch(
        "adobe_vipm.flows.fulfillment.transfer.get_gc_agreement_deployments_by_main_agreement",
        return_value=None,
    )

    adobe_transfer = adobe_transfer_factory(
        status=AdobeStatus.PROCESSED.value,
        customer_id="a-client-id",
        items=adobe_items_factory(subscription_id="a-sub-id")
        + adobe_items_factory(line_number=2, subscription_id="inactive-sub-id")
        + adobe_items_factory(
            line_number=3, offer_id="99999999CA01A12", subscription_id="one-time-sub-id"
        ),
    )

    adobe_transfer_preview = adobe_preview_transfer_factory()
    adobe_customer = adobe_customer_factory(company_profile_address_exists=False)
    adobe_subscription = adobe_subscription_factory()
    adobe_inactive_subscription = adobe_subscription_factory(
        subscription_id="inactive-sub-id",
        status=AdobeStatus.INACTIVE_OR_GENERIC_FAILURE.value,
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
        "adobe_vipm.flows.utils.order.get_product_onetime_items_by_ids",
        return_value=items_factory(item_id=2, external_vendor_id="99999999CA"),
    )

    mocked_process_order = mocker.patch(
        "adobe_vipm.flows.fulfillment.shared.set_processing_template",
    )

    mocked_complete_order = mocker.patch("adobe_vipm.flows.fulfillment.shared.complete_order")
    mocked_sync_agreement = mocker.patch(
        "adobe_vipm.flows.fulfillment.transfer.sync_agreements_by_agreement_ids"
    )

    fulfill_order(mocked_mpt_client, order)

    authorization_id = order["authorization"]["id"]
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
                contact={
                    "firstName": adobe_customer_contact["firstName"],
                    "lastName": adobe_customer_contact["lastName"],
                    "email": adobe_customer_contact["email"],
                    "phone": split_phone_number(
                        adobe_customer_contact.get("phoneNumber"),
                        "",
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
                coterm_date="2024-01-01",
            ),
            "ordering": transfer_order_parameters_factory(
                company_name=adobe_customer["companyProfile"]["companyName"],
                contact={
                    "firstName": adobe_customer_contact["firstName"],
                    "lastName": adobe_customer_contact["lastName"],
                    "email": adobe_customer_contact["email"],
                    "phone": split_phone_number(
                        adobe_customer_contact.get("phoneNumber"),
                        "",
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
                        "value": str(adobe_subscription["autoRenewal"]["renewalQuantity"]),
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
                coterm_date="2024-01-01",
            ),
            "ordering": transfer_order_parameters_factory(
                company_name=adobe_customer["companyProfile"]["companyName"],
                contact={
                    "firstName": adobe_customer_contact["firstName"],
                    "lastName": adobe_customer_contact["lastName"],
                    "email": adobe_customer_contact["email"],
                    "phone": split_phone_number(
                        adobe_customer_contact.get("phoneNumber"),
                        "",
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
    mocker.patch(
        "adobe_vipm.flows.fulfillment.transfer.get_gc_main_agreement",
        return_value=None,
    )
    mocker.patch(
        "adobe_vipm.flows.fulfillment.transfer.get_gc_agreement_deployments_by_main_agreement",
        return_value=None,
    )
    mocker.patch("adobe_vipm.flows.helpers.get_agreement", return_value=agreement)

    adobe_transfer = adobe_transfer_factory(status=AdobeStatus.PENDING.value)

    mocked_adobe_client = mocker.MagicMock()
    mocked_adobe_client.create_transfer.return_value = adobe_transfer
    mocked_adobe_client.get_transfer.return_value = adobe_transfer
    mocker.patch(
        "adobe_vipm.flows.fulfillment.transfer.get_adobe_client",
        return_value=mocked_adobe_client,
    )

    mocked_mpt_client = mocker.MagicMock()
    mocked_update_order = mocker.patch("adobe_vipm.flows.fulfillment.shared.update_order")
    mocked_complete_order = mocker.patch("adobe_vipm.flows.fulfillment.shared.complete_order")

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


@freeze_time("2026-01-01")
def test_transfer_reached_due_date(
    mocker,
    agreement,
    order_factory,
    transfer_order_parameters_factory,
    fulfillment_parameters_factory,
    adobe_transfer_factory,
):
    """
    Tests that transfer order when it reaches due date fails
    """
    mocker.patch(
        "adobe_vipm.flows.fulfillment.transfer.get_transfer_by_authorization_membership_or_customer",
        return_value=None,
    )
    mocker.patch(
        "adobe_vipm.flows.fulfillment.transfer.get_gc_main_agreement",
        return_value=None,
    )
    mocker.patch(
        "adobe_vipm.flows.fulfillment.transfer.get_gc_agreement_deployments_by_main_agreement",
        return_value=None,
    )
    mocker.patch("adobe_vipm.flows.helpers.get_agreement", return_value=agreement)

    adobe_transfer = adobe_transfer_factory(status=AdobeStatus.PENDING.value)

    mocked_adobe_client = mocker.MagicMock()
    mocked_adobe_client.create_transfer.return_value = adobe_transfer
    mocked_adobe_client.get_transfer.return_value = adobe_transfer
    mocker.patch(
        "adobe_vipm.flows.fulfillment.transfer.get_adobe_client",
        return_value=mocked_adobe_client,
    )

    mocked_mpt_client = mocker.MagicMock()
    mocked_update_order = mocker.patch("adobe_vipm.flows.fulfillment.shared.update_order")
    mocked_fail_order = mocker.patch("adobe_vipm.flows.fulfillment.shared.fail_order")

    order = order_factory(
        order_parameters=transfer_order_parameters_factory(),
        fulfillment_parameters=fulfillment_parameters_factory(
            due_date="2025-01-01",
        ),
        external_ids={"vendor": "a-transfer-id"},
    )

    fulfill_order(mocked_mpt_client, order)

    authorization_id = order["authorization"]["id"]

    mocked_update_order.assert_not_called()

    reason = "Due date is reached (2025-01-01)."
    mocked_fail_order.assert_called_once_with(
        mocked_mpt_client,
        order["id"],
        reason,
        ERR_VIPM_UNHANDLED_EXCEPTION.to_dict(error=reason),
    )
    mocked_adobe_client.get_transfer.assert_called_once_with(
        authorization_id, "a-membership-id", adobe_transfer["transferId"]
    )


def test_transfer_unexpected_status(
    mocker,
    agreement,
    order_factory,
    transfer_order_parameters_factory,
    adobe_transfer_factory,
    mock_mpt_client,
    mock_sync_agreements_by_agreement_ids,
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
    mocker.patch(
        "adobe_vipm.flows.fulfillment.transfer.get_gc_main_agreement",
        return_value=None,
    )
    mocker.patch(
        "adobe_vipm.flows.fulfillment.transfer.get_gc_agreement_deployments_by_main_agreement",
        return_value=None,
    )
    mocked_fail_order = mocker.patch("adobe_vipm.flows.fulfillment.shared.fail_order")

    order = order_factory(
        order_parameters=transfer_order_parameters_factory(),
        external_ids={"vendor": "a-transfer-id"},
    )

    fulfill_order(mock_mpt_client, order)

    mocked_fail_order.assert_called_once_with(
        mock_mpt_client,
        order["id"],
        ERR_UNEXPECTED_ADOBE_ERROR_STATUS.to_dict(status="9999"),
        parameters=order["parameters"],
    )
    mock_sync_agreements_by_agreement_ids.assert_called_once_with(
        mock_mpt_client, [agreement["id"]], dry_run=False, sync_prices=False
    )


def test_transfer_items_mismatch(
    mocker,
    agreement,
    order_factory,
    transfer_order_parameters_factory,
    adobe_preview_transfer_factory,
    adobe_items_factory,
    mock_mpt_client,
    mock_sync_agreements_by_agreement_ids,
):
    """
    Tests a transfer order when the items contained in the order don't match
    the subscriptions owned by a given membership id.
    """
    mocker.patch(
        "adobe_vipm.flows.fulfillment.transfer.get_transfer_by_authorization_membership_or_customer",
        return_value=None,
    )
    mocker.patch(
        "adobe_vipm.flows.fulfillment.transfer.get_gc_main_agreement",
        return_value=None,
    )
    mocker.patch(
        "adobe_vipm.flows.fulfillment.transfer.get_gc_agreement_deployments_by_main_agreement",
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

    mocked_fail_order = mocker.patch("adobe_vipm.flows.fulfillment.shared.fail_order")

    order = order_factory(order_parameters=transfer_order_parameters_factory())

    fulfill_order(mock_mpt_client, order)

    authorization_id = order["authorization"]["id"]

    mocked_adobe_client.preview_transfer.assert_called_once_with(
        authorization_id,
        "a-membership-id",
    )

    mocked_fail_order.assert_called_once_with(
        mock_mpt_client,
        order["id"],
        ERR_MEMBERSHIP_ITEMS_DONT_MATCH.to_dict(lines="99999999CA"),
        parameters=order["parameters"],
    )
    mock_sync_agreements_by_agreement_ids.assert_called_once_with(
        mock_mpt_client, [agreement["id"]], dry_run=False, sync_prices=False
    )


@pytest.mark.parametrize(
    "transfer_status",
    [
        AdobeStatus.TRANSFER_INVALID_MEMBERSHIP.value,
        AdobeStatus.TRANSFER_INVALID_MEMBERSHIP_OR_TRANSFER_IDS.value,
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
    mocker.patch(
        "adobe_vipm.flows.fulfillment.transfer.get_gc_main_agreement",
        return_value=None,
    )
    mocker.patch(
        "adobe_vipm.flows.fulfillment.transfer.get_gc_agreement_deployments_by_main_agreement",
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
    param = get_ordering_parameter(order, Param.MEMBERSHIP_ID.value)
    order = set_ordering_parameter_error(
        order,
        Param.MEMBERSHIP_ID.value,
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
        "adobe_vipm.flows.fulfillment.transfer.get_gc_main_agreement",
        return_value=None,
    )
    mocker.patch(
        "adobe_vipm.flows.fulfillment.transfer.get_gc_agreement_deployments_by_main_agreement",
        return_value=None,
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
    param = get_ordering_parameter(order, Param.MEMBERSHIP_ID.value)
    order = set_ordering_parameter_error(
        order,
        Param.MEMBERSHIP_ID.value,
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
    mock_sync_agreements_by_agreement_ids,
    mock_mpt_client,
):
    """
    Tests a transfer order when it cannot be processed.
    """
    mocker.patch(
        "adobe_vipm.flows.fulfillment.transfer.get_transfer_by_authorization_membership_or_customer",
        return_value=None,
    )
    mocker.patch(
        "adobe_vipm.flows.fulfillment.transfer.get_gc_main_agreement",
        return_value=None,
    )
    mocker.patch(
        "adobe_vipm.flows.fulfillment.transfer.get_gc_agreement_deployments_by_main_agreement",
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
    mocker.patch(
        "adobe_vipm.flows.fulfillment.transfer.get_gc_main_agreement",
        return_value=None,
    )
    mocker.patch(
        "adobe_vipm.flows.fulfillment.transfer.get_gc_agreement_deployments_by_main_agreement",
        return_value=None,
    )

    mocked_fail_order = mocker.patch("adobe_vipm.flows.fulfillment.shared.fail_order")

    order = order_factory(order_parameters=transfer_order_parameters_factory())

    fulfill_order(mock_mpt_client, order)

    authorization_id = order["authorization"]["id"]

    mocked_adobe_client.preview_transfer.assert_called_once_with(
        authorization_id,
        "a-membership-id",
    )
    mocked_fail_order.assert_called_once_with(
        mock_mpt_client,
        order["id"],
        ERR_ADOBE_TRANSFER_PREVIEW.to_dict(error=str(adobe_error)),
        parameters=order["parameters"],
    )
    mock_sync_agreements_by_agreement_ids.assert_called_once_with(
        mock_mpt_client, [agreement["id"]], dry_run=False, sync_prices=False
    )


def test_create_transfer_fail(
    mocker,
    agreement,
    order_factory,
    transfer_order_parameters_factory,
    adobe_preview_transfer_factory,
    mock_mpt_client,
    mock_sync_agreements_by_agreement_ids,
):
    """
    Tests generic failure on transfer order creation.
    """
    mocker.patch(
        "adobe_vipm.flows.fulfillment.transfer.get_transfer_by_authorization_membership_or_customer",
        return_value=None,
    )
    mocker.patch(
        "adobe_vipm.flows.fulfillment.transfer.get_gc_main_agreement",
        return_value=None,
    )
    mocker.patch(
        "adobe_vipm.flows.fulfillment.transfer.get_gc_agreement_deployments_by_main_agreement",
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

    mocked_fail_order = mocker.patch("adobe_vipm.flows.fulfillment.shared.fail_order")

    order = order_factory(order_parameters=transfer_order_parameters_factory())

    fulfill_order(mock_mpt_client, order)

    order = reset_order_error(reset_ordering_parameters_error(order))

    mocked_fail_order.assert_called_once_with(
        mock_mpt_client,
        order["id"],
        ERR_VIPM_UNHANDLED_EXCEPTION.to_dict(error="Unexpected error"),
        parameters=order["parameters"],
    )
    mock_sync_agreements_by_agreement_ids.assert_called_once_with(
        mock_mpt_client, [agreement["id"]], dry_run=False, sync_prices=False
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
    mocker.patch(
        "adobe_vipm.flows.fulfillment.transfer.get_gc_main_agreement",
        return_value=None,
    )
    mocker.patch(
        "adobe_vipm.flows.fulfillment.transfer.get_gc_agreement_deployments_by_main_agreement",
        return_value=None,
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
        "adobe_vipm.flows.utils.order.get_product_onetime_items_by_ids",
        return_value=items_factory(item_id=2, external_vendor_id="99999999CA"),
    )
    product_items = items_factory()
    mocker.patch(
        "adobe_vipm.flows.fulfillment.transfer.get_product_items_by_skus",
        return_value=product_items,
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

    mocked_complete_order = mocker.patch("adobe_vipm.flows.fulfillment.shared.complete_order")

    transfer_items = adobe_items_factory(subscription_id="sub-id")

    adobe_transfer = adobe_transfer_factory(items=transfer_items)
    adobe_subscription = adobe_subscription_factory(current_quantity=170, subscription_id="sub-id")

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

    membership_id_param = get_ordering_parameter(updated_order, Param.MEMBERSHIP_ID.value)

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
def test_fulfill_transfer_order_with_no_profile_address_already_migrated(
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
    mocker.patch(
        "adobe_vipm.flows.fulfillment.transfer.get_gc_main_agreement",
        return_value=None,
    )
    mocker.patch(
        "adobe_vipm.flows.fulfillment.transfer.get_gc_agreement_deployments_by_main_agreement",
        return_value=None,
    )

    order_params = transfer_order_parameters_factory()
    order = order_factory(order_parameters=order_params)

    mocker.patch("adobe_vipm.flows.helpers.get_agreement", return_value=agreement)

    mocked_transfer = mocker.MagicMock()
    mocked_transfer.membership_id = "membership-id"
    mocked_transfer.customer_id = "customer-id"
    mocked_transfer.transfer_id = "transfer-id"
    mocked_transfer.customer_benefits_3yc_status = None

    adobe_customer = adobe_customer_factory(company_profile_address_exists=False)

    adobe_customer_contact = adobe_customer["companyProfile"]["contacts"][0]

    updated_order = order_factory(
        fulfillment_parameters=fulfillment_parameters_factory(
            customer_id="a-client-id",
            due_date="2012-02-13",
        ),
        order_parameters=transfer_order_parameters_factory(
            company_name=adobe_customer["companyProfile"]["companyName"],
            contact={
                "firstName": adobe_customer_contact["firstName"],
                "lastName": adobe_customer_contact["lastName"],
                "email": adobe_customer_contact["email"],
                "phone": split_phone_number(
                    adobe_customer_contact.get("phoneNumber"),
                    "",
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
        "adobe_vipm.flows.utils.order.get_product_onetime_items_by_ids",
        return_value=items_factory(item_id=2, external_vendor_id="99999999CA"),
    )
    product_items = items_factory()
    mocker.patch(
        "adobe_vipm.flows.fulfillment.transfer.get_product_items_by_skus",
        return_value=product_items,
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

    mocked_complete_order = mocker.patch("adobe_vipm.flows.fulfillment.shared.complete_order")

    transfer_items = adobe_items_factory(subscription_id="sub-id")

    adobe_transfer = adobe_transfer_factory(items=transfer_items)
    adobe_subscription = adobe_subscription_factory(current_quantity=170, subscription_id="sub-id")

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

    membership_id_param = get_ordering_parameter(updated_order, Param.MEMBERSHIP_ID.value)

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
    mock_mpt_client,
    mock_sync_agreements_by_agreement_ids,
):
    mocker.patch(
        "adobe_vipm.flows.fulfillment.shared.get_product_template_or_default",
        side_effect=[{"id": "TPL-0000"}, {"id": "TPL-1111"}],
    )
    mocker.patch(
        "adobe_vipm.flows.fulfillment.transfer.get_gc_main_agreement",
        return_value=None,
    )
    mocker.patch(
        "adobe_vipm.flows.fulfillment.transfer.get_gc_agreement_deployments_by_main_agreement",
        return_value=None,
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
    mocker.patch(
        "adobe_vipm.flows.fulfillment.transfer.get_transfer_by_authorization_membership_or_customer",
        return_value=mocked_transfer,
    )

    mocker.patch(
        "adobe_vipm.flows.utils.order.get_product_onetime_items_by_ids",
        return_value=items_factory(item_id=2, external_vendor_id="99999999CA"),
    )

    mocked_process_order = mocker.patch(
        "adobe_vipm.flows.fulfillment.shared.set_processing_template",
    )

    product_items = items_factory()
    mocker.patch(
        "adobe_vipm.flows.fulfillment.transfer.get_product_items_by_skus",
        return_value=product_items,
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

    fulfill_order(mock_mpt_client, order)

    mocked_process_order.assert_called_once_with(
        mock_mpt_client,
        order["id"],
        {"id": "TPL-0000"},
    )
    mocked_fail_order.assert_called_once_with(
        mock_mpt_client,
        order["id"],
        ERR_UPDATING_TRANSFER_ITEMS.to_dict(),
        parameters=order["parameters"],
    )

    assert mocked_update_order.mock_calls[0].args == (
        mock_mpt_client,
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
    mock_sync_agreements_by_agreement_ids.assert_called_once_with(
        mock_mpt_client, [agreement["id"]], dry_run=False, sync_prices=False
    )


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
    items_factory,
):
    mocked_get_template = mocker.patch(
        "adobe_vipm.flows.fulfillment.shared.get_product_template_or_default",
        side_effect=[{"id": "TPL-0000"}, {"id": "TPL-1111"}],
    )
    mocker.patch(
        "adobe_vipm.flows.fulfillment.transfer.get_gc_main_agreement",
        return_value=None,
    )
    mocker.patch(
        "adobe_vipm.flows.fulfillment.transfer.get_gc_agreement_deployments_by_main_agreement",
        return_value=None,
    )

    order_params = transfer_order_parameters_factory()
    order = order_factory(order_parameters=order_params)

    mocker.patch("adobe_vipm.flows.helpers.get_agreement", return_value=agreement)

    mocked_transfer = mocker.MagicMock()
    mocked_transfer.customer_id = "customer-id"
    mocked_transfer.transfer_id = "transfer-id"
    mocked_transfer.customer_benefits_3yc_status = ThreeYearCommitmentStatus.COMMITTED.value

    adobe_customer = adobe_customer_factory()

    adobe_customer_address = adobe_customer["companyProfile"]["address"]
    adobe_customer_contact = adobe_customer["companyProfile"]["contacts"][0]

    updated_order = order_factory(
        fulfillment_parameters=fulfillment_parameters_factory(
            customer_id="a-client-id",
            due_date="2012-02-14",
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
        "adobe_vipm.flows.utils.order.get_product_onetime_items_by_ids",
        return_value=[],
    )
    product_items = items_factory()
    mocker.patch(
        "adobe_vipm.flows.fulfillment.transfer.get_product_items_by_skus",
        return_value=product_items,
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

    mocked_complete_order = mocker.patch("adobe_vipm.flows.fulfillment.shared.complete_order")

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

    membership_id_param = get_ordering_parameter(updated_order, Param.MEMBERSHIP_ID.value)

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
    items_factory,
):
    mocked_get_template = mocker.patch(
        "adobe_vipm.flows.fulfillment.shared.get_product_template_or_default",
        side_effect=[{"id": "TPL-0000"}, {"id": "TPL-1111"}],
    )

    order_params = transfer_order_parameters_factory()
    order = order_factory(order_parameters=order_params)

    mocker.patch("adobe_vipm.flows.helpers.get_agreement", return_value=agreement)
    mocker.patch(
        "adobe_vipm.flows.fulfillment.transfer.get_gc_main_agreement",
        return_value=None,
    )
    mocker.patch(
        "adobe_vipm.flows.fulfillment.transfer.get_gc_agreement_deployments_by_main_agreement",
        return_value=None,
    )
    product_items = items_factory()
    mocker.patch(
        "adobe_vipm.flows.fulfillment.transfer.get_product_items_by_skus",
        return_value=product_items,
    )

    mocked_transfer = mocker.MagicMock()
    mocked_transfer.customer_id = "customer-id"
    mocked_transfer.transfer_id = "transfer-id"
    mocked_transfer.customer_benefits_3yc_status = ThreeYearCommitmentStatus.EXPIRED.value

    adobe_customer = adobe_customer_factory()

    adobe_customer_address = adobe_customer["companyProfile"]["address"]
    adobe_customer_contact = adobe_customer["companyProfile"]["contacts"][0]

    updated_order = order_factory(
        fulfillment_parameters=fulfillment_parameters_factory(
            customer_id="a-client-id",
            due_date="2025-01-01",
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
        "adobe_vipm.flows.utils.order.get_product_onetime_items_by_ids",
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

    adobe_transfer = adobe_transfer_factory(status=AdobeStatus.PENDING.value, items=transfer_items)
    adobe_subscription = adobe_subscription_factory(
        status=AdobeStatus.PENDING.value, current_quantity=170
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

    membership_id_param = get_ordering_parameter(updated_order, Param.MEMBERSHIP_ID.value)

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
    mocker.patch(
        "adobe_vipm.flows.fulfillment.transfer.get_gc_main_agreement",
        return_value=None,
    )
    mocker.patch(
        "adobe_vipm.flows.fulfillment.transfer.get_gc_agreement_deployments_by_main_agreement",
        return_value=None,
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

    membership_param = get_ordering_parameter(order, Param.MEMBERSHIP_ID.value)

    mocked_get_transfer.assert_called_once_with(
        order["agreement"]["product"]["id"],
        adobe_authorizations_file["authorizations"][0]["authorization_id"],
        membership_param["value"],
    )

    param = get_ordering_parameter(order, Param.MEMBERSHIP_ID.value)
    order = set_ordering_parameter_error(
        order,
        Param.MEMBERSHIP_ID.value,
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
    mock_sync_agreements_by_agreement_ids,
):
    mocker.patch(
        "adobe_vipm.flows.fulfillment.shared.get_product_template_or_default",
        return_value={"id": "TPL-964-112"},
    )

    mocker.patch(
        "adobe_vipm.flows.fulfillment.transfer.get_gc_main_agreement",
        return_value=None,
    )
    mocker.patch(
        "adobe_vipm.flows.fulfillment.transfer.get_gc_agreement_deployments_by_main_agreement",
        return_value=None,
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

    membership_param = get_ordering_parameter(order, Param.MEMBERSHIP_ID.value)

    mocked_get_transfer.assert_called_once_with(
        order["agreement"]["product"]["id"],
        adobe_authorizations_file["authorizations"][0]["authorization_id"],
        membership_param["value"],
    )

    mocked_fail_order.assert_called_once_with(
        m_client,
        order["id"],
        ERR_MEMBERSHIP_HAS_BEEN_TRANSFERED.to_dict(),
        parameters=order["parameters"],
    )
    mock_sync_agreements_by_agreement_ids.assert_called_once_with(
        m_client, [agreement["id"]], dry_run=False, sync_prices=False
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
    mocker.patch(
        "adobe_vipm.flows.fulfillment.transfer.get_gc_main_agreement",
        return_value=None,
    )
    mocker.patch(
        "adobe_vipm.flows.fulfillment.transfer.get_gc_agreement_deployments_by_main_agreement",
        return_value=None,
    )

    adobe_transfer = adobe_transfer_factory(
        status=AdobeStatus.PROCESSED.value,
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
    mocked_update_order = mocker.patch("adobe_vipm.flows.fulfillment.shared.update_order")
    subscription = subscriptions_factory(commitment_date="2024-01-01")[0]
    mocked_create_subscription = mocker.patch(
        "adobe_vipm.flows.fulfillment.shared.create_subscription",
        return_value=subscription,
    )
    mocker.patch(
        "adobe_vipm.flows.utils.order.get_product_onetime_items_by_ids",
        return_value=[],
    )

    mocked_complete_order = mocker.patch("adobe_vipm.flows.fulfillment.shared.complete_order")
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
                        "value": str(adobe_subscription["autoRenewal"]["renewalQuantity"]),
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


@freeze_time("2024-01-01")
def test_transfer_3yc_customer_with_no_profile_address(
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
    mocker.patch(
        "adobe_vipm.flows.fulfillment.transfer.get_gc_main_agreement",
        return_value=None,
    )
    mocker.patch(
        "adobe_vipm.flows.fulfillment.transfer.get_gc_agreement_deployments_by_main_agreement",
        return_value=None,
    )

    adobe_transfer = adobe_transfer_factory(
        status=AdobeStatus.PROCESSED.value,
        customer_id="a-client-id",
        items=adobe_items_factory(subscription_id="a-sub-id"),
    )
    adobe_3yc_commitment = adobe_commitment_factory(licenses=15, consumables=37)
    adobe_transfer_preview = adobe_preview_transfer_factory()
    adobe_customer = adobe_customer_factory(
        commitment=adobe_3yc_commitment, company_profile_address_exists=False
    )
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
    mocked_update_order = mocker.patch("adobe_vipm.flows.fulfillment.shared.update_order")
    subscription = subscriptions_factory(commitment_date="2024-01-01")[0]
    mocked_create_subscription = mocker.patch(
        "adobe_vipm.flows.fulfillment.shared.create_subscription",
        return_value=subscription,
    )
    mocker.patch(
        "adobe_vipm.flows.utils.order.get_product_onetime_items_by_ids",
        return_value=[],
    )

    mocked_complete_order = mocker.patch("adobe_vipm.flows.fulfillment.shared.complete_order")
    mocked_sync_agreement = mocker.patch(
        "adobe_vipm.flows.fulfillment.transfer.sync_agreements_by_agreement_ids"
    )

    order = order_factory(order_parameters=transfer_order_parameters_factory())

    fulfill_order(mocked_mpt_client, order)

    authorization_id = order["authorization"]["id"]
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
                contact={
                    "firstName": adobe_customer_contact["firstName"],
                    "lastName": adobe_customer_contact["lastName"],
                    "email": adobe_customer_contact["email"],
                    "phone": split_phone_number(
                        adobe_customer_contact.get("phoneNumber"),
                        "",
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
                coterm_date="2024-01-01",
            ),
            "ordering": transfer_order_parameters_factory(
                company_name=adobe_customer["companyProfile"]["companyName"],
                contact={
                    "firstName": adobe_customer_contact["firstName"],
                    "lastName": adobe_customer_contact["lastName"],
                    "email": adobe_customer_contact["email"],
                    "phone": split_phone_number(
                        adobe_customer_contact.get("phoneNumber"),
                        "",
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
                        "value": str(adobe_subscription["autoRenewal"]["renewalQuantity"]),
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
                coterm_date="2024-01-01",
            ),
            "ordering": transfer_order_parameters_factory(
                company_name=adobe_customer["companyProfile"]["companyName"],
                contact={
                    "firstName": adobe_customer_contact["firstName"],
                    "lastName": adobe_customer_contact["lastName"],
                    "email": adobe_customer_contact["email"],
                    "phone": split_phone_number(
                        adobe_customer_contact.get("phoneNumber"),
                        "",
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
    product_items = items_factory()
    mocker.patch(
        "adobe_vipm.flows.fulfillment.transfer.get_product_items_by_skus",
        return_value=product_items,
    )
    mocker.patch(
        "adobe_vipm.flows.fulfillment.transfer.get_gc_main_agreement",
        return_value=None,
    )
    mocker.patch(
        "adobe_vipm.flows.fulfillment.transfer.get_gc_agreement_deployments_by_main_agreement",
        return_value=None,
    )

    mocker.patch(
        "adobe_vipm.flows.utils.order.get_product_onetime_items_by_ids",
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
        status=AdobeStatus.INACTIVE_OR_GENERIC_FAILURE.value,
        offer_id="65304990CA",
    )

    adobe_transfer = adobe_transfer_factory(items=transfer_items)
    new_order = adobe_order_factory(order_type=ORDER_TYPE_NEW, status=AdobeStatus.PENDING.value)

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

    membership_id_param = get_ordering_parameter(updated_order, Param.MEMBERSHIP_ID.value)

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
def test_fulfill_transfer_order_already_migrated_empty_adobe_items(
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
    mock_get_product_items_by_skus = mocker.patch(
        "adobe_vipm.flows.fulfillment.transfer.get_product_items_by_skus",
    )
    mocker.patch(
        "adobe_vipm.flows.fulfillment.transfer.get_gc_main_agreement",
        return_value=None,
    )
    mocker.patch(
        "adobe_vipm.flows.fulfillment.transfer.get_gc_agreement_deployments_by_main_agreement",
        return_value=None,
    )

    mocker.patch(
        "adobe_vipm.flows.utils.order.get_product_onetime_items_by_ids",
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

    adobe_transfer = adobe_transfer_factory()
    adobe_transfer["lineItems"] = []
    new_order = adobe_order_factory(order_type=ORDER_TYPE_NEW, status=AdobeStatus.PENDING.value)

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

    mock_get_product_items_by_skus.assert_not_called()

    membership_id_param = get_ordering_parameter(updated_order, Param.MEMBERSHIP_ID.value)

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


@freeze_time("2024-01-01")
def test_transfer_gc_account_all_deployments_created(
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

    mocked_gc_main_agreement = mocker.MagicMock()
    mocked_gc_main_agreement.main_agreement_id = "main-agreement-id"
    mocked_gc_main_agreement.status = STATUS_GC_PENDING

    mocked_gc_agreement_deployments_by_main_agreement = mocker.MagicMock()
    mocked_gc_agreement_deployments_by_main_agreement.status = STATUS_GC_CREATED
    mocked_gc_agreement_deployments_by_main_agreement.deployment_id = "deployment-id"

    mocked_get_gc_main_agreement = mocker.patch(
        "adobe_vipm.flows.fulfillment.transfer.get_gc_main_agreement",
        return_value=mocked_gc_main_agreement,
    )
    mocked_get_gc_agreement_deployments_by_main_agreement = mocker.patch(
        "adobe_vipm.flows.fulfillment.transfer.get_gc_agreement_deployments_by_main_agreement",
        return_value=[mocked_gc_agreement_deployments_by_main_agreement],
    )

    adobe_transfer = adobe_transfer_factory(
        status=AdobeStatus.PROCESSED.value,
        customer_id="a-client-id",
        items=adobe_items_factory(subscription_id="a-sub-id")
        + adobe_items_factory(line_number=2, subscription_id="inactive-sub-id")
        + adobe_items_factory(
            line_number=3, offer_id="99999999CA01A12", subscription_id="one-time-sub-id"
        ),
    )

    adobe_transfer_preview = adobe_preview_transfer_factory()
    adobe_customer = adobe_customer_factory(global_sales_enabled=True)
    adobe_subscription = adobe_subscription_factory()
    adobe_inactive_subscription = adobe_subscription_factory(
        subscription_id="inactive-sub-id", status=AdobeStatus.INACTIVE_OR_GENERIC_FAILURE.value
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
    mocked_adobe_client.get_customer_deployments_active_status.return_value = [
        {
            "deploymentId": "deployment-id",
            "status": "1000",
            "companyProfile": {"address": {"country": "DE"}},
        }
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
        "adobe_vipm.flows.utils.order.get_product_onetime_items_by_ids",
        return_value=items_factory(item_id=2, external_vendor_id="99999999CA"),
    )

    mocked_process_order = mocker.patch(
        "adobe_vipm.flows.fulfillment.shared.set_processing_template",
    )

    mocked_complete_order = mocker.patch("adobe_vipm.flows.fulfillment.shared.complete_order")
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
                deployments=["deployment-id - DE"],
                global_customer="Yes",
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
                coterm_date="2024-01-01",
                deployments=["deployment-id - DE"],
                global_customer="Yes",
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
                        "value": str(adobe_subscription["autoRenewal"]["renewalQuantity"]),
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
                coterm_date="2024-01-01",
                deployments=["deployment-id - DE"],
                global_customer="Yes",
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
    mocked_get_gc_agreement_deployments_by_main_agreement()
    mocked_get_gc_main_agreement.assert_called_once_with(
        "PRD-1111-1111", "AUT-1234-4567", "a-membership-id"
    )


@freeze_time("2024-01-01")
def test_transfer_gc_account_no_deployments(
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

    mocked_gc_main_agreement = mocker.MagicMock()
    mocked_gc_main_agreement.main_agreement_id = "main-agreement-id"
    mocked_gc_main_agreement.status = STATUS_GC_PENDING

    mocked_get_gc_main_agreement = mocker.patch(
        "adobe_vipm.flows.fulfillment.transfer.get_gc_main_agreement",
        return_value=mocked_gc_main_agreement,
    )

    mocked_get_gc_agreement_deployments_by_main_agreement = mocker.patch(
        "adobe_vipm.flows.fulfillment.transfer.get_gc_agreement_deployments_by_main_agreement",
        return_value=[],
    )

    adobe_transfer = adobe_transfer_factory(
        status=AdobeStatus.PROCESSED.value,
        customer_id="a-client-id",
        items=adobe_items_factory(subscription_id="a-sub-id")
        + adobe_items_factory(line_number=2, subscription_id="inactive-sub-id")
        + adobe_items_factory(
            line_number=3, offer_id="99999999CA01A12", subscription_id="one-time-sub-id"
        ),
    )

    adobe_transfer_preview = adobe_preview_transfer_factory()
    adobe_customer = adobe_customer_factory(global_sales_enabled=True)
    adobe_subscription = adobe_subscription_factory()
    adobe_inactive_subscription = adobe_subscription_factory(
        subscription_id="inactive-sub-id", status=AdobeStatus.INACTIVE_OR_GENERIC_FAILURE.value
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
    mocked_adobe_client.get_customer_deployments_active_status.return_value = []
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
        "adobe_vipm.flows.utils.order.get_product_onetime_items_by_ids",
        return_value=items_factory(item_id=2, external_vendor_id="99999999CA"),
    )

    mocked_process_order = mocker.patch(
        "adobe_vipm.flows.fulfillment.shared.set_processing_template",
    )

    mocked_complete_order = mocker.patch("adobe_vipm.flows.fulfillment.shared.complete_order")
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
    order_result = {
        "externalIds": {
            "vendor": adobe_transfer["transferId"],
        },
        "parameters": {
            "fulfillment": fulfillment_parameters_factory(
                customer_id="a-client-id",
                due_date="2024-01-31",
                global_customer="Yes",
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

    order_result = reset_order_error(reset_ordering_parameters_error(order_result))
    assert mocked_update_order.mock_calls[2].kwargs.get("parameters") == order_result.get(
        "parameters"
    )

    assert mocked_update_order.mock_calls[3].args == (
        mocked_mpt_client,
        order["id"],
    )

    order_result = {
        "parameters": {
            "fulfillment": fulfillment_parameters_factory(
                customer_id="a-client-id",
                coterm_date="2024-01-01",
                global_customer="Yes",
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
    order_result = reset_order_error(reset_ordering_parameters_error(order_result))

    assert mocked_update_order.mock_calls[3].kwargs.get("parameters") == order_result.get(
        "parameters"
    )

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
                        "value": str(adobe_subscription["autoRenewal"]["renewalQuantity"]),
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
                coterm_date="2024-01-01",
                deployments=[],
                global_customer="Yes",
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
    assert mocked_get_gc_main_agreement.mock_calls[0].args == (
        "PRD-1111-1111",
        "AUT-1234-4567",
        "a-membership-id",
    )
    mocked_get_gc_agreement_deployments_by_main_agreement.assert_called_once_with(
        "PRD-1111-1111", "AGR-2119-4550-8674-5962"
    )


@freeze_time("2024-01-01")
def test_transfer_gc_account_create_deployments(
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
    mocker.patch(
        "adobe_vipm.flows.fulfillment.transfer.get_transfer_by_authorization_membership_or_customer",
        return_value=None,
    )
    mocker.patch("adobe_vipm.flows.helpers.get_agreement", return_value=agreement)

    mocked_get_gc_main_agreement = mocker.patch(
        "adobe_vipm.flows.fulfillment.transfer.get_gc_main_agreement",
        return_value=None,
    )
    mocked_create_gc_main_agreement = mocker.patch(
        "adobe_vipm.flows.fulfillment.transfer.create_gc_main_agreement",
        return_value=None,
    )
    mocked_get_gc_agreement_deployments_by_main_agreement = mocker.patch(
        "adobe_vipm.flows.fulfillment.transfer.get_gc_agreement_deployments_by_main_agreement",
        return_value=[],
    )
    mocked_create_gc_agreement_deployments = mocker.patch(
        "adobe_vipm.flows.fulfillment.transfer.create_gc_agreement_deployments",
        return_value=None,
    )
    mocked_get_agreement_deployment_view_link = mocker.patch(
        "adobe_vipm.flows.fulfillment.transfer.get_agreement_deployment_view_link",
        return_value="link",
    )
    mocker.patch(
        "adobe_vipm.flows.fulfillment.transfer.send_warning",
        return_value=None,
    )

    adobe_transfer = adobe_transfer_factory(
        status=AdobeStatus.PROCESSED.value,
        customer_id="a-client-id",
        items=adobe_items_factory(subscription_id="a-sub-id")
        + adobe_items_factory(line_number=2, subscription_id="inactive-sub-id")
        + adobe_items_factory(
            line_number=3, offer_id="99999999CA01A12", subscription_id="one-time-sub-id"
        ),
    )

    adobe_transfer_preview = adobe_preview_transfer_factory()
    adobe_customer = adobe_customer_factory(global_sales_enabled=True)
    adobe_subscription = adobe_subscription_factory()
    adobe_inactive_subscription = adobe_subscription_factory(
        subscription_id="inactive-sub-id", status=AdobeStatus.INACTIVE_OR_GENERIC_FAILURE.value
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
    mocked_adobe_client.get_customer_deployments_active_status.return_value = [
        {
            "deploymentId": "deployment-id",
            "status": "1000",
            "companyProfile": {"address": {"country": "DE"}},
        }
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

    fulfill_order(mocked_mpt_client, order)
    authorization_id = order["authorization"]["id"]
    mocked_adobe_client.preview_transfer.assert_called_once_with(
        authorization_id,
        "a-membership-id",
    )

    assert mocked_update_order.mock_calls[1].kwargs == {
        "externalIds": {
            "vendor": adobe_transfer["transferId"],
        }
    }

    mocked_adobe_client.get_transfer.assert_called_once_with(
        authorization_id, "a-membership-id", adobe_transfer["transferId"]
    )
    gc_main_agreement = {
        "membership_id": "membership-id",
        "authorization_uk": "AUT-1234-4567",
        "main_agreement_id": "AGR-2119-4550-8674-5962",
        "transfer_id": "a-transfer-id",
        "customer_id": "a-client-id",
        "status": "pending",
        "error_description": "",
    }
    mocked_get_gc_main_agreement.assert_called_once_with(
        "PRD-1111-1111", "AUT-1234-4567", "a-membership-id"
    )
    mocked_create_gc_main_agreement.assert_called_once_with("PRD-1111-1111", gc_main_agreement)
    mocked_get_agreement_deployment_view_link.assert_called_once_with(
        "PRD-1111-1111",
    )
    mocked_get_gc_agreement_deployments_by_main_agreement.assert_called_once_with(
        "PRD-1111-1111", "AGR-2119-4550-8674-5962"
    )
    gc_agreement_deployments = [
        {
            "deployment_id": "deployment-id",
            "status": "pending",
            "customer_id": "a-client-id",
            "product_id": "PRD-1111-1111",
            "main_agreement_id": "AGR-2119-4550-8674-5962",
            "account_id": "",
            "seller_id": "",
            "membership_id": "membership-id",
            "transfer_id": "a-transfer-id",
            "deployment_currency": "",
            "deployment_country": "DE",
        }
    ]

    mocked_create_gc_agreement_deployments.assert_called_once_with(
        "PRD-1111-1111", gc_agreement_deployments
    )


@freeze_time("2024-01-01")
def test_transfer_gc_account_create_deployments_bulk_migrated_agreement(
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
    mocker.patch(
        "adobe_vipm.flows.fulfillment.transfer.get_transfer_by_authorization_membership_or_customer",
        return_value=None,
    )
    mocker.patch("adobe_vipm.flows.helpers.get_agreement", return_value=agreement)

    mocked_gc_main_agreement = mocker.MagicMock()
    mocked_gc_main_agreement.main_agreement_id = ""
    mocked_gc_main_agreement.status = STATUS_GC_PENDING

    mocker.patch(
        "adobe_vipm.flows.fulfillment.transfer.get_gc_main_agreement",
        return_value=mocked_gc_main_agreement,
    )

    mocked_get_gc_agreement_deployments_by_main_agreement = mocked_get_gc_main_agreement = (
        mocker.patch(
            "adobe_vipm.flows.fulfillment.transfer.get_gc_agreement_deployments_by_main_agreement",
            return_value=[],
        )
    )
    mocked_create_gc_agreement_deployments = mocker.patch(
        "adobe_vipm.flows.fulfillment.transfer.create_gc_agreement_deployments",
        return_value=None,
    )
    mocked_get_agreement_deployment_view_link = mocker.patch(
        "adobe_vipm.flows.fulfillment.transfer.get_agreement_deployment_view_link",
        return_value="link",
    )
    mocker.patch(
        "adobe_vipm.flows.fulfillment.transfer.send_warning",
        return_value=None,
    )

    adobe_transfer = adobe_transfer_factory(
        status=AdobeStatus.PROCESSED.value,
        customer_id="a-client-id",
        items=adobe_items_factory(subscription_id="a-sub-id")
        + adobe_items_factory(line_number=2, subscription_id="inactive-sub-id")
        + adobe_items_factory(
            line_number=3, offer_id="99999999CA01A12", subscription_id="one-time-sub-id"
        ),
    )

    adobe_transfer_preview = adobe_preview_transfer_factory()
    adobe_customer = adobe_customer_factory(global_sales_enabled=True)
    adobe_subscription = adobe_subscription_factory()
    adobe_inactive_subscription = adobe_subscription_factory(
        subscription_id="inactive-sub-id", status=AdobeStatus.INACTIVE_OR_GENERIC_FAILURE.value
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
    mocked_adobe_client.get_customer_deployments_active_status.return_value = [
        {
            "deploymentId": "deployment-id",
            "status": "1000",
            "companyProfile": {"address": {"country": "DE"}},
        },
        {
            "deploymentId": "deployment-id-2",
            "status": "1000",
            "companyProfile": {"address": {"country": "ES"}},
        },
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

    fulfill_order(mocked_mpt_client, order)
    authorization_id = order["authorization"]["id"]
    mocked_adobe_client.preview_transfer.assert_called_once_with(
        authorization_id,
        "a-membership-id",
    )

    assert mocked_update_order.mock_calls[1].kwargs == {
        "externalIds": {
            "vendor": adobe_transfer["transferId"],
        }
    }

    mocked_adobe_client.get_transfer.assert_called_once_with(
        authorization_id, "a-membership-id", adobe_transfer["transferId"]
    )
    mocked_get_gc_main_agreement.assert_called_once_with("PRD-1111-1111", "AGR-2119-4550-8674-5962")
    mocked_get_agreement_deployment_view_link.assert_called_once_with(
        "PRD-1111-1111",
    )
    mocked_get_gc_agreement_deployments_by_main_agreement.assert_called_once_with(
        "PRD-1111-1111", "AGR-2119-4550-8674-5962"
    )
    gc_agreement_deployments = [
        {
            "deployment_id": "deployment-id",
            "status": "pending",
            "customer_id": "a-client-id",
            "product_id": "PRD-1111-1111",
            "main_agreement_id": "AGR-2119-4550-8674-5962",
            "account_id": "",
            "seller_id": "",
            "membership_id": "membership-id",
            "transfer_id": "a-transfer-id",
            "deployment_currency": "",
            "deployment_country": "DE",
        },
        {
            "deployment_id": "deployment-id-2",
            "status": "pending",
            "customer_id": "a-client-id",
            "product_id": "PRD-1111-1111",
            "main_agreement_id": "AGR-2119-4550-8674-5962",
            "account_id": "",
            "seller_id": "",
            "membership_id": "membership-id",
            "transfer_id": "a-transfer-id",
            "deployment_currency": "",
            "deployment_country": "ES",
        },
    ]

    mocked_create_gc_agreement_deployments.assert_called_once_with(
        "PRD-1111-1111", gc_agreement_deployments
    )


def test_transfer_gc_account_pending_deployments(
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
    mocker.patch(
        "adobe_vipm.flows.fulfillment.transfer.get_transfer_by_authorization_membership_or_customer",
        return_value=None,
    )
    mocker.patch("adobe_vipm.flows.helpers.get_agreement", return_value=agreement)
    mocked_gc_main_agreement = mocker.MagicMock()
    mocked_gc_main_agreement.main_agreement_id = "main-agreement-id"
    mocked_gc_main_agreement.status = STATUS_GC_PENDING

    mocked_gc_agreement_deployments_by_main_agreement = mocker.MagicMock()
    mocked_gc_agreement_deployments_by_main_agreement.status = AdobeStatus.PENDING.value
    mocked_gc_agreement_deployments_by_main_agreement.deployment_id = "deployment-id"

    mocker.patch(
        "adobe_vipm.flows.fulfillment.transfer.get_gc_main_agreement",
        return_value=mocked_gc_main_agreement,
    )
    mocker.patch(
        "adobe_vipm.flows.fulfillment.transfer.get_gc_agreement_deployments_by_main_agreement",
        return_value=[mocked_gc_agreement_deployments_by_main_agreement],
    )

    adobe_transfer = adobe_transfer_factory(
        status=AdobeStatus.PROCESSED.value,
        customer_id="a-client-id",
        items=adobe_items_factory(subscription_id="a-sub-id")
        + adobe_items_factory(line_number=2, subscription_id="inactive-sub-id")
        + adobe_items_factory(
            line_number=3, offer_id="99999999CA01A12", subscription_id="one-time-sub-id"
        ),
    )

    adobe_transfer_preview = adobe_preview_transfer_factory()
    adobe_customer = adobe_customer_factory(global_sales_enabled=True)
    adobe_subscription = adobe_subscription_factory()

    mocked_adobe_client = mocker.MagicMock()
    mocked_adobe_client.preview_transfer.return_value = adobe_transfer_preview
    mocked_adobe_client.get_customer.return_value = adobe_customer
    mocked_adobe_client.get_transfer.return_value = adobe_transfer
    mocked_adobe_client.get_customer_deployments_active_status.return_value = [
        {
            "deploymentId": "deployment-id",
            "status": "1000",
            "companyProfile": {"address": {"country": "DE"}},
        }
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

    fulfill_order(mocked_mpt_client, order)
    assert order["status"] == MPT_ORDER_STATUS_PROCESSING


def test_transfer_gc_account_main_agreement_error_status(
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
    mocker.patch(
        "adobe_vipm.flows.fulfillment.transfer.get_transfer_by_authorization_membership_or_customer",
        return_value=None,
    )
    mocker.patch("adobe_vipm.flows.helpers.get_agreement", return_value=agreement)
    mocked_gc_main_agreement = mocker.MagicMock()
    mocked_gc_main_agreement.main_agreement_id = "main-agreement-id"
    mocked_gc_main_agreement.status = STATUS_GC_ERROR

    mocker.patch(
        "adobe_vipm.flows.fulfillment.transfer.get_gc_main_agreement",
        return_value=mocked_gc_main_agreement,
    )
    mocker.patch(
        "adobe_vipm.flows.fulfillment.transfer.get_gc_agreement_deployments_by_main_agreement",
        return_value=[],
    )

    adobe_transfer = adobe_transfer_factory(
        status=AdobeStatus.PROCESSED.value,
        customer_id="a-client-id",
        items=adobe_items_factory(subscription_id="a-sub-id")
        + adobe_items_factory(line_number=2, subscription_id="inactive-sub-id")
        + adobe_items_factory(
            line_number=3, offer_id="99999999CA01A12", subscription_id="one-time-sub-id"
        ),
    )

    adobe_transfer_preview = adobe_preview_transfer_factory()
    adobe_customer = adobe_customer_factory(global_sales_enabled=True)
    adobe_subscription = adobe_subscription_factory()

    mocked_adobe_client = mocker.MagicMock()
    mocked_adobe_client.preview_transfer.return_value = adobe_transfer_preview
    mocked_adobe_client.get_customer.return_value = adobe_customer
    mocked_adobe_client.get_transfer.return_value = adobe_transfer
    mocked_adobe_client.get_customer_deployments_active_status.return_value = [
        {
            "deploymentId": "deployment-id",
            "status": "1000",
            "companyProfile": {"address": {"country": "DE"}},
        }
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

    fulfill_order(mocked_mpt_client, order)
    assert order["status"] == MPT_ORDER_STATUS_PROCESSING


@freeze_time("2024-01-01")
def test_transfer_gc_account_no_items_error_main_agreement(
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
    mocker.patch(
        "adobe_vipm.flows.fulfillment.shared.get_product_template_or_default",
        side_effect=[{"id": "TPL-0000"}, {"id": "TPL-1111"}],
    )
    mocker.patch(
        "adobe_vipm.flows.fulfillment.transfer.get_transfer_by_authorization_membership_or_customer",
        return_value=None,
    )
    mocker.patch("adobe_vipm.flows.helpers.get_agreement", return_value=agreement)

    mocked_gc_main_agreement = mocker.MagicMock()
    mocked_gc_main_agreement.main_agreement_id = "main-agreement-id"
    mocked_gc_main_agreement.status = STATUS_GC_PENDING

    mocked_gc_agreement_deployments_by_main_agreement = mocker.MagicMock()
    mocked_gc_agreement_deployments_by_main_agreement.status = STATUS_GC_CREATED
    mocked_gc_agreement_deployments_by_main_agreement.deployment_id = "deployment-id"

    mocked_get_gc_main_agreement = mocker.patch(
        "adobe_vipm.flows.fulfillment.transfer.get_gc_main_agreement",
        return_value=mocked_gc_main_agreement,
    )
    mocker.patch(
        "adobe_vipm.flows.fulfillment.transfer.get_gc_agreement_deployments_by_main_agreement",
        return_value=[mocked_gc_agreement_deployments_by_main_agreement],
    )

    adobe_transfer = adobe_transfer_factory(
        status=AdobeStatus.PROCESSED.value,
        customer_id="a-client-id",
        items=adobe_items_factory(
            subscription_id="a-sub-id",
            deployment_id="deployment-id",
            offer_id="65304579CA01A12",
        ),
    )

    adobe_transfer_preview = adobe_preview_transfer_factory()
    adobe_customer = adobe_customer_factory(global_sales_enabled=True)
    adobe_subscription = adobe_subscription_factory(deployment_id="deployment-id")

    mocked_adobe_client = mocker.MagicMock()
    mocked_adobe_client.preview_transfer.return_value = adobe_transfer_preview
    mocked_adobe_client.create_transfer.return_value = adobe_transfer
    mocked_adobe_client.get_customer.return_value = adobe_customer
    mocked_adobe_client.get_transfer.return_value = adobe_transfer
    mocked_adobe_client.get_subscription.side_effect = [
        adobe_subscription,
    ]
    mocked_adobe_client.get_customer_deployments_active_status.return_value = [
        {
            "deploymentId": "deployment-id",
            "status": "1000",
            "companyProfile": {"address": {"country": "DE"}},
        }
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
    mocker.patch(
        "adobe_vipm.flows.utils.order.get_product_onetime_items_by_ids",
        return_value=items_factory(item_id=2, external_vendor_id="99999999CA"),
    )

    mocked_process_order = mocker.patch(
        "adobe_vipm.flows.fulfillment.shared.set_processing_template",
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
                deployments=["deployment-id - DE"],
                global_customer="Yes",
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

    mocked_process_order.assert_called_once_with(
        mocked_mpt_client,
        order["id"],
        {"id": "TPL-0000"},
    )
    mocked_adobe_client.get_transfer.assert_called_once_with(
        authorization_id, "a-membership-id", adobe_transfer["transferId"]
    )
    mocked_get_gc_main_agreement.assert_called_once_with(
        "PRD-1111-1111", "AUT-1234-4567", "a-membership-id"
    )
    assert order["status"] == MPT_ORDER_STATUS_PROCESSING


@freeze_time("2024-01-01")
def test_transfer_gc_account_some_deployments_not_created(
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
    mocker.patch(
        "adobe_vipm.flows.fulfillment.transfer.get_transfer_by_authorization_membership_or_customer",
        return_value=None,
    )
    mocker.patch("adobe_vipm.flows.helpers.get_agreement", return_value=agreement)

    mocked_gc_main_agreement = mocker.MagicMock()
    mocked_gc_main_agreement.main_agreement_id = "main-agreement-id"
    mocked_gc_main_agreement.status = STATUS_GC_PENDING

    mocker.patch(
        "adobe_vipm.flows.fulfillment.transfer.get_gc_main_agreement",
        return_value=mocked_gc_main_agreement,
    )

    mocked_get_gc_agreement_deployments_by_main_agreement = mocked_get_gc_main_agreement = (
        mocker.patch(
            "adobe_vipm.flows.fulfillment.transfer.get_gc_agreement_deployments_by_main_agreement",
            return_value=[],
        )
    )
    mocked_create_gc_agreement_deployments = mocker.patch(
        "adobe_vipm.flows.fulfillment.transfer.create_gc_agreement_deployments",
        return_value=None,
    )
    mocked_get_agreement_deployment_view_link = mocker.patch(
        "adobe_vipm.flows.fulfillment.transfer.get_agreement_deployment_view_link",
        return_value="link",
    )
    mocker.patch(
        "adobe_vipm.flows.fulfillment.transfer.send_warning",
        return_value=None,
    )

    adobe_transfer = adobe_transfer_factory(
        status=AdobeStatus.PROCESSED.value,
        customer_id="a-client-id",
        items=adobe_items_factory(
            subscription_id="a-sub-id",
            deployment_id="deployment-id",
            currencyCode="EUR",
            offer_id="653045798CA01A12",
            deployment_currency_code="EUR",
        )
        + adobe_items_factory(line_number=2, subscription_id="inactive-sub-id")
        + adobe_items_factory(
            line_number=3,
            offer_id="99999999CA01A12",
            subscription_id="one-time-sub-id",
            deployment_id="deployment-id-2",
            currencyCode="EUR",
            deployment_currency_code="EUR",
        )
        + adobe_items_factory(
            line_number=4,
            subscription_id="a-sub-id2",
            deployment_id="deployment-id",
            currencyCode="USD",
            offer_id="65304579CA01A12",
            deployment_currency_code="USD",
        ),
    )

    adobe_transfer_preview = adobe_preview_transfer_factory()
    adobe_customer = adobe_customer_factory(global_sales_enabled=True)
    adobe_subscription = adobe_subscription_factory()
    adobe_inactive_subscription = adobe_subscription_factory(
        subscription_id="inactive-sub-id", status=AdobeStatus.INACTIVE_OR_GENERIC_FAILURE.value
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
    mocked_adobe_client.get_customer_deployments_active_status.return_value = [
        {
            "deploymentId": "deployment-id",
            "status": "1000",
            "companyProfile": {"address": {"country": "DE"}},
            "currencyCode": "EUR",
        },
        {
            "deploymentId": "deployment-id-2",
            "status": "1000",
            "companyProfile": {"address": {"country": "ES"}},
            "currencyCode": "EUR",
        },
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

    fulfill_order(mocked_mpt_client, order)
    authorization_id = order["authorization"]["id"]
    mocked_adobe_client.preview_transfer.assert_called_once_with(
        authorization_id,
        "a-membership-id",
    )

    assert mocked_update_order.mock_calls[1].kwargs == {
        "externalIds": {
            "vendor": adobe_transfer["transferId"],
        }
    }

    mocked_adobe_client.get_transfer.assert_called_once_with(
        authorization_id, "a-membership-id", adobe_transfer["transferId"]
    )
    mocked_get_gc_main_agreement.assert_called_once_with("PRD-1111-1111", "AGR-2119-4550-8674-5962")
    mocked_get_agreement_deployment_view_link.assert_called_once_with(
        "PRD-1111-1111",
    )
    mocked_get_gc_agreement_deployments_by_main_agreement.assert_called_once_with(
        "PRD-1111-1111", "AGR-2119-4550-8674-5962"
    )
    gc_agreement_deployments = [
        {
            "deployment_id": "deployment-id",
            "status": "pending",
            "customer_id": "a-client-id",
            "product_id": "PRD-1111-1111",
            "main_agreement_id": "AGR-2119-4550-8674-5962",
            "account_id": "",
            "seller_id": "",
            "membership_id": "membership-id",
            "transfer_id": "a-transfer-id",
            "deployment_currency": "EUR,USD",
            "deployment_country": "DE",
        },
        {
            "deployment_id": "deployment-id-2",
            "status": "pending",
            "customer_id": "a-client-id",
            "product_id": "PRD-1111-1111",
            "main_agreement_id": "AGR-2119-4550-8674-5962",
            "account_id": "",
            "seller_id": "",
            "membership_id": "membership-id",
            "transfer_id": "a-transfer-id",
            "deployment_currency": "EUR",
            "deployment_country": "ES",
        },
    ]

    mocked_create_gc_agreement_deployments.assert_called_once_with(
        "PRD-1111-1111", gc_agreement_deployments
    )


@freeze_time("2012-01-14 12:00:01")
def test_fulfill_transfer_gc_order_already_migrated_(
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
    mocker.patch(
        "adobe_vipm.flows.fulfillment.shared.get_product_template_or_default",
        side_effect=[{"id": "TPL-0000"}, {"id": "TPL-1111"}],
    )

    order_params = transfer_order_parameters_factory()
    order = order_factory(order_parameters=order_params)

    mocker.patch("adobe_vipm.flows.helpers.get_agreement", return_value=agreement)
    gc_main_agreement = mocker.MagicMock()
    gc_main_agreement.main_agreement_id = ""
    gc_main_agreement.status = STATUS_GC_PENDING
    mocker.patch(
        "adobe_vipm.flows.fulfillment.transfer.get_gc_main_agreement",
        return_value=gc_main_agreement,
    )
    mocked_get_gc_agreement_deployments_by_main_agreement = mocker.patch(
        "adobe_vipm.flows.fulfillment.transfer.get_gc_agreement_deployments_by_main_agreement",
        return_value=[],
    )
    mocked_create_gc_agreement_deployments = mocker.patch(
        "adobe_vipm.flows.fulfillment.transfer.create_gc_agreement_deployments",
        return_value=None,
    )
    mocked_get_agreement_deployment_view_link = mocker.patch(
        "adobe_vipm.flows.fulfillment.transfer.get_agreement_deployment_view_link",
        return_value="link",
    )
    mocker.patch(
        "adobe_vipm.flows.fulfillment.transfer.send_warning",
        return_value=None,
    )

    mocked_transfer = mocker.MagicMock()
    mocked_transfer.customer_id = "customer-id"
    mocked_transfer.transfer_id = "transfer-id"
    mocked_transfer.customer_benefits_3yc_status = ThreeYearCommitmentStatus.EXPIRED.value

    adobe_customer = adobe_customer_factory(global_sales_enabled=True)

    adobe_customer_address = adobe_customer["companyProfile"]["address"]
    adobe_customer_contact = adobe_customer["companyProfile"]["contacts"][0]

    updated_order = order_factory(
        fulfillment_parameters=fulfillment_parameters_factory(
            customer_id="a-client-id",
            due_date="2025-01-01",
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
        "adobe_vipm.flows.utils.order.get_product_onetime_items_by_ids",
        return_value=[],
    )

    mocker.patch(
        "adobe_vipm.flows.fulfillment.transfer.add_subscription",
        return_value=subscriptions_factory(commitment_date="2024-08-04")[0],
    )

    mocked_process_order = mocker.patch(
        "adobe_vipm.flows.fulfillment.shared.set_processing_template",
    )

    mocker.patch(
        "adobe_vipm.flows.fulfillment.shared.update_order",
    )

    mocker.patch("adobe_vipm.flows.fulfillment.shared.complete_order")

    transfer_items = adobe_items_factory(subscription_id="sub-id")

    adobe_transfer = adobe_transfer_factory(status=AdobeStatus.PENDING.value, items=transfer_items)
    adobe_subscription = adobe_subscription_factory(
        status=AdobeStatus.PENDING.value, current_quantity=170
    )

    mocked_adobe_client = mocker.MagicMock()
    mocked_adobe_client.get_transfer.return_value = adobe_transfer
    mocked_adobe_client.get_customer.return_value = adobe_customer
    mocked_adobe_client.get_subscription.return_value = adobe_subscription
    mocked_adobe_client.get_subscriptions.return_value = {
        "items": [adobe_subscription],
    }
    mocked_adobe_client.get_customer_deployments_active_status.return_value = [
        {
            "deploymentId": "deployment-id",
            "status": "1000",
            "companyProfile": {"address": {"country": "DE"}},
        }
    ]

    mocker.patch(
        "adobe_vipm.flows.fulfillment.transfer.get_adobe_client",
        return_value=mocked_adobe_client,
    )

    fulfill_order(m_client, order)

    membership_id_param = get_ordering_parameter(updated_order, Param.MEMBERSHIP_ID.value)

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

    mocked_get_agreement_deployment_view_link.assert_called_once_with(
        "PRD-1111-1111",
    )
    mocked_get_gc_agreement_deployments_by_main_agreement.assert_called_once_with(
        "PRD-1111-1111", "AGR-2119-4550-8674-5962"
    )
    gc_agreement_deployments = [
        {
            "deployment_id": "deployment-id",
            "status": "pending",
            "customer_id": "",
            "product_id": "PRD-1111-1111",
            "main_agreement_id": "AGR-2119-4550-8674-5962",
            "account_id": "",
            "seller_id": "",
            "membership_id": "membership-id",
            "transfer_id": "a-transfer-id",
            "deployment_currency": "",
            "deployment_country": "DE",
        }
    ]

    mocked_create_gc_agreement_deployments.assert_called_once_with(
        "PRD-1111-1111", gc_agreement_deployments
    )
    mocked_adobe_client.update_subscription.assert_not_called()


@freeze_time("2012-01-14 12:00:01")
def test_fulfill_transfer_gc_order_already_migrated_no_items_without_deployment(
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
    items_factory,
):
    order_params = transfer_order_parameters_factory()
    order = order_factory(order_parameters=order_params, lines=[])

    mocker.patch("adobe_vipm.flows.helpers.get_agreement", return_value=agreement)
    mocked_gc_main_agreement = mocker.MagicMock()
    mocked_gc_main_agreement.main_agreement_id = ""
    mocked_gc_main_agreement.status = STATUS_GC_PENDING
    mocker.patch(
        "adobe_vipm.flows.fulfillment.transfer.get_gc_main_agreement",
        return_value=mocked_gc_main_agreement,
    )
    mocked_gc_agreement_deployments_by_main_agreement = mocker.MagicMock()
    mocked_gc_agreement_deployments_by_main_agreement.status = STATUS_GC_CREATED
    mocked_gc_agreement_deployments_by_main_agreement.deployment_id = "deployment-id"
    mocked_get_gc_agreement_deployments_by_main_agreement = mocker.patch(
        "adobe_vipm.flows.fulfillment.transfer.get_gc_agreement_deployments_by_main_agreement",
        return_value=[mocked_gc_agreement_deployments_by_main_agreement],
    )
    mocker.patch(
        "adobe_vipm.flows.fulfillment.transfer.create_gc_agreement_deployments",
        return_value=None,
    )
    mocker.patch(
        "adobe_vipm.flows.fulfillment.transfer.get_agreement_deployment_view_link",
        return_value="link",
    )
    mocker.patch(
        "adobe_vipm.flows.fulfillment.transfer.send_warning",
        return_value=None,
    )
    product_items = items_factory()
    mocker.patch(
        "adobe_vipm.flows.fulfillment.transfer.get_product_items_by_skus",
        return_value=product_items,
    )

    mocked_transfer = mocker.MagicMock()
    mocked_transfer.customer_id = "customer-id"
    mocked_transfer.transfer_id = "transfer-id"
    mocked_transfer.customer_benefits_3yc_status = ThreeYearCommitmentStatus.EXPIRED.value

    adobe_customer = adobe_customer_factory(global_sales_enabled=True)

    adobe_customer_address = adobe_customer["companyProfile"]["address"]
    adobe_customer_contact = adobe_customer["companyProfile"]["contacts"][0]

    updated_order = order_factory(
        fulfillment_parameters=fulfillment_parameters_factory(
            customer_id="a-client-id",
            due_date="2025-01-01",
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
        "adobe_vipm.flows.utils.order.get_product_onetime_items_by_ids",
        return_value=[],
    )

    mocker.patch(
        "adobe_vipm.flows.fulfillment.transfer.add_subscription",
        return_value=subscriptions_factory(commitment_date="2024-08-04")[0],
    )

    mocker.patch(
        "adobe_vipm.flows.fulfillment.shared.set_processing_template",
    )

    mocker.patch(
        "adobe_vipm.flows.fulfillment.shared.update_order",
    )

    mocker.patch("adobe_vipm.flows.fulfillment.shared.complete_order")

    transfer_items = adobe_items_factory(subscription_id="sub-id", deployment_id="deployment-id")

    adobe_transfer = adobe_transfer_factory(status=AdobeStatus.PENDING.value, items=transfer_items)
    adobe_subscription = adobe_subscription_factory(
        status=AdobeStatus.PENDING.value, current_quantity=170, deployment_id="deployment-id"
    )

    mocked_adobe_client = mocker.MagicMock()
    mocked_adobe_client.get_transfer.return_value = adobe_transfer
    mocked_adobe_client.get_customer.return_value = adobe_customer
    mocked_adobe_client.get_subscription.return_value = adobe_subscription
    mocked_adobe_client.get_subscriptions.return_value = {
        "items": [adobe_subscription],
    }
    mocked_adobe_client.get_customer_deployments_active_status.return_value = [
        {
            "deploymentId": "deployment-id",
            "status": "1000",
            "companyProfile": {"address": {"country": "DE"}},
        }
    ]

    mocker.patch(
        "adobe_vipm.flows.fulfillment.transfer.get_adobe_client",
        return_value=mocked_adobe_client,
    )

    fulfill_order(m_client, order)

    membership_id_param = get_ordering_parameter(updated_order, Param.MEMBERSHIP_ID.value)

    mocked_get_transfer.assert_called_once_with(
        order["agreement"]["product"]["id"],
        adobe_authorizations_file["authorizations"][0]["authorization_id"],
        membership_id_param["value"],
    )

    mocked_get_gc_agreement_deployments_by_main_agreement.assert_called_once_with(
        "PRD-1111-1111", "AGR-2119-4550-8674-5962"
    )
    assert mocked_gc_main_agreement.save.call_count == 2
    mocked_adobe_client.update_subscription.assert_not_called()


@freeze_time("2012-01-14 12:00:01")
def test_sync_gc_main_agreement_step(
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

    mocked_gc_main_agreement = mocker.MagicMock()
    mocked_gc_main_agreement.main_agreement_id = "agr-id"
    mocked_gc_main_agreement.status = STATUS_GC_PENDING

    step = SyncGCMainAgreement(mocked_transfer, mocked_gc_main_agreement, STATUS_GC_TRANSFERRED)
    step(mocked_client, context, mocked_next_step)

    assert mocked_gc_main_agreement.status == STATUS_GC_TRANSFERRED
    mocked_next_step.assert_called_once_with(mocked_client, context)


@freeze_time("2024-01-01")
def test_transfer_gc_account_items_with_deployment_main_agreement(
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
    mocker.patch(
        "adobe_vipm.flows.fulfillment.shared.get_product_template_or_default",
        side_effect=[{"id": "TPL-0000"}, {"id": "TPL-1111"}],
    )
    mocker.patch(
        "adobe_vipm.flows.fulfillment.transfer.get_transfer_by_authorization_membership_or_customer",
        return_value=None,
    )
    mocker.patch("adobe_vipm.flows.helpers.get_agreement", return_value=agreement)

    mocked_gc_main_agreement = mocker.MagicMock()
    mocked_gc_main_agreement.main_agreement_id = "main-agreement-id"
    mocked_gc_main_agreement.status = STATUS_GC_PENDING

    mocked_create_gc_main_agreement = mocker.patch(
        "adobe_vipm.flows.fulfillment.transfer.create_gc_main_agreement",
        return_value=None,
    )

    mocked_gc_agreement_deployments_by_main_agreement = mocker.MagicMock()
    mocked_gc_agreement_deployments_by_main_agreement.status = STATUS_GC_CREATED
    mocked_gc_agreement_deployments_by_main_agreement.deployment_id = "deployment-id"

    mocked_get_gc_main_agreement = mocker.patch(
        "adobe_vipm.flows.fulfillment.transfer.get_gc_main_agreement",
        return_value=None,
    )
    mocker.patch(
        "adobe_vipm.flows.fulfillment.transfer.get_gc_agreement_deployments_by_main_agreement",
        return_value=[mocked_gc_agreement_deployments_by_main_agreement],
    )

    adobe_transfer = adobe_transfer_factory(
        status=AdobeStatus.PROCESSED.value,
        customer_id="a-client-id",
        items=adobe_items_factory(subscription_id="a-sub-id", deployment_id="deployment-id"),
    )

    adobe_transfer_preview = adobe_preview_transfer_factory()
    adobe_customer = adobe_customer_factory(global_sales_enabled=True)
    adobe_subscription = adobe_subscription_factory(deployment_id="deployment-id")

    mocked_adobe_client = mocker.MagicMock()
    mocked_adobe_client.preview_transfer.return_value = adobe_transfer_preview
    mocked_adobe_client.create_transfer.return_value = adobe_transfer
    mocked_adobe_client.get_customer.return_value = adobe_customer
    mocked_adobe_client.get_transfer.return_value = adobe_transfer
    mocked_adobe_client.get_subscription.side_effect = [
        adobe_subscription,
    ]
    mocked_adobe_client.get_customer_deployments_active_status.return_value = [
        {
            "deploymentId": "deployment-id",
            "status": "1000",
            "companyProfile": {"address": {"country": "DE"}},
        }
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

    mocker.patch(
        "adobe_vipm.flows.utils.order.get_product_onetime_items_by_ids",
        return_value=items_factory(item_id=2, external_vendor_id="99999999CA"),
    )

    fulfill_order(mocked_mpt_client, order)

    authorization_id = order["authorization"]["id"]

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

    mocked_adobe_client.get_transfer.assert_called_once_with(
        authorization_id, "a-membership-id", adobe_transfer["transferId"]
    )
    mocked_get_gc_main_agreement.assert_called_once_with(
        "PRD-1111-1111", "AUT-1234-4567", "a-membership-id"
    )
    assert order["status"] == MPT_ORDER_STATUS_PROCESSING

    gc_main_agreement = {
        "membership_id": "membership-id",
        "authorization_uk": "AUT-1234-4567",
        "main_agreement_id": "AGR-2119-4550-8674-5962",
        "transfer_id": "a-transfer-id",
        "customer_id": "a-client-id",
        "status": "error",
        "error_description": "Order contains items with deployment ID",
    }
    mocked_create_gc_main_agreement.assert_called_once_with("PRD-1111-1111", gc_main_agreement)


@freeze_time("2024-01-01")
def test_transfer_gc_account_items_with_deployment_main_agreement_bulk_migrated(
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
    mocked_transfer = mocker.MagicMock()
    mocked_transfer.membership_id = "membership-id"
    mocked_transfer.customer_id = "customer-id"
    mocked_transfer.transfer_id = "a-transfer-id"
    mocked_transfer.customer_benefits_3yc_status = None

    mocker.patch(
        "adobe_vipm.flows.fulfillment.shared.get_product_template_or_default",
        side_effect=[{"id": "TPL-0000"}, {"id": "TPL-1111"}],
    )
    mocker.patch(
        "adobe_vipm.flows.fulfillment.transfer.get_transfer_by_authorization_membership_or_customer",
        return_value=None,
    )
    mocker.patch("adobe_vipm.flows.helpers.get_agreement", return_value=agreement)

    mocked_gc_main_agreement = mocker.MagicMock()
    mocked_gc_main_agreement.main_agreement_id = "main-agreement-id"
    mocked_gc_main_agreement.status = STATUS_GC_PENDING

    mocked_gc_agreement_deployments_by_main_agreement = mocker.MagicMock()
    mocked_gc_agreement_deployments_by_main_agreement.status = STATUS_GC_CREATED
    mocked_gc_agreement_deployments_by_main_agreement.deployment_id = "deployment-id"

    mocked_get_gc_main_agreement = mocker.patch(
        "adobe_vipm.flows.fulfillment.transfer.get_gc_main_agreement",
        return_value=mocked_gc_main_agreement,
    )
    mocker.patch(
        "adobe_vipm.flows.fulfillment.transfer.get_gc_agreement_deployments_by_main_agreement",
        return_value=[mocked_gc_agreement_deployments_by_main_agreement],
    )

    adobe_transfer = adobe_transfer_factory(
        status=AdobeStatus.PROCESSED.value,
        customer_id="a-client-id",
        items=adobe_items_factory(subscription_id="a-sub-id", deployment_id="deployment-id"),
    )

    adobe_transfer_preview = adobe_preview_transfer_factory()
    adobe_customer = adobe_customer_factory(global_sales_enabled=True)
    adobe_subscription = adobe_subscription_factory(deployment_id="deployment-id")

    mocked_adobe_client = mocker.MagicMock()
    mocked_adobe_client.preview_transfer.return_value = adobe_transfer_preview
    mocked_adobe_client.create_transfer.return_value = adobe_transfer
    mocked_adobe_client.get_customer.return_value = adobe_customer
    mocked_adobe_client.get_transfer.return_value = adobe_transfer
    mocked_adobe_client.get_subscription.side_effect = [
        adobe_subscription,
    ]
    mocked_adobe_client.get_customer_deployments_active_status.return_value = [
        {
            "deploymentId": "deployment-id",
            "status": "1000",
            "companyProfile": {"address": {"country": "DE"}},
        }
    ]
    mocker.patch(
        "adobe_vipm.flows.fulfillment.transfer.get_transfer_by_authorization_membership_or_customer",
        return_value=mocked_transfer,
    )
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

    mocker.patch(
        "adobe_vipm.flows.utils.order.get_product_onetime_items_by_ids",
        return_value=items_factory(item_id=2, external_vendor_id="99999999CA"),
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
                due_date="2024-01-31",
            ),
            "ordering": order["parameters"]["ordering"],
        },
    }

    mocked_adobe_client.get_transfer.assert_called_once_with(
        authorization_id, "membership-id", adobe_transfer["transferId"]
    )
    mocked_get_gc_main_agreement.assert_called_once_with(
        "PRD-1111-1111", "AUT-1234-4567", "a-membership-id"
    )
    assert order["status"] == MPT_ORDER_STATUS_PROCESSING

    mocked_gc_main_agreement.save.assert_called_once()


@freeze_time("2025-01-01")
def test_transfer_not_ready_not_commercial(
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
    mocked_get_gc_main_agreement = mocker.patch(
        "adobe_vipm.flows.fulfillment.transfer.get_gc_main_agreement",
        return_value=None,
    )
    mocked_get_gc_agreement_deployments_by_main_agreement = mocker.patch(
        "adobe_vipm.flows.fulfillment.transfer.get_gc_agreement_deployments_by_main_agreement",
        return_value=None,
    )
    agreement["product"]["id"] = "PRD-2222-2222"
    mocker.patch("adobe_vipm.flows.helpers.get_agreement", return_value=agreement)

    adobe_transfer = adobe_transfer_factory(status=AdobeStatus.PENDING.value)

    mocked_adobe_client = mocker.MagicMock()
    mocked_adobe_client.create_transfer.return_value = adobe_transfer
    mocked_adobe_client.get_transfer.return_value = adobe_transfer
    mocker.patch(
        "adobe_vipm.flows.fulfillment.transfer.get_adobe_client",
        return_value=mocked_adobe_client,
    )

    mocked_mpt_client = mocker.MagicMock()
    mocked_update_order = mocker.patch("adobe_vipm.flows.fulfillment.shared.update_order")
    mocked_complete_order = mocker.patch("adobe_vipm.flows.fulfillment.shared.complete_order")

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
    mocked_get_gc_agreement_deployments_by_main_agreement.assert_not_called()
    mocked_get_gc_main_agreement.assert_not_called()


@freeze_time("2024-01-01")
def test_transfer_gc_account_no_deployments_gc_parameters_updated(
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

    mocked_gc_main_agreement = mocker.MagicMock()
    mocked_gc_main_agreement.main_agreement_id = "main-agreement-id"
    mocked_gc_main_agreement.status = STATUS_GC_PENDING

    mocked_get_gc_main_agreement = mocker.patch(
        "adobe_vipm.flows.fulfillment.transfer.get_gc_main_agreement",
        return_value=mocked_gc_main_agreement,
    )

    mocked_get_gc_agreement_deployments_by_main_agreement = mocker.patch(
        "adobe_vipm.flows.fulfillment.transfer.get_gc_agreement_deployments_by_main_agreement",
        return_value=[],
    )

    adobe_transfer = adobe_transfer_factory(
        status=AdobeStatus.PROCESSED.value,
        customer_id="a-client-id",
        items=adobe_items_factory(subscription_id="a-sub-id")
        + adobe_items_factory(line_number=2, subscription_id="inactive-sub-id")
        + adobe_items_factory(
            line_number=3, offer_id="99999999CA01A12", subscription_id="one-time-sub-id"
        ),
    )

    adobe_transfer_preview = adobe_preview_transfer_factory()
    adobe_customer = adobe_customer_factory(global_sales_enabled=True)
    adobe_subscription = adobe_subscription_factory()
    adobe_inactive_subscription = adobe_subscription_factory(
        subscription_id="inactive-sub-id", status=AdobeStatus.INACTIVE_OR_GENERIC_FAILURE.value
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
    mocked_adobe_client.get_customer_deployments_active_status.return_value = []
    mocked_adobe_client.update_subscription.return_value = adobe_subscription
    mocker.patch(
        "adobe_vipm.flows.fulfillment.transfer.get_adobe_client",
        return_value=mocked_adobe_client,
    )

    order = order_factory(
        order_parameters=transfer_order_parameters_factory(),
        fulfillment_parameters=fulfillment_parameters_factory(
            global_customer="Yes", deployments=""
        ),
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
        "adobe_vipm.flows.utils.order.get_product_onetime_items_by_ids",
        return_value=items_factory(item_id=2, external_vendor_id="99999999CA"),
    )

    mocked_process_order = mocker.patch(
        "adobe_vipm.flows.fulfillment.shared.set_processing_template",
    )

    mocked_complete_order = mocker.patch("adobe_vipm.flows.fulfillment.shared.complete_order")
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
                global_customer="Yes",
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
                global_customer="Yes",
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
                coterm_date="2024-01-01",
                global_customer="Yes",
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
                        "value": str(adobe_subscription["autoRenewal"]["renewalQuantity"]),
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
                coterm_date="2024-01-01",
                deployments=[],
                global_customer="Yes",
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
    assert mocked_get_gc_main_agreement.mock_calls[0].args == (
        "PRD-1111-1111",
        "AUT-1234-4567",
        "a-membership-id",
    )
    mocked_get_gc_agreement_deployments_by_main_agreement.assert_called_once_with(
        "PRD-1111-1111", "AGR-2119-4550-8674-5962"
    )


@freeze_time("2024-01-01")
def test_transfer_gc_account_items_with_and_without_deployment_main_agreement_bulk_migrated(
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
    mocked_transfer = mocker.MagicMock()
    mocked_transfer.membership_id = "membership-id"
    mocked_transfer.customer_id = "customer-id"
    mocked_transfer.transfer_id = "a-transfer-id"
    mocked_transfer.customer_benefits_3yc_status = None

    mocker.patch(
        "adobe_vipm.flows.fulfillment.shared.get_product_template_or_default",
        side_effect=[{"id": "TPL-0000"}, {"id": "TPL-1111"}],
    )
    mocker.patch(
        "adobe_vipm.flows.fulfillment.transfer.get_transfer_by_authorization_membership_or_customer",
        return_value=None,
    )
    product_items = items_factory()
    mocker.patch(
        "adobe_vipm.flows.fulfillment.transfer.get_product_items_by_skus",
        return_value=product_items,
    )
    mocker.patch("adobe_vipm.flows.helpers.get_agreement", return_value=agreement)

    mocked_gc_main_agreement = mocker.MagicMock()
    mocked_gc_main_agreement.main_agreement_id = "main-agreement-id"
    mocked_gc_main_agreement.status = STATUS_GC_PENDING

    mocked_gc_agreement_deployments_by_main_agreement = mocker.MagicMock()
    mocked_gc_agreement_deployments_by_main_agreement.status = STATUS_GC_CREATED
    mocked_gc_agreement_deployments_by_main_agreement.deployment_id = "deployment-id"

    mocked_get_gc_main_agreement = mocker.patch(
        "adobe_vipm.flows.fulfillment.transfer.get_gc_main_agreement",
        return_value=mocked_gc_main_agreement,
    )
    mocker.patch(
        "adobe_vipm.flows.fulfillment.transfer.get_gc_agreement_deployments_by_main_agreement",
        return_value=[mocked_gc_agreement_deployments_by_main_agreement],
    )

    adobe_transfer = adobe_transfer_factory(
        status=AdobeStatus.PROCESSED.value,
        customer_id="a-client-id",
        items=adobe_items_factory(
            offer_id="65304578CACA01A12",
            subscription_id="a-sub-id",
            deployment_id="deployment-id",
        )
        + adobe_items_factory(offer_id="65304578CACA01A12", subscription_id="a-sub-id1"),
    )

    adobe_transfer_preview = adobe_preview_transfer_factory()
    adobe_customer = adobe_customer_factory(global_sales_enabled=True)
    adobe_subscription = adobe_subscription_factory(
        deployment_id="deployment-id", current_quantity=170
    )
    adobe_subscription1 = adobe_subscription_factory(current_quantity=170)

    mocked_adobe_client = mocker.MagicMock()
    mocked_adobe_client.preview_transfer.return_value = adobe_transfer_preview
    mocked_adobe_client.create_transfer.return_value = adobe_transfer
    mocked_adobe_client.get_customer.return_value = adobe_customer
    mocked_adobe_client.get_transfer.return_value = adobe_transfer
    mocked_adobe_client.get_subscriptions.return_value = {
        "items": [adobe_subscription, adobe_subscription1],
    }
    mocked_adobe_client.get_subscription.return_value = adobe_subscription
    mocked_adobe_client.get_customer_deployments_active_status.return_value = [
        {
            "deploymentId": "deployment-id",
            "status": "1000",
            "companyProfile": {"address": {"country": "DE"}},
        }
    ]

    mocker.patch(
        "adobe_vipm.flows.fulfillment.transfer.add_subscription",
        return_value=subscriptions_factory(commitment_date="2024-08-04")[0],
    )

    mocker.patch(
        "adobe_vipm.flows.fulfillment.transfer.get_transfer_by_authorization_membership_or_customer",
        return_value=mocked_transfer,
    )
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

    mocker.patch(
        "adobe_vipm.flows.utils.order.get_product_onetime_items_by_ids",
        return_value=items_factory(item_id=2, external_vendor_id="99999999CA"),
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
                due_date="2024-01-31",
            ),
            "ordering": order["parameters"]["ordering"],
        },
    }

    mocked_adobe_client.get_transfer.assert_called_once_with(
        authorization_id, "membership-id", adobe_transfer["transferId"]
    )
    mocked_get_gc_main_agreement.assert_called_once_with(
        "PRD-1111-1111", "AUT-1234-4567", "a-membership-id"
    )
    assert order["status"] == MPT_ORDER_STATUS_PROCESSING


@freeze_time("2012-01-14 12:00:01")
def test_fulfill_transfer_migrated_order_all_items_expired_add_new_item(
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
    adobe_subscription_factory,
    agreement,
    mock_sync_agreements_by_agreement_ids,
    mock_mpt_client,
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
    mocker.patch(
        "adobe_vipm.flows.fulfillment.transfer.add_subscription",
        return_value=subscriptions_factory(commitment_date="2024-08-04")[0],
    )
    product_items = items_factory()
    mocker.patch(
        "adobe_vipm.flows.fulfillment.transfer.get_product_items_by_skus",
        return_value=product_items,
    )
    mocked_get_transfer = mocker.patch(
        "adobe_vipm.flows.fulfillment.transfer.get_transfer_by_authorization_membership_or_customer",
        return_value=mocked_transfer,
    )
    mocker.patch(
        "adobe_vipm.flows.fulfillment.transfer.get_gc_main_agreement",
        return_value=None,
    )
    mocker.patch(
        "adobe_vipm.flows.fulfillment.transfer.get_gc_agreement_deployments_by_main_agreement",
        return_value=None,
    )
    product_items = items_factory()
    mocker.patch(
        "adobe_vipm.flows.fulfillment.transfer.get_product_items_by_skus",
        return_value=product_items,
    )
    mocker.patch(
        "adobe_vipm.flows.utils.order.get_product_onetime_items_by_ids",
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
        subscription_id="inactive-sub-id",
        status=AdobeStatus.INACTIVE_OR_GENERIC_FAILURE.value,
        offer_id="65304999CA",
    ) + adobe_items_factory(
        subscription_id="one-time-sub-id",
        offer_id="99999999CA01A12",
    )
    adobe_subscription = adobe_subscription_factory(offer_id="65304578CA2", current_quantity=170)
    adobe_inactive_subscription = adobe_subscription_factory(
        subscription_id="inactive-sub-id",
        status=AdobeStatus.INACTIVE_OR_GENERIC_FAILURE.value,
        offer_id="65304999CA",
    )
    adobe_one_time_subscription = adobe_subscription_factory(
        subscription_id="one-time-sub-id", offer_id="99999999CA01A12"
    )
    adobe_transfer = adobe_transfer_factory(items=transfer_items)
    new_order = adobe_order_factory(order_type=ORDER_TYPE_NEW, status=AdobeStatus.PENDING.value)

    mocked_adobe_client = mocker.MagicMock()
    mocked_adobe_client.get_transfer.return_value = adobe_transfer
    mocked_adobe_client.get_customer.return_value = adobe_customer
    mocked_adobe_client.get_subscriptions.return_value = {
        "items": [
            adobe_subscription,
            adobe_inactive_subscription,
            adobe_one_time_subscription,
        ]
    }
    mocked_adobe_client.get_subscription.return_value = adobe_subscription

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

    fulfill_order(mock_mpt_client, order)

    membership_id_param = get_ordering_parameter(updated_order, Param.MEMBERSHIP_ID.value)

    mocked_get_transfer.assert_called_once_with(
        order["agreement"]["product"]["id"],
        adobe_authorizations_file["authorizations"][0]["authorization_id"],
        membership_id_param["value"],
    )

    mocked_process_order.assert_called_once_with(
        mock_mpt_client,
        order["id"],
        {"id": "TPL-0000"},
    )

    assert mocked_update_order.mock_calls[0].args == (
        mock_mpt_client,
        order["id"],
    )
    assert mocked_update_order.mock_calls[0].kwargs == {
        "parameters": {
            "fulfillment": fulfillment_parameters_factory(due_date="2012-02-13"),
            "ordering": order["parameters"]["ordering"],
        },
    }
    mock_sync_agreements_by_agreement_ids.assert_called_once_with(
        mock_mpt_client, [agreement["id"]], dry_run=False, sync_prices=False
    )
