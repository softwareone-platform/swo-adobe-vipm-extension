import datetime as dt
from unittest.mock import call

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
    ERR_DUE_DATE_REACHED,
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
from adobe_vipm.flows.utils.date import reset_due_date
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
    mock_adobe_client,
    mock_mpt_client,
    agreement,
    order_factory,
    transfer_order_parameters_factory,
    fulfillment_parameters_factory,
    adobe_preview_transfer_factory,
    adobe_transfer_factory,
    adobe_items_factory,
    adobe_subscription_factory,
    adobe_customer_factory,
    assets_factory,
    items_factory,
    lines_factory,
    subscriptions_factory,
):
    mocked_get_template = mocker.patch(
        "adobe_vipm.flows.fulfillment.shared.get_product_template_or_default",
        side_effect=[{"id": "TPL-0000"}, {"id": "TPL-1111"}],
    )
    mocker.patch(
        "adobe_vipm.flows.fulfillment.transfer.get_transfer_by_authorization_membership_or_customer",
        return_value=None,
    )
    mocker.patch("adobe_vipm.flows.helpers.get_agreement", return_value=agreement)
    mocker.patch("adobe_vipm.flows.fulfillment.transfer.get_gc_main_agreement", return_value=None)
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
    adobe_transfer_preview = adobe_preview_transfer_factory(
        items=[
            adobe_items_factory()[0],
            adobe_items_factory(offer_id="99999999CA01A12", subscription_id="one-time-sub-id")[0],
        ],
    )
    adobe_customer = adobe_customer_factory()
    adobe_subscription = adobe_subscription_factory()
    adobe_inactive_subscription = adobe_subscription_factory(
        subscription_id="inactive-sub-id", status=AdobeStatus.INACTIVE_OR_GENERIC_FAILURE.value
    )
    adobe_one_time_subscription = adobe_subscription_factory(
        offer_id="99999999CA01A12", subscription_id="one-time-sub-id", autorenewal_enabled=False
    )
    mock_adobe_client.preview_transfer.return_value = adobe_transfer_preview
    mock_adobe_client.create_transfer.return_value = adobe_transfer
    mock_adobe_client.get_customer.return_value = adobe_customer
    mock_adobe_client.get_transfer.return_value = adobe_transfer
    mock_adobe_client.get_subscription.side_effect = [
        adobe_one_time_subscription,
        adobe_subscription,
        adobe_inactive_subscription,
        adobe_one_time_subscription,
    ]
    mock_adobe_client.update_subscription.return_value = adobe_subscription
    order = order_factory(
        lines=[lines_factory()[0], lines_factory(external_vendor_id="99999999CA")[0]],
        order_parameters=transfer_order_parameters_factory(),
    )
    mocked_update_order = mocker.patch("adobe_vipm.flows.fulfillment.shared.update_order")
    mocked_update_agreement = mocker.patch("adobe_vipm.flows.fulfillment.shared.update_agreement")
    asset = assets_factory(adobe_sku="99999999CA01A12")[0]
    mocked_add_asset = mocker.patch(
        "adobe_vipm.flows.fulfillment.transfer.add_asset", return_value=asset
    )
    subscription = subscriptions_factory(commitment_date="2024-01-01")[0]
    mocked_create_subscription = mocker.patch(
        "adobe_vipm.flows.fulfillment.shared.create_subscription", return_value=subscription
    )
    mocked_get_onetime = mocker.patch(
        "adobe_vipm.flows.utils.order.get_product_onetime_items_by_ids",
        return_value=items_factory(item_id=2, external_vendor_id="99999999CA"),
    )
    mocked_process_order = mocker.patch(
        "adobe_vipm.flows.fulfillment.shared.set_processing_template"
    )
    mocked_complete_order = mocker.patch("adobe_vipm.flows.fulfillment.shared.complete_order")
    mocked_sync_agreement = mocker.patch(
        "adobe_vipm.flows.fulfillment.transfer.sync_agreements_by_agreement_ids"
    )

    fulfill_order(mock_mpt_client, order)

    authorization_id = order["authorization"]["id"]
    adobe_customer_address = adobe_customer["companyProfile"]["address"]
    adobe_customer_contact = adobe_customer["companyProfile"]["contacts"][0]
    mock_adobe_client.preview_transfer.assert_called_once_with(authorization_id, "a-membership-id")
    assert mocked_update_order.mock_calls[0].args == (mock_mpt_client, order["id"])
    assert mocked_update_order.mock_calls[0].kwargs == {
        "parameters": {
            "fulfillment": fulfillment_parameters_factory(
                due_date="2024-01-31",
            ),
            "ordering": order["parameters"]["ordering"],
        },
    }
    assert mocked_update_order.mock_calls[1].args == (mock_mpt_client, order["id"])
    assert mocked_update_order.mock_calls[1].kwargs == {
        "externalIds": {
            "vendor": adobe_transfer["transferId"],
        },
    }
    assert mocked_update_order.mock_calls[2].args == (mock_mpt_client, order["id"])
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
    assert mocked_update_order.mock_calls[3].args == (mock_mpt_client, order["id"])
    assert mocked_update_order.mock_calls[3].kwargs == {
        "parameters": {
            "fulfillment": fulfillment_parameters_factory(
                customer_id="a-client-id",
                due_date="2024-01-31",
                coterm_date="",
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
        "externalIds": {"vendor": "a-transfer-id"},
    }

    assert mocked_update_order.mock_calls[4].args == (
        mock_mpt_client,
        order["id"],
    )
    assert mocked_update_order.mock_calls[4].kwargs == {
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
    mocked_update_agreement.assert_has_calls([
        mocker.call(
            mock_mpt_client,
            order["agreement"]["id"],
            externalIds={"vendor": "a-client-id"},
        ),
        mocker.call(
            mock_mpt_client,
            order["agreement"]["id"],
            externalIds={"vendor": "a-client-id"},
        ),
    ])
    mocked_add_asset.assert_called_once_with(
        mock_mpt_client, adobe_one_time_subscription, mocker.ANY, adobe_transfer["lineItems"][2]
    )
    mocked_create_subscription.assert_called_once_with(
        mock_mpt_client,
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
                        "externalId": Param.CURRENT_QUANTITY.value,
                        "value": str(adobe_subscription[Param.CURRENT_QUANTITY.value]),
                    },
                    {
                        "externalId": Param.RENEWAL_QUANTITY.value,
                        "value": str(
                            adobe_subscription["autoRenewal"][Param.RENEWAL_QUANTITY.value]
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
    mocked_process_order.assert_called_once_with(mock_mpt_client, order["id"], {"id": "TPL-0000"})
    mocked_complete_order.assert_called_once_with(
        mock_mpt_client,
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
    mock_adobe_client.get_transfer.assert_called_once_with(
        authorization_id, "a-membership-id", adobe_transfer["transferId"]
    )
    mock_adobe_client.get_subscription.assert_has_calls([
        call(authorization_id, "a-client-id", adobe_one_time_subscription["subscriptionId"]),
        call(authorization_id, "a-client-id", adobe_subscription["subscriptionId"]),
        call(authorization_id, "a-client-id", adobe_inactive_subscription["subscriptionId"]),
    ])
    mocked_get_template.assert_has_calls([
        call(
            mock_mpt_client,
            order["agreement"]["product"]["id"],
            MPT_ORDER_STATUS_PROCESSING,
            TEMPLATE_NAME_TRANSFER,
        ),
        call(
            mock_mpt_client,
            order["agreement"]["product"]["id"],
            MPT_ORDER_STATUS_COMPLETED,
            TEMPLATE_NAME_TRANSFER,
        ),
    ])
    mocked_get_onetime.assert_called_with(
        mock_mpt_client,
        order["agreement"]["product"]["id"],
        [line["item"]["id"] for line in order["lines"]],
    )
    mocked_sync_agreement.assert_called_once_with(
        mock_mpt_client,
        mock_adobe_client,
        [order["agreement"]["id"]],
        dry_run=False,
        sync_prices=False,
    )


@freeze_time("2024-01-01")
def test_transfer_with_no_profile_address(
    mocker,
    mock_adobe_client,
    mock_mpt_client,
    agreement,
    order_factory,
    transfer_order_parameters_factory,
    fulfillment_parameters_factory,
    adobe_preview_transfer_factory,
    adobe_transfer_factory,
    adobe_items_factory,
    adobe_subscription_factory,
    adobe_customer_factory,
    assets_factory,
    items_factory,
    lines_factory,
    subscriptions_factory,
):
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
    mocker.patch("adobe_vipm.flows.fulfillment.transfer.get_gc_main_agreement", return_value=None)
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
    adobe_transfer_preview = adobe_preview_transfer_factory(
        items=[
            adobe_items_factory()[0],
            adobe_items_factory(offer_id="99999999CA01A12", subscription_id="one-time-sub-id")[0],
        ],
    )
    adobe_customer = adobe_customer_factory(company_profile_address_exists=False)
    adobe_subscription = adobe_subscription_factory()
    adobe_inactive_subscription = adobe_subscription_factory(
        subscription_id="inactive-sub-id", status=AdobeStatus.INACTIVE_OR_GENERIC_FAILURE.value
    )
    adobe_one_time_subscription = adobe_subscription_factory(
        offer_id="99999999CA01A12", subscription_id="one-time-sub-id", autorenewal_enabled=False
    )
    mock_adobe_client.preview_transfer.return_value = adobe_transfer_preview
    mock_adobe_client.create_transfer.return_value = adobe_transfer
    mock_adobe_client.get_customer.return_value = adobe_customer
    mock_adobe_client.get_transfer.return_value = adobe_transfer
    mock_adobe_client.get_subscription.side_effect = [
        adobe_one_time_subscription,
        adobe_subscription,
        adobe_inactive_subscription,
        adobe_one_time_subscription,
    ]
    mock_adobe_client.update_subscription.return_value = adobe_subscription
    order = order_factory(
        lines=[lines_factory()[0], lines_factory(external_vendor_id="99999999CA")[0]],
        order_parameters=transfer_order_parameters_factory(),
    )
    mocked_update_order = mocker.patch("adobe_vipm.flows.fulfillment.shared.update_order")
    mocked_update_agreement = mocker.patch("adobe_vipm.flows.fulfillment.shared.update_agreement")
    asset = assets_factory(adobe_sku="99999999CA01A12")[0]
    mocked_add_asset = mocker.patch(
        "adobe_vipm.flows.fulfillment.transfer.add_asset", return_value=asset
    )
    subscription = subscriptions_factory(commitment_date="2024-01-01")[0]
    mocked_create_subscription = mocker.patch(
        "adobe_vipm.flows.fulfillment.shared.create_subscription", return_value=subscription
    )
    mocked_get_onetime = mocker.patch(
        "adobe_vipm.flows.utils.order.get_product_onetime_items_by_ids",
        return_value=items_factory(item_id=2, external_vendor_id="99999999CA"),
    )
    mocked_process_order = mocker.patch(
        "adobe_vipm.flows.fulfillment.shared.set_processing_template"
    )

    mocked_complete_order = mocker.patch("adobe_vipm.flows.fulfillment.shared.complete_order")
    mocked_sync_agreement = mocker.patch(
        "adobe_vipm.flows.fulfillment.transfer.sync_agreements_by_agreement_ids"
    )

    fulfill_order(mock_mpt_client, order)

    authorization_id = order["authorization"]["id"]
    adobe_customer_contact = adobe_customer["companyProfile"]["contacts"][0]

    mock_adobe_client.preview_transfer.assert_called_once_with(authorization_id, "a-membership-id")

    assert mocked_update_order.mock_calls[0].args == (mock_mpt_client, order["id"])
    assert mocked_update_order.mock_calls[0].kwargs == {
        "parameters": {
            "fulfillment": fulfillment_parameters_factory(
                due_date="2024-01-31",
            ),
            "ordering": order["parameters"]["ordering"],
        },
    }
    assert mocked_update_order.mock_calls[1].args == (mock_mpt_client, order["id"])
    assert mocked_update_order.mock_calls[1].kwargs == {
        "externalIds": {
            "vendor": adobe_transfer["transferId"],
        },
    }
    assert mocked_update_order.mock_calls[2].args == (mock_mpt_client, order["id"])
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
    assert mocked_update_order.mock_calls[3].args == (mock_mpt_client, order["id"])
    assert mocked_update_order.mock_calls[3].kwargs == {
        "parameters": {
            "fulfillment": fulfillment_parameters_factory(
                customer_id="a-client-id",
                due_date="2024-01-31",
                coterm_date="",
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
        "externalIds": {
            "vendor": adobe_transfer["transferId"],
        },
    }

    assert mocked_update_order.mock_calls[4].kwargs == {
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

    mocked_update_agreement.assert_has_calls([
        mocker.call(
            mock_mpt_client,
            order["agreement"]["id"],
            externalIds={"vendor": "a-client-id"},
        ),
        mocker.call(
            mock_mpt_client,
            order["agreement"]["id"],
            externalIds={"vendor": "a-client-id"},
        ),
    ])
    mocked_add_asset.assert_called_once_with(
        mock_mpt_client, adobe_one_time_subscription, mocker.ANY, adobe_transfer["lineItems"][2]
    )
    mocked_create_subscription.assert_called_once_with(
        mock_mpt_client,
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
                        "externalId": Param.CURRENT_QUANTITY.value,
                        "value": str(adobe_subscription[Param.CURRENT_QUANTITY.value]),
                    },
                    {
                        "externalId": Param.RENEWAL_QUANTITY.value,
                        "value": str(
                            adobe_subscription["autoRenewal"][Param.RENEWAL_QUANTITY.value]
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
    mocked_process_order.assert_called_once_with(mock_mpt_client, order["id"], {"id": "TPL-0000"})
    mocked_complete_order.assert_called_once_with(
        mock_mpt_client,
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
    mock_adobe_client.get_transfer.assert_called_once_with(
        authorization_id, "a-membership-id", adobe_transfer["transferId"]
    )
    mock_adobe_client.get_subscription.assert_has_calls([
        call(authorization_id, "a-client-id", adobe_one_time_subscription["subscriptionId"]),
        call(authorization_id, "a-client-id", adobe_subscription["subscriptionId"]),
        call(authorization_id, "a-client-id", adobe_inactive_subscription["subscriptionId"]),
    ])
    mocked_get_template.assert_has_calls([
        call(
            mock_mpt_client,
            order["agreement"]["product"]["id"],
            MPT_ORDER_STATUS_PROCESSING,
            TEMPLATE_NAME_TRANSFER,
        ),
        call(
            mock_mpt_client,
            order["agreement"]["product"]["id"],
            MPT_ORDER_STATUS_COMPLETED,
            TEMPLATE_NAME_TRANSFER,
        ),
    ])
    mocked_get_onetime.assert_called_with(
        mock_mpt_client,
        order["agreement"]["product"]["id"],
        [line["item"]["id"] for line in order["lines"]],
    )
    mocked_sync_agreement.assert_called_once_with(
        mock_mpt_client,
        mock_adobe_client,
        [order["agreement"]["id"]],
        dry_run=False,
        sync_prices=False,
    )


@freeze_time("2025-01-01")
def test_transfer_not_ready(
    mocker,
    mock_adobe_client,
    mock_mpt_client,
    agreement,
    order_factory,
    transfer_order_parameters_factory,
    fulfillment_parameters_factory,
    adobe_transfer_factory,
):
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
    mock_adobe_client.create_transfer.return_value = adobe_transfer
    mock_adobe_client.get_transfer.return_value = adobe_transfer
    mocked_update_order = mocker.patch("adobe_vipm.flows.fulfillment.shared.update_order")
    mocked_complete_order = mocker.patch("adobe_vipm.flows.fulfillment.shared.complete_order")
    order = order_factory(
        order_parameters=transfer_order_parameters_factory(),
        external_ids={"vendor": "a-transfer-id"},
    )

    fulfill_order(mock_mpt_client, order)

    authorization_id = order["authorization"]["id"]

    assert mocked_update_order.mock_calls[0].args == (mock_mpt_client, order["id"])
    assert mocked_update_order.mock_calls[0].kwargs == {
        "parameters": {
            "fulfillment": fulfillment_parameters_factory(
                due_date="2025-01-31",
            ),
            "ordering": transfer_order_parameters_factory(),
        },
    }

    mocked_complete_order.assert_not_called()
    mock_adobe_client.get_transfer.assert_called_once_with(
        authorization_id, "a-membership-id", adobe_transfer["transferId"]
    )


@freeze_time("2026-01-01")
def test_transfer_reached_due_date(
    mocker,
    mock_adobe_client,
    mock_mpt_client,
    agreement,
    order_factory,
    transfer_order_parameters_factory,
    fulfillment_parameters_factory,
    adobe_transfer_factory,
):
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

    mock_adobe_client.create_transfer.return_value = adobe_transfer
    mock_adobe_client.get_transfer.return_value = adobe_transfer
    mocker.patch(
        "adobe_vipm.flows.fulfillment.transfer.get_adobe_client",
        return_value=mock_adobe_client,
    )

    mocked_update_order = mocker.patch("adobe_vipm.flows.fulfillment.shared.update_order")
    mocked_fail_order = mocker.patch("adobe_vipm.flows.fulfillment.shared.fail_order")

    order = order_factory(
        order_parameters=transfer_order_parameters_factory(),
        fulfillment_parameters=fulfillment_parameters_factory(
            due_date="2025-01-01",
        ),
        external_ids={"vendor": "a-transfer-id"},
    )

    mocked_notification = mocker.patch("adobe_vipm.flows.fulfillment.shared.send_mpt_notification")
    mocked_sync_agreements_by_agreement_ids = mocker.patch(
        "adobe_vipm.flows.fulfillment.shared.sync_agreements_by_agreement_ids"
    )

    fulfill_order(mock_mpt_client, order)

    mocked_update_order.assert_not_called()

    reset_due_date(order)

    mocked_fail_order.assert_called_once_with(
        mock_mpt_client,
        order["id"],
        ERR_DUE_DATE_REACHED.to_dict(due_date="2025-01-01"),
        parameters=order["parameters"],
    )

    mocked_notification.assert_called_once()
    mocked_sync_agreements_by_agreement_ids.assert_called_once()


def test_transfer_unexpected_status(
    mocker,
    mock_adobe_client,
    agreement,
    order_factory,
    transfer_order_parameters_factory,
    adobe_transfer_factory,
    mock_mpt_client,
    mock_sync_agreements_by_agreement_ids,
):
    mocker.patch(
        "adobe_vipm.flows.fulfillment.transfer.get_transfer_by_authorization_membership_or_customer",
        return_value=None,
    )
    mocker.patch("adobe_vipm.flows.helpers.get_agreement", return_value=agreement)

    adobe_transfer = adobe_transfer_factory(status="9999")

    mock_adobe_client.create_transfer.return_value = adobe_transfer
    mock_adobe_client.get_transfer.return_value = adobe_transfer
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
        mock_mpt_client, mock_adobe_client, [agreement["id"]], dry_run=False, sync_prices=False
    )


def test_transfer_items_mismatch(
    mocker,
    mock_adobe_client,
    agreement,
    order_factory,
    transfer_order_parameters_factory,
    adobe_preview_transfer_factory,
    adobe_items_factory,
    mock_mpt_client,
    mock_sync_agreements_by_agreement_ids,
):
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

    mock_adobe_client.preview_transfer.return_value = adobe_transfer_preview
    mocker.patch(
        "adobe_vipm.flows.fulfillment.transfer.get_adobe_client",
        return_value=mock_adobe_client,
    )

    mocked_fail_order = mocker.patch("adobe_vipm.flows.fulfillment.shared.fail_order")

    order = order_factory(order_parameters=transfer_order_parameters_factory())

    fulfill_order(mock_mpt_client, order)

    authorization_id = order["authorization"]["id"]

    mock_adobe_client.preview_transfer.assert_called_once_with(
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
        mock_mpt_client, mock_adobe_client, [agreement["id"]], dry_run=False, sync_prices=False
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
    mock_adobe_client,
    mock_mpt_client,
    agreement,
    order_factory,
    transfer_order_parameters_factory,
    adobe_api_error_factory,
    transfer_status,
):
    mocker.patch(
        "adobe_vipm.flows.fulfillment.shared.get_product_template_or_default",
        return_value={"id": "TPL-964-112"},
    )
    mocker.patch(
        "adobe_vipm.flows.fulfillment.transfer.get_transfer_by_authorization_membership_or_customer",
        return_value=None,
    )
    mocker.patch("adobe_vipm.flows.fulfillment.transfer.get_gc_main_agreement", return_value=None)
    mocker.patch(
        "adobe_vipm.flows.fulfillment.transfer.get_gc_agreement_deployments_by_main_agreement",
        return_value=None,
    )
    mocker.patch("adobe_vipm.flows.helpers.get_agreement", return_value=agreement)
    adobe_error = AdobeAPIError(
        400,
        adobe_api_error_factory(
            transfer_status,
            "some error",
        ),
    )
    mock_adobe_client.preview_transfer.side_effect = adobe_error
    mocker.patch(
        "adobe_vipm.flows.fulfillment.transfer.get_adobe_client", return_value=mock_adobe_client
    )
    mocked_query_order = mocker.patch("adobe_vipm.flows.fulfillment.shared.query_order")
    order = order_factory(order_parameters=transfer_order_parameters_factory())

    fulfill_order(mock_mpt_client, order)

    authorization_id = order["authorization"]["id"]
    mock_adobe_client.preview_transfer.assert_called_once_with(authorization_id, "a-membership-id")
    param = get_ordering_parameter(order, Param.MEMBERSHIP_ID.value)
    order = set_ordering_parameter_error(
        order,
        Param.MEMBERSHIP_ID.value,
        ERR_ADOBE_MEMBERSHIP_ID.to_dict(title=param["name"], details=str(adobe_error)),
    )
    mocked_query_order.assert_called_once_with(
        mock_mpt_client, order["id"], parameters=order["parameters"], template={"id": "TPL-964-112"}
    )


def test_transfer_membership_not_found(
    mocker,
    mock_adobe_client,
    mock_mpt_client,
    agreement,
    order_factory,
    transfer_order_parameters_factory,
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
    mocker.patch(
        "adobe_vipm.flows.fulfillment.transfer.get_transfer_by_authorization_membership_or_customer",
        return_value=None,
    )
    mocker.patch("adobe_vipm.flows.helpers.get_agreement", return_value=agreement)
    adobe_error = AdobeHttpError(404, "Not found")
    mock_adobe_client.preview_transfer.side_effect = adobe_error
    mocker.patch(
        "adobe_vipm.flows.fulfillment.transfer.get_adobe_client", return_value=mock_adobe_client
    )
    mocked_query_order = mocker.patch("adobe_vipm.flows.fulfillment.shared.query_order")
    order = order_factory(order_parameters=transfer_order_parameters_factory())

    fulfill_order(mock_mpt_client, order)

    authorization_id = order["authorization"]["id"]
    mock_adobe_client.preview_transfer.assert_called_once_with(authorization_id, "a-membership-id")
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
        mock_mpt_client,
        order["id"],
        parameters=order["parameters"],
        template={"id": "TPL-964-112"},
    )


@pytest.mark.parametrize("transfer_status", UNRECOVERABLE_TRANSFER_STATUSES)
def test_transfer_unrecoverable_status(
    mocker,
    mock_adobe_client,
    agreement,
    order_factory,
    transfer_order_parameters_factory,
    adobe_api_error_factory,
    transfer_status,
    mock_sync_agreements_by_agreement_ids,
    mock_mpt_client,
):
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
    adobe_error = AdobeAPIError(400, adobe_api_error_factory(transfer_status, "some error"))
    mock_adobe_client.preview_transfer.side_effect = adobe_error
    mocker.patch(
        "adobe_vipm.flows.fulfillment.transfer.get_adobe_client", return_value=mock_adobe_client
    )
    mocker.patch("adobe_vipm.flows.fulfillment.transfer.get_gc_main_agreement", return_value=None)
    mocker.patch(
        "adobe_vipm.flows.fulfillment.transfer.get_gc_agreement_deployments_by_main_agreement",
        return_value=None,
    )
    mocked_fail_order = mocker.patch("adobe_vipm.flows.fulfillment.shared.fail_order")
    order = order_factory(order_parameters=transfer_order_parameters_factory())

    fulfill_order(mock_mpt_client, order)

    authorization_id = order["authorization"]["id"]

    mock_adobe_client.preview_transfer.assert_called_once_with(authorization_id, "a-membership-id")
    mocked_fail_order.assert_called_once_with(
        mock_mpt_client,
        order["id"],
        ERR_ADOBE_TRANSFER_PREVIEW.to_dict(error=str(adobe_error)),
        parameters=order["parameters"],
    )
    mock_sync_agreements_by_agreement_ids.assert_called_once_with(
        mock_mpt_client, mock_adobe_client, [agreement["id"]], dry_run=False, sync_prices=False
    )


def test_create_transfer_fail(
    mocker,
    mock_adobe_client,
    agreement,
    order_factory,
    transfer_order_parameters_factory,
    adobe_preview_transfer_factory,
    mock_mpt_client,
    mock_sync_agreements_by_agreement_ids,
):
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
    mock_adobe_client.preview_transfer.return_value = adobe_transfer_preview
    mock_adobe_client.create_transfer.side_effect = AdobeError("Unexpected error")
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
        mock_mpt_client, mock_adobe_client, [agreement["id"]], dry_run=False, sync_prices=False
    )


@freeze_time("2012-01-14 12:00:01", tz_offset=0)
def test_fulfill_transfer_order_already_migrated(
    mocker,
    mock_adobe_client,
    mock_mpt_client,
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
    mocker.patch("adobe_vipm.flows.fulfillment.transfer.get_gc_main_agreement", return_value=None)
    mocker.patch(
        "adobe_vipm.flows.fulfillment.transfer.get_gc_agreement_deployments_by_main_agreement",
        return_value=None,
    )
    order_params = transfer_order_parameters_factory()
    order = order_factory(order_parameters=order_params)
    mocker.patch("adobe_vipm.flows.helpers.get_agreement", return_value=agreement)
    mocked_transfer = mocker.MagicMock(
        membership_id="membership-id",
        customer_id="customer-id",
        transfer_id="transfer-id",
        customer_benefits_3yc_status=None,
    )
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
    mocked_update_order = mocker.patch("adobe_vipm.flows.fulfillment.shared.update_order")
    mocked_complete_order = mocker.patch("adobe_vipm.flows.fulfillment.shared.complete_order")
    transfer_items = adobe_items_factory(subscription_id="sub-id")
    adobe_transfer = adobe_transfer_factory(items=transfer_items)
    adobe_subscription = adobe_subscription_factory(current_quantity=170, subscription_id="sub-id")
    mock_adobe_client.get_transfer.return_value = adobe_transfer
    mock_adobe_client.get_customer.return_value = adobe_customer
    mock_adobe_client.get_subscription.return_value = adobe_subscription
    mock_adobe_client.get_subscriptions.return_value = {
        "items": [adobe_subscription],
    }
    mocker.patch(
        "adobe_vipm.flows.fulfillment.transfer.get_adobe_client", return_value=mock_adobe_client
    )

    fulfill_order(mock_mpt_client, order)

    membership_id_param = get_ordering_parameter(updated_order, Param.MEMBERSHIP_ID.value)
    mocked_get_transfer.assert_called_once_with(
        order["agreement"]["product"]["id"],
        adobe_authorizations_file["authorizations"][0]["authorization_id"],
        membership_id_param["value"],
    )
    mocked_process_order.assert_called_once_with(mock_mpt_client, order["id"], {"id": "TPL-0000"})
    mocked_complete_order.assert_called_once_with(
        mock_mpt_client,
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
    assert mocked_update_order.mock_calls[0].args == (mock_mpt_client, order["id"])
    assert mocked_update_order.mock_calls[0].kwargs == {
        "parameters": {
            "fulfillment": fulfillment_parameters_factory(
                due_date="2012-02-13",
            ),
            "ordering": order["parameters"]["ordering"],
        },
    }

    assert mocked_update_order.mock_calls[1].args == (mock_mpt_client, order["id"])
    assert mocked_transfer.status == "synchronized"
    assert mocked_transfer.synchronized_at == dt.datetime(2012, 1, 14, 12, 00, 1, tzinfo=dt.UTC)
    assert mocked_transfer.mpt_order_id == order["id"]
    mocked_transfer.save.assert_called_once()
    mocked_get_template.assert_has_calls([
        call(
            mock_mpt_client,
            order["agreement"]["product"]["id"],
            MPT_ORDER_STATUS_PROCESSING,
            TEMPLATE_NAME_BULK_MIGRATE,
        ),
        call(
            mock_mpt_client,
            order["agreement"]["product"]["id"],
            MPT_ORDER_STATUS_COMPLETED,
            TEMPLATE_NAME_BULK_MIGRATE,
        ),
    ])
    mock_adobe_client.update_subscription.assert_called_once_with(
        adobe_authorizations_file["authorizations"][0]["authorization_id"],
        mocked_transfer.customer_id,
        transfer_items[0]["subscriptionId"],
        auto_renewal=True,
    )


@freeze_time("2012-01-14 12:00:01", tz_offset=0)
def test_fulfill_transfer_order_with_no_profile_address_already_migrated(
    mocker,
    mock_adobe_client,
    mock_mpt_client,
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
    mocked_transfer = mocker.MagicMock(
        membership_id="membership-id",
        customer_id="customer-id",
        transfer_id="transfer-id",
        customer_benefits_3yc_status=None,
    )
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
    mock_adobe_client.get_transfer.return_value = adobe_transfer
    mock_adobe_client.get_customer.return_value = adobe_customer
    mock_adobe_client.get_subscription.return_value = adobe_subscription
    mock_adobe_client.get_subscriptions.return_value = {"items": [adobe_subscription]}
    mocker.patch(
        "adobe_vipm.flows.fulfillment.transfer.get_adobe_client", return_value=mock_adobe_client
    )

    fulfill_order(mock_mpt_client, order)

    membership_id_param = get_ordering_parameter(updated_order, Param.MEMBERSHIP_ID.value)
    mocked_get_transfer.assert_called_once_with(
        order["agreement"]["product"]["id"],
        adobe_authorizations_file["authorizations"][0]["authorization_id"],
        membership_id_param["value"],
    )
    mocked_process_order.assert_called_once_with(mock_mpt_client, order["id"], {"id": "TPL-0000"})
    mocked_complete_order.assert_called_once_with(
        mock_mpt_client,
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
    assert mocked_update_order.mock_calls[0].args == (mock_mpt_client, order["id"])
    assert mocked_update_order.mock_calls[0].kwargs == {
        "parameters": {
            "fulfillment": fulfillment_parameters_factory(
                due_date="2012-02-13",
            ),
            "ordering": order["parameters"]["ordering"],
        },
    }
    assert mocked_update_order.mock_calls[1].args == (mock_mpt_client, order["id"])
    assert mocked_transfer.status == "synchronized"
    assert mocked_transfer.synchronized_at == dt.datetime(2012, 1, 14, 12, 00, 1, tzinfo=dt.UTC)
    assert mocked_transfer.mpt_order_id == order["id"]
    mocked_transfer.save.assert_called_once()
    mocked_get_template.assert_has_calls([
        call(
            mock_mpt_client,
            order["agreement"]["product"]["id"],
            MPT_ORDER_STATUS_PROCESSING,
            TEMPLATE_NAME_BULK_MIGRATE,
        ),
        call(
            mock_mpt_client,
            order["agreement"]["product"]["id"],
            MPT_ORDER_STATUS_COMPLETED,
            TEMPLATE_NAME_BULK_MIGRATE,
        ),
    ])
    mock_adobe_client.update_subscription.assert_called_once_with(
        adobe_authorizations_file["authorizations"][0]["authorization_id"],
        mocked_transfer.customer_id,
        transfer_items[0]["subscriptionId"],
        auto_renewal=True,
    )


@freeze_time("2012-01-14 12:00:01")
def test_fulfill_transfer_order_already_migrated_error_order_line_updated(
    mocker,
    mock_adobe_client,
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

    mocked_transfer = mocker.MagicMock(
        membership_id="membership-id",
        customer_id="customer-id",
        transfer_id="transfer-id",
        customer_benefits_3yc_status=None,
    )
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
        "adobe_vipm.flows.fulfillment.shared.set_processing_template"
    )
    product_items = items_factory()
    mocker.patch(
        "adobe_vipm.flows.fulfillment.transfer.get_product_items_by_skus",
        return_value=product_items,
    )
    mocked_update_order = mocker.patch("adobe_vipm.flows.fulfillment.shared.update_order")
    transfer_items = adobe_items_factory(
        subscription_id="sub-id", renewal_date=dt.datetime.now(tz=dt.UTC).date().isoformat()
    ) + adobe_items_factory(
        line_number=2,
        offer_id="99999999CA01A12",
        subscription_id="onetime-sub-id",
    )

    adobe_transfer = adobe_transfer_factory(items=transfer_items)
    adobe_subscription = adobe_subscription_factory()
    mock_adobe_client.get_transfer.return_value = adobe_transfer
    mock_adobe_client.get_customer.return_value = adobe_customer
    mock_adobe_client.get_subscriptions.return_value = {
        "items": [adobe_subscription],
    }
    mocker.patch(
        "adobe_vipm.flows.fulfillment.transfer.get_adobe_client", return_value=mock_adobe_client
    )
    mocked_fail_order = mocker.patch("adobe_vipm.flows.fulfillment.shared.fail_order")

    fulfill_order(mock_mpt_client, order)

    mocked_process_order.assert_called_once_with(mock_mpt_client, order["id"], {"id": "TPL-0000"})
    mocked_fail_order.assert_called_once_with(
        mock_mpt_client,
        order["id"],
        ERR_UPDATING_TRANSFER_ITEMS.to_dict(),
        parameters=order["parameters"],
    )
    assert mocked_update_order.mock_calls[0].args == (mock_mpt_client, order["id"])
    assert mocked_update_order.mock_calls[0].kwargs == {"parameters": order["parameters"]}
    mock_sync_agreements_by_agreement_ids.assert_called_once_with(
        mock_mpt_client, mock_adobe_client, [agreement["id"]], dry_run=False, sync_prices=False
    )


@freeze_time("2012-01-14 12:00:01", tz_offset=0)
def test_fulfill_transfer_order_already_migrated_3yc(
    mocker,
    mock_adobe_client,
    mock_mpt_client,
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
    mocked_get_transfer = mocker.patch(
        "adobe_vipm.flows.fulfillment.transfer.get_transfer_by_authorization_membership_or_customer",
        return_value=mocked_transfer,
    )
    mocker.patch("adobe_vipm.flows.utils.order.get_product_onetime_items_by_ids", return_value=[])
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
        "adobe_vipm.flows.fulfillment.shared.set_processing_template"
    )
    mocked_update_order = mocker.patch("adobe_vipm.flows.fulfillment.shared.update_order")
    mocked_complete_order = mocker.patch("adobe_vipm.flows.fulfillment.shared.complete_order")
    transfer_items = adobe_items_factory(subscription_id="sub-id")
    adobe_transfer = adobe_transfer_factory(items=transfer_items)
    adobe_subscription = adobe_subscription_factory(current_quantity=170)
    mock_adobe_client.get_transfer.return_value = adobe_transfer
    mock_adobe_client.get_customer.return_value = adobe_customer
    mock_adobe_client.get_subscription.return_value = adobe_subscription
    mock_adobe_client.get_subscriptions.return_value = {"items": [adobe_subscription]}
    mocker.patch(
        "adobe_vipm.flows.fulfillment.transfer.get_adobe_client", return_value=mock_adobe_client
    )

    fulfill_order(mock_mpt_client, order)

    membership_id_param = get_ordering_parameter(updated_order, Param.MEMBERSHIP_ID.value)
    mocked_get_transfer.assert_called_once_with(
        order["agreement"]["product"]["id"],
        adobe_authorizations_file["authorizations"][0]["authorization_id"],
        membership_id_param["value"],
    )
    mocked_process_order.assert_called_once_with(mock_mpt_client, order["id"], {"id": "TPL-0000"})

    mocked_complete_order.assert_called_once_with(
        mock_mpt_client,
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

    assert mocked_update_order.mock_calls[2].args == (mock_mpt_client, order["id"])
    assert mocked_update_order.mock_calls[1].kwargs == {
        "externalIds": updated_order["externalIds"],
        "parameters": {
            "fulfillment": fulfillment_parameters_factory(
                customer_id="a-client-id",
                due_date="2012-02-13",
                coterm_date="",
            ),
            "ordering": updated_order["parameters"]["ordering"],
        },
    }
    assert mocked_transfer.status == "synchronized"
    assert mocked_transfer.synchronized_at == dt.datetime(2012, 1, 14, 12, 00, 1, tzinfo=dt.UTC)
    assert mocked_transfer.mpt_order_id == order["id"]
    mocked_transfer.save.assert_called_once()
    assert mocked_get_template.mock_calls[0].args == (
        mock_mpt_client,
        order["agreement"]["product"]["id"],
        MPT_ORDER_STATUS_PROCESSING,
        TEMPLATE_NAME_BULK_MIGRATE,
    )
    assert mocked_get_template.mock_calls[1].args == (
        mock_mpt_client,
        order["agreement"]["product"]["id"],
        MPT_ORDER_STATUS_COMPLETED,
        TEMPLATE_NAME_BULK_MIGRATE,
    )
    mock_adobe_client.update_subscription.assert_not_called()


@freeze_time("2012-01-14 12:00:01", tz_offset=0)
def test_fulfill_transfer_order_already_migrated_(
    mocker,
    mock_adobe_client,
    mock_mpt_client,
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
    mocker.patch("adobe_vipm.flows.fulfillment.transfer.get_gc_main_agreement", return_value=None)
    mocker.patch(
        "adobe_vipm.flows.fulfillment.transfer.get_gc_agreement_deployments_by_main_agreement",
        return_value=None,
    )
    product_items = items_factory()
    mocker.patch(
        "adobe_vipm.flows.fulfillment.transfer.get_product_items_by_skus",
        return_value=product_items,
    )
    mocked_transfer = mocker.MagicMock(
        customer_id="customer-id",
        transfer_id="transfer-id",
        customer_benefits_3yc_status=ThreeYearCommitmentStatus.EXPIRED.value,
    )
    adobe_customer = adobe_customer_factory()
    adobe_customer_address = adobe_customer["companyProfile"]["address"]
    adobe_customer_contact = adobe_customer["companyProfile"]["contacts"][0]
    updated_order = order_factory(
        fulfillment_parameters=fulfillment_parameters_factory(
            customer_id="a-client-id", due_date="2025-01-01", coterm_date="2024-08-04"
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
    mocked_get_transfer = mocker.patch(
        "adobe_vipm.flows.fulfillment.transfer.get_transfer_by_authorization_membership_or_customer",
        return_value=mocked_transfer,
    )
    mocker.patch("adobe_vipm.flows.utils.order.get_product_onetime_items_by_ids", return_value=[])
    mocker.patch(
        "adobe_vipm.flows.fulfillment.transfer.add_subscription",
        return_value=subscriptions_factory(commitment_date="2024-08-04")[0],
    )
    mocked_process_order = mocker.patch(
        "adobe_vipm.flows.fulfillment.shared.set_processing_template"
    )
    mocked_update_order = mocker.patch("adobe_vipm.flows.fulfillment.shared.update_order")
    mocker.patch("adobe_vipm.flows.fulfillment.shared.complete_order")
    transfer_items = adobe_items_factory(subscription_id="sub-id")
    adobe_transfer = adobe_transfer_factory(status=AdobeStatus.PENDING.value, items=transfer_items)
    adobe_subscription = adobe_subscription_factory(
        status=AdobeStatus.PENDING.value, current_quantity=170
    )

    mock_adobe_client.get_transfer.return_value = adobe_transfer
    mock_adobe_client.get_customer.return_value = adobe_customer
    mock_adobe_client.get_subscription.return_value = adobe_subscription
    mock_adobe_client.get_subscriptions.return_value = {
        "items": [adobe_subscription],
    }

    mocker.patch(
        "adobe_vipm.flows.fulfillment.transfer.get_adobe_client",
        return_value=mock_adobe_client,
    )

    fulfill_order(mock_mpt_client, order)

    membership_id_param = get_ordering_parameter(updated_order, Param.MEMBERSHIP_ID.value)
    mocked_get_transfer.assert_called_once_with(
        order["agreement"]["product"]["id"],
        adobe_authorizations_file["authorizations"][0]["authorization_id"],
        membership_id_param["value"],
    )
    mocked_process_order.assert_called_once_with(mock_mpt_client, order["id"], {"id": "TPL-0000"})
    assert mocked_update_order.mock_calls[1].args == (mock_mpt_client, order["id"])
    assert mocked_transfer.status == "synchronized"
    assert mocked_transfer.synchronized_at == dt.datetime(2012, 1, 14, 12, 00, 1, tzinfo=dt.UTC)
    assert mocked_transfer.mpt_order_id == order["id"]
    mocked_transfer.save.assert_called_once()
    assert mocked_get_template.mock_calls[0].args == (
        mock_mpt_client,
        order["agreement"]["product"]["id"],
        MPT_ORDER_STATUS_PROCESSING,
        TEMPLATE_NAME_BULK_MIGRATE,
    )
    assert mocked_get_template.mock_calls[1].args == (
        mock_mpt_client,
        order["agreement"]["product"]["id"],
        MPT_ORDER_STATUS_COMPLETED,
        TEMPLATE_NAME_BULK_MIGRATE,
    )
    mock_adobe_client.update_subscription.assert_not_called()


def test_fulfill_transfer_order_migration_running(
    mocker,
    mock_mpt_client,
    order_factory,
    transfer_order_parameters_factory,
    adobe_authorizations_file,
    agreement,
    mock_adobe_client,
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

    mocked_transfer = mocker.MagicMock(
        status="running", customer_id="customer-id", transfer_id="transfer-id"
    )
    mocked_get_transfer = mocker.patch(
        "adobe_vipm.flows.fulfillment.transfer.get_transfer_by_authorization_membership_or_customer",
        return_value=mocked_transfer,
    )
    mocked_query_order = mocker.patch("adobe_vipm.flows.fulfillment.shared.query_order")
    mocker.patch("adobe_vipm.flows.fulfillment.transfer.get_adobe_client")

    fulfill_order(mock_mpt_client, order)

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
        mock_mpt_client, order["id"], parameters=order["parameters"], template={"id": "TPL-964-112"}
    )


def test_fulfill_transfer_order_migration_synchronized(
    mocker,
    mock_mpt_client,
    order_factory,
    transfer_order_parameters_factory,
    adobe_authorizations_file,
    agreement,
    mock_sync_agreements_by_agreement_ids,
    mock_adobe_client,
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

    mocked_transfer = mocker.MagicMock(
        status="synchronized", customer_id="customer-id", transfer_id="transfer-id"
    )
    mocked_get_transfer = mocker.patch(
        "adobe_vipm.flows.fulfillment.transfer.get_transfer_by_authorization_membership_or_customer",
        return_value=mocked_transfer,
    )
    mocked_fail_order = mocker.patch("adobe_vipm.flows.fulfillment.shared.fail_order")
    mocker.patch("adobe_vipm.flows.fulfillment.transfer.get_adobe_client")

    fulfill_order(mock_mpt_client, order)

    membership_param = get_ordering_parameter(order, Param.MEMBERSHIP_ID.value)
    mocked_get_transfer.assert_called_once_with(
        order["agreement"]["product"]["id"],
        adobe_authorizations_file["authorizations"][0]["authorization_id"],
        membership_param["value"],
    )
    mocked_fail_order.assert_called_once_with(
        mock_mpt_client,
        order["id"],
        ERR_MEMBERSHIP_HAS_BEEN_TRANSFERED.to_dict(),
        parameters=order["parameters"],
    )
    mock_sync_agreements_by_agreement_ids.assert_called_once_with(
        mock_mpt_client, mock_adobe_client, [agreement["id"]], dry_run=False, sync_prices=False
    )


@freeze_time("2024-01-01")
def test_transfer_3yc_customer(
    mocker,
    mock_adobe_client,
    mock_mpt_client,
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

    mock_adobe_client.preview_transfer.return_value = adobe_transfer_preview
    mock_adobe_client.create_transfer.return_value = adobe_transfer
    mock_adobe_client.get_customer.return_value = adobe_customer
    mock_adobe_client.get_transfer.return_value = adobe_transfer
    mock_adobe_client.get_subscription.return_value = adobe_subscription
    mocker.patch(
        "adobe_vipm.flows.fulfillment.transfer.get_adobe_client", return_value=mock_adobe_client
    )
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

    fulfill_order(mock_mpt_client, order)

    authorization_id = order["authorization"]["id"]
    adobe_customer_address = adobe_customer["companyProfile"]["address"]
    adobe_customer_contact = adobe_customer["companyProfile"]["contacts"][0]
    mock_adobe_client.preview_transfer.assert_called_once_with(authorization_id, "a-membership-id")

    assert mocked_update_order.mock_calls[0].args == (mock_mpt_client, order["id"])
    assert mocked_update_order.mock_calls[0].kwargs == {
        "parameters": {
            "fulfillment": fulfillment_parameters_factory(
                due_date="2024-01-31",
            ),
            "ordering": order["parameters"]["ordering"],
        },
    }
    assert mocked_update_order.mock_calls[1].args == (mock_mpt_client, order["id"])
    assert mocked_update_order.mock_calls[1].kwargs == {
        "externalIds": {
            "vendor": adobe_transfer["transferId"],
        },
    }
    assert mocked_update_order.mock_calls[2].args == (
        mock_mpt_client,
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
    assert mocked_update_order.mock_calls[3].args == (mock_mpt_client, order["id"])
    assert mocked_update_order.mock_calls[3].kwargs == {
        "parameters": {
            "fulfillment": fulfillment_parameters_factory(
                customer_id="a-client-id",
                due_date="2024-01-31",
                p3yc_enroll_status=adobe_3yc_commitment["status"],
                p3yc_start_date=adobe_3yc_commitment["startDate"],
                p3yc_end_date=adobe_3yc_commitment["endDate"],
                coterm_date="",
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
        "externalIds": {"vendor": "a-transfer-id"},
    }

    assert mocked_update_order.mock_calls[4].args == (
        mock_mpt_client,
        order["id"],
    )
    assert mocked_update_order.mock_calls[4].kwargs == {
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
        mock_mpt_client,
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
                        "externalId": Param.CURRENT_QUANTITY.value,
                        "value": str(adobe_subscription[Param.CURRENT_QUANTITY.value]),
                    },
                    {
                        "externalId": Param.RENEWAL_QUANTITY.value,
                        "value": str(
                            adobe_subscription["autoRenewal"][Param.RENEWAL_QUANTITY.value]
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
        mock_mpt_client,
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
    mock_adobe_client.get_transfer.assert_called_once_with(
        authorization_id, "a-membership-id", adobe_transfer["transferId"]
    )
    mock_adobe_client.get_subscription.assert_called_once_with(
        authorization_id,
        "a-client-id",
        adobe_subscription["subscriptionId"],
    )
    mocked_sync_agreement.assert_called_once_with(
        mock_mpt_client,
        mock_adobe_client,
        [order["agreement"]["id"]],
        dry_run=False,
        sync_prices=False,
    )


@freeze_time("2024-01-01")
def test_transfer_3yc_customer_with_no_profile_address(
    mocker,
    mock_adobe_client,
    mock_mpt_client,
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
    mock_adobe_client.preview_transfer.return_value = adobe_transfer_preview
    mock_adobe_client.create_transfer.return_value = adobe_transfer
    mock_adobe_client.get_customer.return_value = adobe_customer
    mock_adobe_client.get_transfer.return_value = adobe_transfer
    mock_adobe_client.get_subscription.return_value = adobe_subscription
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

    fulfill_order(mock_mpt_client, order)

    authorization_id = order["authorization"]["id"]
    adobe_customer_contact = adobe_customer["companyProfile"]["contacts"][0]

    mock_adobe_client.preview_transfer.assert_called_once_with(authorization_id, "a-membership-id")
    assert mocked_update_order.mock_calls[0].args == (mock_mpt_client, order["id"])
    assert mocked_update_order.mock_calls[0].kwargs == {
        "parameters": {
            "fulfillment": fulfillment_parameters_factory(
                due_date="2024-01-31",
            ),
            "ordering": order["parameters"]["ordering"],
        },
    }

    assert mocked_update_order.mock_calls[1].args == (
        mock_mpt_client,
        order["id"],
    )
    assert mocked_update_order.mock_calls[1].kwargs == {
        "externalIds": {
            "vendor": adobe_transfer["transferId"],
        },
    }
    assert mocked_update_order.mock_calls[2].args == (mock_mpt_client, order["id"])
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
    assert mocked_update_order.mock_calls[3].args == (mock_mpt_client, order["id"])
    assert mocked_update_order.mock_calls[3].kwargs == {
        "parameters": {
            "fulfillment": fulfillment_parameters_factory(
                customer_id="a-client-id",
                due_date="2024-01-31",
                p3yc_enroll_status=adobe_3yc_commitment["status"],
                p3yc_start_date=adobe_3yc_commitment["startDate"],
                p3yc_end_date=adobe_3yc_commitment["endDate"],
                coterm_date="",
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
        "externalIds": {"vendor": "a-transfer-id"},
    }

    assert mocked_update_order.mock_calls[4].args == (
        mock_mpt_client,
        order["id"],
    )
    assert mocked_update_order.mock_calls[4].kwargs == {
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
        mock_mpt_client,
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
                        "externalId": Param.CURRENT_QUANTITY.value,
                        "value": str(adobe_subscription[Param.CURRENT_QUANTITY.value]),
                    },
                    {
                        "externalId": Param.RENEWAL_QUANTITY.value,
                        "value": str(
                            adobe_subscription["autoRenewal"][Param.RENEWAL_QUANTITY.value]
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
        mock_mpt_client,
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
    mock_adobe_client.get_transfer.assert_called_once_with(
        authorization_id, "a-membership-id", adobe_transfer["transferId"]
    )
    mock_adobe_client.get_subscription.assert_called_once_with(
        authorization_id,
        "a-client-id",
        adobe_subscription["subscriptionId"],
    )
    mocked_sync_agreement.assert_called_once_with(
        mock_mpt_client,
        mock_adobe_client,
        [order["agreement"]["id"]],
        dry_run=False,
        sync_prices=False,
    )


@freeze_time("2012-01-14 12:00:01")
def test_fulfill_transfer_order_already_migrated_all_items_expired_create_new_order(
    mocker,
    mock_adobe_client,
    mock_mpt_client,
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
    mocked_transfer = mocker.MagicMock(
        membership_id="membership-id",
        customer_id="customer-id",
        transfer_id="transfer-id",
        customer_benefits_3yc_status=None,
    )
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
    mocked_get_transfer = mocker.patch(
        "adobe_vipm.flows.fulfillment.transfer.get_transfer_by_authorization_membership_or_customer",
        return_value=mocked_transfer,
    )
    product_items = items_factory()
    mocker.patch(
        "adobe_vipm.flows.fulfillment.transfer.get_product_items_by_skus",
        return_value=product_items,
    )
    mocker.patch("adobe_vipm.flows.fulfillment.transfer.get_gc_main_agreement", return_value=None)
    mocker.patch(
        "adobe_vipm.flows.fulfillment.transfer.get_gc_agreement_deployments_by_main_agreement",
        return_value=None,
    )
    mocker.patch(
        "adobe_vipm.flows.utils.order.get_product_onetime_items_by_ids",
        return_value=items_factory(item_id=2, external_vendor_id="99999999CA"),
    )
    mocked_process_order = mocker.patch(
        "adobe_vipm.flows.fulfillment.shared.set_processing_template"
    )
    mocked_update_order = mocker.patch("adobe_vipm.flows.fulfillment.shared.update_order")
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
    mock_adobe_client.get_transfer.return_value = adobe_transfer
    mock_adobe_client.get_customer.return_value = adobe_customer
    adobe_preview_order = adobe_order_factory(ORDER_TYPE_PREVIEW)
    mock_adobe_client.create_preview_order.return_value = adobe_preview_order
    mock_adobe_client.create_new_order.return_value = new_order
    mocker.patch(
        "adobe_vipm.flows.fulfillment.transfer.get_adobe_client", return_value=mock_adobe_client
    )
    mocker.patch(
        "adobe_vipm.flows.helpers.get_adobe_client",
        return_value=mock_adobe_client,
    )
    mocker.patch(
        "adobe_vipm.flows.fulfillment.shared.get_adobe_client",
        return_value=mock_adobe_client,
    )

    fulfill_order(mock_mpt_client, order)

    membership_id_param = get_ordering_parameter(updated_order, Param.MEMBERSHIP_ID.value)
    mocked_get_transfer.assert_called_once_with(
        order["agreement"]["product"]["id"],
        adobe_authorizations_file["authorizations"][0]["authorization_id"],
        membership_id_param["value"],
    )
    mocked_process_order.assert_called_once_with(mock_mpt_client, order["id"], {"id": "TPL-0000"})
    assert mocked_update_order.mock_calls[0].args == (mock_mpt_client, order["id"])
    assert mocked_update_order.mock_calls[0].kwargs == {
        "parameters": {
            "fulfillment": fulfillment_parameters_factory(
                due_date="2012-02-13",
            ),
            "ordering": order["parameters"]["ordering"],
        },
    }
    assert mocked_update_order.mock_calls[2].args == (mock_mpt_client, order["id"])
    assert mocked_update_order.mock_calls[2].kwargs == {
        "externalIds": {"vendor": new_order["orderId"]}
    }


@freeze_time("2012-01-14 12:00:01")
def test_fulfill_transfer_order_already_migrated_empty_adobe_items(
    mocker,
    mock_adobe_client,
    mock_mpt_client,
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
    mock_adobe_client.get_transfer.return_value = adobe_transfer
    mock_adobe_client.get_customer.return_value = adobe_customer
    adobe_preview_order = adobe_order_factory(ORDER_TYPE_PREVIEW)
    mock_adobe_client.create_preview_order.return_value = adobe_preview_order
    mock_adobe_client.create_new_order.return_value = new_order
    mocker.patch(
        "adobe_vipm.flows.fulfillment.transfer.get_adobe_client", return_value=mock_adobe_client
    )
    mocker.patch("adobe_vipm.flows.helpers.get_adobe_client", return_value=mock_adobe_client)
    mocker.patch(
        "adobe_vipm.flows.fulfillment.shared.get_adobe_client", return_value=mock_adobe_client
    )

    fulfill_order(mock_mpt_client, order)

    mock_get_product_items_by_skus.assert_not_called()
    membership_id_param = get_ordering_parameter(updated_order, Param.MEMBERSHIP_ID.value)
    mocked_get_transfer.assert_called_once_with(
        order["agreement"]["product"]["id"],
        adobe_authorizations_file["authorizations"][0]["authorization_id"],
        membership_id_param["value"],
    )
    mocked_process_order.assert_called_once_with(mock_mpt_client, order["id"], {"id": "TPL-0000"})

    assert mocked_update_order.mock_calls[0].args == (mock_mpt_client, order["id"])
    assert mocked_update_order.mock_calls[0].kwargs == {
        "parameters": {
            "fulfillment": fulfillment_parameters_factory(
                due_date="2012-02-13",
            ),
            "ordering": order["parameters"]["ordering"],
        },
    }

    assert mocked_update_order.mock_calls[2].args == (mock_mpt_client, order["id"])
    assert mocked_update_order.mock_calls[2].kwargs == {
        "externalIds": {"vendor": new_order["orderId"]}
    }


@freeze_time("2012-01-14 12:00:01", tz_offset=0)
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
    assert mocked_transfer.synchronized_at == dt.datetime(2012, 1, 14, 12, 00, 1, tzinfo=dt.UTC)
    assert mocked_transfer.mpt_order_id == order["id"]
    mocked_next_step.assert_called_once_with(mocked_client, context)


@freeze_time("2024-01-01")
def test_transfer_gc_account_all_deployments_created(
    mocker,
    mock_adobe_client,
    mock_mpt_client,
    agreement,
    order_factory,
    transfer_order_parameters_factory,
    fulfillment_parameters_factory,
    adobe_preview_transfer_factory,
    adobe_transfer_factory,
    adobe_items_factory,
    adobe_subscription_factory,
    adobe_customer_factory,
    assets_factory,
    items_factory,
    lines_factory,
    subscriptions_factory,
):
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
    adobe_transfer_preview = adobe_preview_transfer_factory(
        items=[
            adobe_items_factory()[0],
            adobe_items_factory(offer_id="99999999CA01A12", subscription_id="one-time-sub-id")[0],
        ],
    )
    adobe_customer = adobe_customer_factory(global_sales_enabled=True)
    adobe_subscription = adobe_subscription_factory()
    adobe_inactive_subscription = adobe_subscription_factory(
        subscription_id="inactive-sub-id", status=AdobeStatus.INACTIVE_OR_GENERIC_FAILURE.value
    )
    adobe_one_time_subscription = adobe_subscription_factory(
        offer_id="99999999CA01A12", subscription_id="one-time-sub-id", autorenewal_enabled=False
    )
    mock_adobe_client.preview_transfer.return_value = adobe_transfer_preview
    mock_adobe_client.create_transfer.return_value = adobe_transfer
    mock_adobe_client.get_customer.return_value = adobe_customer
    mock_adobe_client.get_transfer.return_value = adobe_transfer
    mock_adobe_client.get_subscription.side_effect = [
        adobe_one_time_subscription,
        adobe_subscription,
        adobe_inactive_subscription,
        adobe_one_time_subscription,
    ]
    mock_adobe_client.get_customer_deployments_active_status.return_value = [
        {
            "deploymentId": "deployment-id",
            "status": "1000",
            "companyProfile": {"address": {"country": "DE"}},
        }
    ]
    mock_adobe_client.update_subscription.return_value = adobe_subscription
    mocker.patch(
        "adobe_vipm.flows.fulfillment.transfer.get_adobe_client",
        return_value=mock_adobe_client,
    )
    order = order_factory(
        lines=[lines_factory()[0], lines_factory(external_vendor_id="99999999CA")[0]],
        order_parameters=transfer_order_parameters_factory(),
    )
    mocked_update_order = mocker.patch(
        "adobe_vipm.flows.fulfillment.shared.update_order",
    )
    mocked_update_agreement = mocker.patch(
        "adobe_vipm.flows.fulfillment.shared.update_agreement",
    )
    asset = assets_factory(adobe_sku="99999999CA01A12")[0]
    mocked_add_asset = mocker.patch(
        "adobe_vipm.flows.fulfillment.transfer.add_asset", return_value=asset
    )
    subscription = subscriptions_factory(commitment_date="2024-01-01")[0]
    mocked_create_subscription = mocker.patch(
        "adobe_vipm.flows.fulfillment.shared.create_subscription", return_value=subscription
    )
    mocked_get_onetime = mocker.patch(
        "adobe_vipm.flows.utils.order.get_product_onetime_items_by_ids",
        return_value=items_factory(item_id=2, external_vendor_id="99999999CA"),
    )
    mocked_process_order = mocker.patch(
        "adobe_vipm.flows.fulfillment.shared.set_processing_template"
    )
    mocked_complete_order = mocker.patch("adobe_vipm.flows.fulfillment.shared.complete_order")
    mocked_sync_agreement = mocker.patch(
        "adobe_vipm.flows.fulfillment.transfer.sync_agreements_by_agreement_ids"
    )

    fulfill_order(mock_mpt_client, order)

    authorization_id = order["authorization"]["id"]
    adobe_customer_address = adobe_customer["companyProfile"]["address"]
    adobe_customer_contact = adobe_customer["companyProfile"]["contacts"][0]
    mock_adobe_client.preview_transfer.assert_called_once_with(authorization_id, "a-membership-id")
    assert mocked_update_order.mock_calls[0].args == (mock_mpt_client, order["id"])
    assert mocked_update_order.mock_calls[0].kwargs == {
        "parameters": {
            "fulfillment": fulfillment_parameters_factory(
                due_date="2024-01-31",
            ),
            "ordering": order["parameters"]["ordering"],
        },
    }
    assert mocked_update_order.mock_calls[1].args == (mock_mpt_client, order["id"])
    assert mocked_update_order.mock_calls[1].kwargs == {
        "externalIds": {"vendor": adobe_transfer["transferId"]},
    }
    assert mocked_update_order.mock_calls[2].args == (mock_mpt_client, order["id"])
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
    assert mocked_update_order.mock_calls[4].args == (mock_mpt_client, order["id"])
    assert mocked_update_order.mock_calls[4].kwargs == {
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

    mocked_update_agreement.assert_has_calls([
        mocker.call(
            mock_mpt_client,
            order["agreement"]["id"],
            externalIds={"vendor": "a-client-id"},
        ),
        mocker.call(
            mock_mpt_client,
            order["agreement"]["id"],
            externalIds={"vendor": "a-client-id"},
        ),
    ])
    mocked_add_asset.assert_called_once_with(
        mock_mpt_client, adobe_one_time_subscription, mocker.ANY, adobe_transfer["lineItems"][2]
    )
    mocked_create_subscription.assert_called_once_with(
        mock_mpt_client,
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
                        "externalId": Param.CURRENT_QUANTITY.value,
                        "value": str(adobe_subscription[Param.CURRENT_QUANTITY.value]),
                    },
                    {
                        "externalId": Param.RENEWAL_QUANTITY.value,
                        "value": str(
                            adobe_subscription["autoRenewal"][Param.RENEWAL_QUANTITY.value]
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
    mocked_process_order.assert_called_once_with(mock_mpt_client, order["id"], {"id": "TPL-0000"})
    mocked_complete_order.assert_called_once_with(
        mock_mpt_client,
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
    mock_adobe_client.get_transfer.assert_called_once_with(
        authorization_id, "a-membership-id", adobe_transfer["transferId"]
    )
    mock_adobe_client.get_subscription.assert_has_calls([
        call(authorization_id, "a-client-id", adobe_one_time_subscription["subscriptionId"]),
        call(authorization_id, "a-client-id", adobe_subscription["subscriptionId"]),
        call(authorization_id, "a-client-id", adobe_inactive_subscription["subscriptionId"]),
    ])
    mocked_get_template.assert_has_calls([
        call(
            mock_mpt_client,
            order["agreement"]["product"]["id"],
            MPT_ORDER_STATUS_PROCESSING,
            TEMPLATE_NAME_TRANSFER,
        ),
        call(
            mock_mpt_client,
            order["agreement"]["product"]["id"],
            MPT_ORDER_STATUS_COMPLETED,
            TEMPLATE_NAME_TRANSFER,
        ),
    ])
    mocked_get_onetime.assert_called_with(
        mock_mpt_client,
        order["agreement"]["product"]["id"],
        [line["item"]["id"] for line in order["lines"]],
    )
    mocked_sync_agreement.assert_called_once_with(
        mock_mpt_client,
        mock_adobe_client,
        [order["agreement"]["id"]],
        dry_run=False,
        sync_prices=False,
    )
    mocked_get_gc_agreement_deployments_by_main_agreement()
    assert mocked_get_gc_main_agreement.call_count == 1
    assert mocked_get_gc_main_agreement.mock_calls[0].args == (
        "PRD-1111-1111",
        "AUT-1234-4567",
        "a-membership-id",
    )


@freeze_time("2024-01-01")
def test_transfer_gc_account_no_deployments(
    mocker,
    mock_adobe_client,
    mock_mpt_client,
    agreement,
    order_factory,
    transfer_order_parameters_factory,
    fulfillment_parameters_factory,
    adobe_preview_transfer_factory,
    adobe_transfer_factory,
    adobe_items_factory,
    adobe_subscription_factory,
    adobe_customer_factory,
    assets_factory,
    items_factory,
    lines_factory,
    subscriptions_factory,
):
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

    adobe_transfer_preview = adobe_preview_transfer_factory(
        items=[
            adobe_items_factory()[0],
            adobe_items_factory(offer_id="99999999CA01A12", subscription_id="one-time-sub-id")[0],
        ],
    )
    adobe_customer = adobe_customer_factory(global_sales_enabled=True)
    adobe_subscription = adobe_subscription_factory()
    adobe_inactive_subscription = adobe_subscription_factory(
        subscription_id="inactive-sub-id", status=AdobeStatus.INACTIVE_OR_GENERIC_FAILURE.value
    )
    adobe_one_time_subscription = adobe_subscription_factory(
        offer_id="99999999CA01A12", subscription_id="one-time-sub-id", autorenewal_enabled=False
    )
    mock_adobe_client.preview_transfer.return_value = adobe_transfer_preview
    mock_adobe_client.create_transfer.return_value = adobe_transfer
    mock_adobe_client.get_customer.return_value = adobe_customer
    mock_adobe_client.get_transfer.return_value = adobe_transfer
    mock_adobe_client.get_subscription.side_effect = [
        adobe_one_time_subscription,
        adobe_subscription,
        adobe_inactive_subscription,
        adobe_one_time_subscription,
    ]
    mock_adobe_client.get_customer_deployments_active_status.return_value = []
    mock_adobe_client.update_subscription.return_value = adobe_subscription
    mocker.patch(
        "adobe_vipm.flows.fulfillment.transfer.get_adobe_client", return_value=mock_adobe_client
    )

    order = order_factory(
        lines=[lines_factory()[0], lines_factory(external_vendor_id="99999999CA")[0]],
        order_parameters=transfer_order_parameters_factory(),
    )
    mocked_update_order = mocker.patch("adobe_vipm.flows.fulfillment.shared.update_order")
    mocked_update_agreement = mocker.patch("adobe_vipm.flows.fulfillment.shared.update_agreement")
    asset = assets_factory(adobe_sku="99999999CA01A12")[0]
    mocked_add_asset = mocker.patch(
        "adobe_vipm.flows.fulfillment.transfer.add_asset", return_value=asset
    )
    subscription = subscriptions_factory(commitment_date="2024-01-01")[0]
    mocked_create_subscription = mocker.patch(
        "adobe_vipm.flows.fulfillment.shared.create_subscription", return_value=subscription
    )
    mocked_get_onetime = mocker.patch(
        "adobe_vipm.flows.utils.order.get_product_onetime_items_by_ids",
        return_value=items_factory(item_id=2, external_vendor_id="99999999CA"),
    )
    mocked_process_order = mocker.patch(
        "adobe_vipm.flows.fulfillment.shared.set_processing_template"
    )
    mocked_complete_order = mocker.patch("adobe_vipm.flows.fulfillment.shared.complete_order")
    mocked_sync_agreement = mocker.patch(
        "adobe_vipm.flows.fulfillment.transfer.sync_agreements_by_agreement_ids"
    )

    fulfill_order(mock_mpt_client, order)

    authorization_id = order["authorization"]["id"]
    adobe_customer_address = adobe_customer["companyProfile"]["address"]
    adobe_customer_contact = adobe_customer["companyProfile"]["contacts"][0]
    mock_adobe_client.preview_transfer.assert_called_once_with(authorization_id, "a-membership-id")

    assert mocked_update_order.mock_calls[0].args == (mock_mpt_client, order["id"])
    assert mocked_update_order.mock_calls[0].kwargs == {
        "parameters": {
            "fulfillment": fulfillment_parameters_factory(
                due_date="2024-01-31",
            ),
            "ordering": order["parameters"]["ordering"],
        },
    }
    assert mocked_update_order.mock_calls[1].args == (mock_mpt_client, order["id"])
    assert mocked_update_order.mock_calls[1].kwargs == {
        "externalIds": {"vendor": adobe_transfer["transferId"]},
    }
    assert mocked_update_order.mock_calls[2].args == (mock_mpt_client, order["id"])
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
    assert mocked_update_order.mock_calls[3].args == (mock_mpt_client, order["id"])
    order_result = {
        "parameters": {
            "fulfillment": fulfillment_parameters_factory(
                customer_id="a-client-id",
                coterm_date="",
                global_customer="Yes",
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
    order_result = reset_order_error(reset_ordering_parameters_error(order_result))

    assert mocked_update_order.mock_calls[3].kwargs.get("parameters") == order_result.get(
        "parameters"
    )

    mocked_update_agreement.assert_has_calls([
        mocker.call(
            mock_mpt_client,
            order["agreement"]["id"],
            externalIds={"vendor": "a-client-id"},
        ),
        mocker.call(
            mock_mpt_client,
            order["agreement"]["id"],
            externalIds={"vendor": "a-client-id"},
        ),
    ])
    mocked_add_asset.assert_called_once_with(
        mock_mpt_client, adobe_one_time_subscription, mocker.ANY, adobe_transfer["lineItems"][2]
    )
    mocked_create_subscription.assert_called_once_with(
        mock_mpt_client,
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
                        "externalId": Param.CURRENT_QUANTITY.value,
                        "value": str(adobe_subscription[Param.CURRENT_QUANTITY.value]),
                    },
                    {
                        "externalId": Param.RENEWAL_QUANTITY.value,
                        "value": str(
                            adobe_subscription["autoRenewal"][Param.RENEWAL_QUANTITY.value]
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
    mocked_process_order.assert_called_once_with(mock_mpt_client, order["id"], {"id": "TPL-0000"})
    mocked_complete_order.assert_called_once_with(
        mock_mpt_client,
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
    mock_adobe_client.get_transfer.assert_called_once_with(
        authorization_id, "a-membership-id", adobe_transfer["transferId"]
    )
    mock_adobe_client.get_subscription.assert_has_calls([
        call(authorization_id, "a-client-id", adobe_one_time_subscription["subscriptionId"]),
        call(authorization_id, "a-client-id", adobe_subscription["subscriptionId"]),
        call(authorization_id, "a-client-id", adobe_inactive_subscription["subscriptionId"]),
    ])
    mocked_get_template.assert_has_calls([
        call(
            mock_mpt_client,
            order["agreement"]["product"]["id"],
            MPT_ORDER_STATUS_PROCESSING,
            TEMPLATE_NAME_TRANSFER,
        ),
        call(
            mock_mpt_client,
            order["agreement"]["product"]["id"],
            MPT_ORDER_STATUS_COMPLETED,
            TEMPLATE_NAME_TRANSFER,
        ),
    ])
    mocked_get_onetime.assert_called_with(
        mock_mpt_client,
        order["agreement"]["product"]["id"],
        [line["item"]["id"] for line in order["lines"]],
    )
    mocked_sync_agreement.assert_called_once_with(
        mock_mpt_client,
        mock_adobe_client,
        [order["agreement"]["id"]],
        dry_run=False,
        sync_prices=False,
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
    mock_adobe_client,
    mock_mpt_client,
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
    mocker.patch("adobe_vipm.flows.fulfillment.transfer.send_warning", return_value=None)
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
    mock_adobe_client.preview_transfer.return_value = adobe_transfer_preview
    mock_adobe_client.create_transfer.return_value = adobe_transfer
    mock_adobe_client.get_customer.return_value = adobe_customer
    mock_adobe_client.get_transfer.return_value = adobe_transfer
    mock_adobe_client.get_subscription.side_effect = [
        adobe_subscription,
        adobe_inactive_subscription,
        adobe_one_time_subscription,
    ]
    mock_adobe_client.get_customer_deployments_active_status.return_value = [
        {
            "deploymentId": "deployment-id",
            "status": "1000",
            "companyProfile": {"address": {"country": "DE"}},
        }
    ]
    mock_adobe_client.update_subscription.return_value = adobe_subscription
    mocker.patch(
        "adobe_vipm.flows.fulfillment.transfer.get_adobe_client", return_value=mock_adobe_client
    )
    order = order_factory(order_parameters=transfer_order_parameters_factory())
    mocked_update_order = mocker.patch("adobe_vipm.flows.fulfillment.shared.update_order")

    fulfill_order(mock_mpt_client, order)

    authorization_id = order["authorization"]["id"]
    mock_adobe_client.preview_transfer.assert_called_once_with(authorization_id, "a-membership-id")
    assert mocked_update_order.mock_calls[1].kwargs == {
        "externalIds": {"vendor": adobe_transfer["transferId"]}
    }
    mock_adobe_client.get_transfer.assert_called_once_with(
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
    mock_adobe_client,
    mock_mpt_client,
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
        "adobe_vipm.flows.fulfillment.transfer.get_transfer_by_authorization_membership_or_customer",
        return_value=None,
    )
    mocker.patch("adobe_vipm.flows.helpers.get_agreement", return_value=agreement)
    mocked_gc_main_agreement = mocker.MagicMock(main_agreement_id="", status=STATUS_GC_PENDING)
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
    mocker.patch("adobe_vipm.flows.fulfillment.transfer.send_warning", return_value=None)
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
    mock_adobe_client.preview_transfer.return_value = adobe_transfer_preview
    mock_adobe_client.create_transfer.return_value = adobe_transfer
    mock_adobe_client.get_customer.return_value = adobe_customer
    mock_adobe_client.get_transfer.return_value = adobe_transfer
    mock_adobe_client.get_subscription.side_effect = [
        adobe_subscription,
        adobe_inactive_subscription,
        adobe_one_time_subscription,
    ]
    mock_adobe_client.get_customer_deployments_active_status.return_value = [
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
    mock_adobe_client.update_subscription.return_value = adobe_subscription
    order = order_factory(order_parameters=transfer_order_parameters_factory())
    mocked_update_order = mocker.patch("adobe_vipm.flows.fulfillment.shared.update_order")

    fulfill_order(mock_mpt_client, order)

    authorization_id = order["authorization"]["id"]
    mock_adobe_client.preview_transfer.assert_called_once_with(authorization_id, "a-membership-id")
    assert mocked_update_order.mock_calls[1].kwargs == {
        "externalIds": {
            "vendor": adobe_transfer["transferId"],
        }
    }
    mock_adobe_client.get_transfer.assert_called_once_with(
        authorization_id, "a-membership-id", adobe_transfer["transferId"]
    )
    mocked_get_gc_main_agreement.assert_called_once_with("PRD-1111-1111", "AGR-2119-4550-8674-5962")
    mocked_get_agreement_deployment_view_link.assert_called_once_with("PRD-1111-1111")
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
    mock_adobe_client,
    mock_mpt_client,
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
    mock_adobe_client.preview_transfer.return_value = adobe_transfer_preview
    mock_adobe_client.get_customer.return_value = adobe_customer
    mock_adobe_client.get_transfer.return_value = adobe_transfer
    mock_adobe_client.get_customer_deployments_active_status.return_value = [
        {
            "deploymentId": "deployment-id",
            "status": "1000",
            "companyProfile": {"address": {"country": "DE"}},
        }
    ]
    mock_adobe_client.update_subscription.return_value = adobe_subscription
    order = order_factory(order_parameters=transfer_order_parameters_factory())

    fulfill_order(mock_mpt_client, order)

    assert order["status"] == MPT_ORDER_STATUS_PROCESSING


def test_transfer_gc_account_main_agreement_error_status(
    mocker,
    mock_adobe_client,
    mock_mpt_client,
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
    mock_adobe_client.preview_transfer.return_value = adobe_transfer_preview
    mock_adobe_client.get_customer.return_value = adobe_customer
    mock_adobe_client.get_transfer.return_value = adobe_transfer
    mock_adobe_client.get_customer_deployments_active_status.return_value = [
        {
            "deploymentId": "deployment-id",
            "status": "1000",
            "companyProfile": {"address": {"country": "DE"}},
        }
    ]
    mock_adobe_client.update_subscription.return_value = adobe_subscription
    order = order_factory(order_parameters=transfer_order_parameters_factory())

    fulfill_order(mock_mpt_client, order)

    assert order["status"] == MPT_ORDER_STATUS_PROCESSING


@freeze_time("2024-01-01")
def test_transfer_gc_account_no_items_error_main_agreement(
    mocker,
    mock_adobe_client,
    mock_mpt_client,
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

    mock_adobe_client.preview_transfer.return_value = adobe_transfer_preview
    mock_adobe_client.create_transfer.return_value = adobe_transfer
    mock_adobe_client.get_customer.return_value = adobe_customer
    mock_adobe_client.get_transfer.return_value = adobe_transfer
    mock_adobe_client.get_subscription.side_effect = [
        adobe_subscription,
    ]
    mock_adobe_client.get_customer_deployments_active_status.return_value = [
        {
            "deploymentId": "deployment-id",
            "status": "1000",
            "companyProfile": {"address": {"country": "DE"}},
        }
    ]
    mock_adobe_client.update_subscription.return_value = adobe_subscription
    order = order_factory(
        order_parameters=transfer_order_parameters_factory(),
    )
    mocked_update_order = mocker.patch("adobe_vipm.flows.fulfillment.shared.update_order")
    mocked_update_agreement = mocker.patch("adobe_vipm.flows.fulfillment.shared.update_agreement")
    mocker.patch(
        "adobe_vipm.flows.utils.order.get_product_onetime_items_by_ids",
        return_value=items_factory(item_id=2, external_vendor_id="99999999CA"),
    )
    mocked_process_order = mocker.patch(
        "adobe_vipm.flows.fulfillment.shared.set_processing_template",
    )

    fulfill_order(mock_mpt_client, order)

    authorization_id = order["authorization"]["id"]
    adobe_customer_address = adobe_customer["companyProfile"]["address"]
    adobe_customer_contact = adobe_customer["companyProfile"]["contacts"][0]
    mock_adobe_client.preview_transfer.assert_called_once_with(authorization_id, "a-membership-id")
    assert mocked_update_order.mock_calls[0].args == (mock_mpt_client, order["id"])
    assert mocked_update_order.mock_calls[0].kwargs == {
        "parameters": {
            "fulfillment": fulfillment_parameters_factory(
                due_date="2024-01-31",
            ),
            "ordering": order["parameters"]["ordering"],
        },
    }
    assert mocked_update_order.mock_calls[1].args == (mock_mpt_client, order["id"])
    assert mocked_update_order.mock_calls[1].kwargs == {
        "externalIds": {
            "vendor": adobe_transfer["transferId"],
        },
    }
    assert mocked_update_order.mock_calls[2].args == (mock_mpt_client, order["id"])
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

    mocked_update_agreement.assert_has_calls([
        mocker.call(
            mock_mpt_client,
            order["agreement"]["id"],
            externalIds={"vendor": "a-client-id"},
        ),
        mocker.call(
            mock_mpt_client,
            order["agreement"]["id"],
            externalIds={"vendor": "a-client-id"},
        ),
    ])
    mocked_process_order.assert_called_once_with(
        mock_mpt_client,
        order["id"],
        {"id": "TPL-0000"},
    )
    mocked_process_order.assert_called_once_with(mock_mpt_client, order["id"], {"id": "TPL-0000"})
    mock_adobe_client.get_transfer.assert_called_once_with(
        authorization_id, "a-membership-id", adobe_transfer["transferId"]
    )
    mocked_get_gc_main_agreement.assert_called_once_with(
        "PRD-1111-1111", "AUT-1234-4567", "a-membership-id"
    )
    assert order["status"] == MPT_ORDER_STATUS_PROCESSING


@freeze_time("2024-01-01")
def test_transfer_gc_account_some_deployments_not_created(
    mocker,
    mock_adobe_client,
    mock_mpt_client,
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
        "adobe_vipm.flows.fulfillment.transfer.get_transfer_by_authorization_membership_or_customer",
        return_value=None,
    )
    mocker.patch("adobe_vipm.flows.helpers.get_agreement", return_value=agreement)
    mocked_gc_main_agreement = mocker.MagicMock(
        main_agreement_id="main-agreement-id", status=STATUS_GC_PENDING
    )
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
    mocker.patch("adobe_vipm.flows.fulfillment.transfer.send_warning", return_value=None)
    adobe_transfer = adobe_transfer_factory(
        status=AdobeStatus.PROCESSED.value,
        customer_id="a-client-id",
        items=adobe_items_factory(
            subscription_id="a-sub-id",
            deployment_id="deployment-id",
            currency_code="EUR",
            offer_id="653045798CA01A12",
            deployment_currency_code="EUR",
        )
        + adobe_items_factory(line_number=2, subscription_id="inactive-sub-id")
        + adobe_items_factory(
            line_number=3,
            offer_id="99999999CA01A12",
            subscription_id="one-time-sub-id",
            deployment_id="deployment-id-2",
            currency_code="EUR",
            deployment_currency_code="EUR",
        )
        + adobe_items_factory(
            line_number=4,
            subscription_id="a-sub-id2",
            deployment_id="deployment-id",
            currency_code="USD",
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
    adobe_one_time_subscription = adobe_subscription_factory(subscription_id="one-time-sub-id")
    mock_adobe_client.preview_transfer.return_value = adobe_transfer_preview
    mock_adobe_client.create_transfer.return_value = adobe_transfer
    mock_adobe_client.get_customer.return_value = adobe_customer
    mock_adobe_client.get_transfer.return_value = adobe_transfer
    mock_adobe_client.get_subscription.side_effect = [
        adobe_subscription,
        adobe_inactive_subscription,
        adobe_one_time_subscription,
    ]
    mock_adobe_client.get_customer_deployments_active_status.return_value = [
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
    mock_adobe_client.update_subscription.return_value = adobe_subscription
    mocker.patch(
        "adobe_vipm.flows.fulfillment.transfer.get_adobe_client", return_value=mock_adobe_client
    )
    order = order_factory(
        order_parameters=transfer_order_parameters_factory(),
    )
    mocked_update_order = mocker.patch("adobe_vipm.flows.fulfillment.shared.update_order")

    fulfill_order(mock_mpt_client, order)

    authorization_id = order["authorization"]["id"]
    mock_adobe_client.preview_transfer.assert_called_once_with(authorization_id, "a-membership-id")
    assert mocked_update_order.mock_calls[1].kwargs == {
        "externalIds": {
            "vendor": adobe_transfer["transferId"],
        }
    }
    mock_adobe_client.get_transfer.assert_called_once_with(
        authorization_id, "a-membership-id", adobe_transfer["transferId"]
    )
    mocked_get_gc_main_agreement.assert_called_once_with("PRD-1111-1111", "AGR-2119-4550-8674-5962")
    mocked_get_agreement_deployment_view_link.assert_called_once_with("PRD-1111-1111")
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
    mock_adobe_client,
    mock_mpt_client,
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
    mocked_transfer = mocker.MagicMock(
        customer_id="customer-id",
        transfer_id="transfer-id",
        customer_benefits_3yc_status=ThreeYearCommitmentStatus.EXPIRED.value,
    )
    mocked_get_transfer = mocker.patch(
        "adobe_vipm.flows.fulfillment.transfer.get_transfer_by_authorization_membership_or_customer",
        return_value=mocked_transfer,
    )
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
    mocker.patch("adobe_vipm.flows.utils.order.get_product_onetime_items_by_ids", return_value=[])
    mocker.patch(
        "adobe_vipm.flows.fulfillment.transfer.add_subscription",
        return_value=subscriptions_factory(commitment_date="2024-08-04")[0],
    )
    mocked_process_order = mocker.patch(
        "adobe_vipm.flows.fulfillment.shared.set_processing_template",
    )
    mocker.patch("adobe_vipm.flows.fulfillment.shared.update_order")
    mocker.patch("adobe_vipm.flows.fulfillment.shared.complete_order")
    transfer_items = adobe_items_factory(subscription_id="sub-id")
    adobe_transfer = adobe_transfer_factory(status=AdobeStatus.PENDING.value, items=transfer_items)
    adobe_subscription = adobe_subscription_factory(
        status=AdobeStatus.PENDING.value, current_quantity=170
    )
    mock_adobe_client.get_transfer.return_value = adobe_transfer
    mock_adobe_client.get_customer.return_value = adobe_customer
    mock_adobe_client.get_subscription.return_value = adobe_subscription
    mock_adobe_client.get_subscriptions.return_value = {
        "items": [adobe_subscription],
    }
    mock_adobe_client.get_customer_deployments_active_status.return_value = [
        {
            "deploymentId": "deployment-id",
            "status": "1000",
            "companyProfile": {"address": {"country": "DE"}},
        }
    ]
    mocker.patch(
        "adobe_vipm.flows.fulfillment.transfer.get_adobe_client",
        return_value=mock_adobe_client,
    )

    fulfill_order(mock_mpt_client, order)

    membership_id_param = get_ordering_parameter(updated_order, Param.MEMBERSHIP_ID.value)
    mocked_get_transfer.assert_called_once_with(
        order["agreement"]["product"]["id"],
        adobe_authorizations_file["authorizations"][0]["authorization_id"],
        membership_id_param["value"],
    )
    mocked_process_order.assert_called_once_with(mock_mpt_client, order["id"], {"id": "TPL-0000"})
    mocked_get_agreement_deployment_view_link.assert_called_once_with("PRD-1111-1111")
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
    mock_adobe_client.update_subscription.assert_not_called()


@freeze_time("2012-01-14 12:00:01")
def test_fulfill_transfer_gc_order_already_migrated_no_items_without_deployment(
    mocker,
    mock_adobe_client,
    mock_mpt_client,
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
    mocked_gc_main_agreement = mocker.MagicMock(main_agreement_id="", status=STATUS_GC_PENDING)
    mocker.patch(
        "adobe_vipm.flows.fulfillment.transfer.get_gc_main_agreement",
        return_value=mocked_gc_main_agreement,
    )
    mocked_gc_agreement_deployments_by_main_agreement = mocker.MagicMock(
        status=STATUS_GC_CREATED, deployment_id="deployment-id"
    )
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
    mocker.patch("adobe_vipm.flows.fulfillment.transfer.send_warning", return_value=None)
    product_items = items_factory()
    mocker.patch(
        "adobe_vipm.flows.fulfillment.transfer.get_product_items_by_skus",
        return_value=product_items,
    )

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
    mocked_transfer = mocker.MagicMock(
        customer_id="customer-id",
        transfer_id="transfer-id",
        customer_benefits_3yc_status=ThreeYearCommitmentStatus.EXPIRED.value,
    )
    mocked_get_transfer = mocker.patch(
        "adobe_vipm.flows.fulfillment.transfer.get_transfer_by_authorization_membership_or_customer",
        return_value=mocked_transfer,
    )
    mocker.patch("adobe_vipm.flows.utils.order.get_product_onetime_items_by_ids", return_value=[])
    mocker.patch(
        "adobe_vipm.flows.fulfillment.transfer.add_subscription",
        return_value=subscriptions_factory(commitment_date="2024-08-04")[0],
    )
    mocker.patch("adobe_vipm.flows.fulfillment.shared.set_processing_template")
    mocker.patch("adobe_vipm.flows.fulfillment.shared.update_order")
    mocker.patch("adobe_vipm.flows.fulfillment.shared.complete_order")
    transfer_items = adobe_items_factory(subscription_id="sub-id", deployment_id="deployment-id")
    adobe_transfer = adobe_transfer_factory(status=AdobeStatus.PENDING.value, items=transfer_items)
    adobe_subscription = adobe_subscription_factory(
        status=AdobeStatus.PENDING.value, current_quantity=170, deployment_id="deployment-id"
    )
    mock_adobe_client.get_transfer.return_value = adobe_transfer
    mock_adobe_client.get_customer.return_value = adobe_customer
    mock_adobe_client.get_subscription.return_value = adobe_subscription
    mock_adobe_client.get_subscriptions.return_value = {
        "items": [adobe_subscription],
    }
    mock_adobe_client.get_customer_deployments_active_status.return_value = [
        {
            "deploymentId": "deployment-id",
            "status": "1000",
            "companyProfile": {"address": {"country": "DE"}},
        }
    ]
    mocker.patch(
        "adobe_vipm.flows.fulfillment.transfer.get_adobe_client", return_value=mock_adobe_client
    )

    fulfill_order(mock_mpt_client, order)

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
    mock_adobe_client.update_subscription.assert_not_called()


@freeze_time("2012-01-14 12:00:01")
def test_sync_gc_main_agreement_step(
    mocker,
    mock_adobe_client,
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

    step = SyncGCMainAgreement(mocked_transfer, mocked_gc_main_agreement)
    step(mocked_client, context, mocked_next_step)

    assert mocked_gc_main_agreement.status == STATUS_GC_TRANSFERRED
    mocked_next_step.assert_called_once_with(mocked_client, context)


@freeze_time("2024-01-01")
def test_transfer_gc_account_items_with_deployment_main_agreement(
    mocker,
    mock_adobe_client,
    mock_mpt_client,
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
    mock_adobe_client.preview_transfer.return_value = adobe_transfer_preview
    mock_adobe_client.create_transfer.return_value = adobe_transfer
    mock_adobe_client.get_customer.return_value = adobe_customer
    mock_adobe_client.get_transfer.return_value = adobe_transfer
    mock_adobe_client.get_subscription.side_effect = [adobe_subscription]
    mock_adobe_client.get_customer_deployments_active_status.return_value = [
        {
            "deploymentId": "deployment-id",
            "status": "1000",
            "companyProfile": {"address": {"country": "DE"}},
        }
    ]
    mock_adobe_client.update_subscription.return_value = adobe_subscription
    order = order_factory(order_parameters=transfer_order_parameters_factory())
    mocked_update_order = mocker.patch("adobe_vipm.flows.fulfillment.shared.update_order")
    mocker.patch(
        "adobe_vipm.flows.utils.order.get_product_onetime_items_by_ids",
        return_value=items_factory(item_id=2, external_vendor_id="99999999CA"),
    )

    fulfill_order(mock_mpt_client, order)

    authorization_id = order["authorization"]["id"]
    mock_adobe_client.preview_transfer.assert_called_once_with(authorization_id, "a-membership-id")
    assert mocked_update_order.mock_calls[0].args == (mock_mpt_client, order["id"])
    assert mocked_update_order.mock_calls[0].kwargs == {
        "parameters": {
            "fulfillment": fulfillment_parameters_factory(
                due_date="2024-01-31",
            ),
            "ordering": order["parameters"]["ordering"],
        },
    }
    assert mocked_update_order.mock_calls[1].args == (mock_mpt_client, order["id"])
    assert mocked_update_order.mock_calls[1].kwargs == {
        "externalIds": {
            "vendor": adobe_transfer["transferId"],
        },
    }
    mock_adobe_client.get_transfer.assert_called_once_with(
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
    mock_adobe_client,
    mock_mpt_client,
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
    mocked_gc_agreement_deployments_by_main_agreement = mocker.MagicMock(
        status=STATUS_GC_CREATED, deployment_id="deployment-id"
    )
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
    mock_adobe_client.preview_transfer.return_value = adobe_transfer_preview
    mock_adobe_client.create_transfer.return_value = adobe_transfer
    mock_adobe_client.get_customer.return_value = adobe_customer
    mock_adobe_client.get_transfer.return_value = adobe_transfer
    mock_adobe_client.get_subscription.side_effect = [adobe_subscription]
    mock_adobe_client.get_customer_deployments_active_status.return_value = [
        {
            "deploymentId": "deployment-id",
            "status": "1000",
            "companyProfile": {"address": {"country": "DE"}},
        }
    ]
    mocked_transfer = mocker.MagicMock(
        membership_id="membership-id",
        customer_id="customer-id",
        transfer_id="a-transfer-id",
        customer_benefits_3yc_status=None,
    )
    mocker.patch(
        "adobe_vipm.flows.fulfillment.transfer.get_transfer_by_authorization_membership_or_customer",
        return_value=mocked_transfer,
    )
    mock_adobe_client.update_subscription.return_value = adobe_subscription
    mocker.patch(
        "adobe_vipm.flows.fulfillment.transfer.get_adobe_client", return_value=mock_adobe_client
    )
    order = order_factory(order_parameters=transfer_order_parameters_factory())
    mocked_update_order = mocker.patch("adobe_vipm.flows.fulfillment.shared.update_order")
    mocker.patch(
        "adobe_vipm.flows.utils.order.get_product_onetime_items_by_ids",
        return_value=items_factory(item_id=2, external_vendor_id="99999999CA"),
    )

    fulfill_order(mock_mpt_client, order)

    authorization_id = order["authorization"]["id"]
    assert mocked_update_order.mock_calls[0].args == (mock_mpt_client, order["id"])
    assert mocked_update_order.mock_calls[0].kwargs == {
        "parameters": {
            "fulfillment": fulfillment_parameters_factory(
                due_date="2024-01-31",
            ),
            "ordering": order["parameters"]["ordering"],
        },
    }
    mock_adobe_client.get_transfer.assert_called_once_with(
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
    mock_adobe_client,
    mock_mpt_client,
    agreement,
    order_factory,
    transfer_order_parameters_factory,
    fulfillment_parameters_factory,
    adobe_transfer_factory,
):
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
    mock_adobe_client.create_transfer.return_value = adobe_transfer
    mock_adobe_client.get_transfer.return_value = adobe_transfer
    mocked_update_order = mocker.patch("adobe_vipm.flows.fulfillment.shared.update_order")
    mocked_complete_order = mocker.patch("adobe_vipm.flows.fulfillment.shared.complete_order")
    order = order_factory(
        order_parameters=transfer_order_parameters_factory(),
        external_ids={"vendor": "a-transfer-id"},
    )

    fulfill_order(mock_mpt_client, order)

    authorization_id = order["authorization"]["id"]
    assert mocked_update_order.mock_calls[0].args == (mock_mpt_client, order["id"])
    assert mocked_update_order.mock_calls[0].kwargs == {
        "parameters": {
            "fulfillment": fulfillment_parameters_factory(
                due_date="2025-01-31",
            ),
            "ordering": transfer_order_parameters_factory(),
        },
    }
    mocked_complete_order.assert_not_called()
    mock_adobe_client.get_transfer.assert_called_once_with(
        authorization_id, "a-membership-id", adobe_transfer["transferId"]
    )
    mocked_get_gc_agreement_deployments_by_main_agreement.assert_not_called()
    mocked_get_gc_main_agreement.assert_not_called()


@freeze_time("2024-01-01")
def test_transfer_gc_account_no_deployments_gc_parameters_updated(
    mocker,
    mock_adobe_client,
    mock_mpt_client,
    agreement,
    order_factory,
    transfer_order_parameters_factory,
    fulfillment_parameters_factory,
    adobe_preview_transfer_factory,
    adobe_transfer_factory,
    adobe_items_factory,
    adobe_subscription_factory,
    adobe_customer_factory,
    assets_factory,
    items_factory,
    lines_factory,
    subscriptions_factory,
):
    mocked_get_template = mocker.patch(
        "adobe_vipm.flows.fulfillment.shared.get_product_template_or_default",
        side_effect=[{"id": "TPL-0000"}, {"id": "TPL-1111"}],
    )
    mocker.patch(
        "adobe_vipm.flows.fulfillment.transfer.get_transfer_by_authorization_membership_or_customer",
        return_value=None,
    )
    mocker.patch("adobe_vipm.flows.helpers.get_agreement", return_value=agreement)

    mocked_gc_main_agreement = mocker.MagicMock(
        main_agreement_id="main-agreement-id", status=STATUS_GC_PENDING
    )
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
    adobe_transfer_preview = adobe_preview_transfer_factory(
        items=[
            adobe_items_factory()[0],
            adobe_items_factory(offer_id="99999999CA01A12", subscription_id="one-time-sub-id")[0],
        ],
    )
    adobe_customer = adobe_customer_factory(global_sales_enabled=True)
    adobe_subscription = adobe_subscription_factory()
    adobe_inactive_subscription = adobe_subscription_factory(
        subscription_id="inactive-sub-id", status=AdobeStatus.INACTIVE_OR_GENERIC_FAILURE.value
    )
    adobe_one_time_subscription = adobe_subscription_factory(
        offer_id="99999999CA01A12", subscription_id="one-time-sub-id", autorenewal_enabled=False
    )
    mock_adobe_client.preview_transfer.return_value = adobe_transfer_preview
    mock_adobe_client.create_transfer.return_value = adobe_transfer
    mock_adobe_client.get_customer.return_value = adobe_customer
    mock_adobe_client.get_transfer.return_value = adobe_transfer
    mock_adobe_client.get_subscription.side_effect = [
        adobe_one_time_subscription,
        adobe_subscription,
        adobe_inactive_subscription,
        adobe_one_time_subscription,
    ]
    mock_adobe_client.get_customer_deployments_active_status.return_value = []
    mock_adobe_client.update_subscription.return_value = adobe_subscription
    mocker.patch(
        "adobe_vipm.flows.fulfillment.transfer.get_adobe_client", return_value=mock_adobe_client
    )
    order = order_factory(
        lines=[lines_factory()[0], lines_factory(external_vendor_id="99999999CA")[0]],
        order_parameters=transfer_order_parameters_factory(),
        fulfillment_parameters=fulfillment_parameters_factory(
            global_customer="Yes", deployments=""
        ),
    )
    mocked_update_order = mocker.patch("adobe_vipm.flows.fulfillment.shared.update_order")
    mocked_update_agreement = mocker.patch("adobe_vipm.flows.fulfillment.shared.update_agreement")
    asset = assets_factory(adobe_sku="99999999CA01A12")[0]
    mocked_add_asset = mocker.patch(
        "adobe_vipm.flows.fulfillment.transfer.add_asset", return_value=asset
    )
    subscription = subscriptions_factory(commitment_date="2024-01-01")[0]
    mocked_create_subscription = mocker.patch(
        "adobe_vipm.flows.fulfillment.shared.create_subscription", return_value=subscription
    )
    mocked_get_onetime = mocker.patch(
        "adobe_vipm.flows.utils.order.get_product_onetime_items_by_ids",
        return_value=items_factory(item_id=2, external_vendor_id="99999999CA"),
    )
    mocked_process_order = mocker.patch(
        "adobe_vipm.flows.fulfillment.shared.set_processing_template"
    )

    mocked_complete_order = mocker.patch("adobe_vipm.flows.fulfillment.shared.complete_order")
    mocked_sync_agreement = mocker.patch(
        "adobe_vipm.flows.fulfillment.transfer.sync_agreements_by_agreement_ids"
    )

    fulfill_order(mock_mpt_client, order)

    authorization_id = order["authorization"]["id"]
    adobe_customer_address = adobe_customer["companyProfile"]["address"]
    adobe_customer_contact = adobe_customer["companyProfile"]["contacts"][0]
    mock_adobe_client.preview_transfer.assert_called_once_with(authorization_id, "a-membership-id")
    assert mocked_update_order.mock_calls[0].args == (mock_mpt_client, order["id"])
    assert mocked_update_order.mock_calls[0].kwargs == {
        "parameters": {
            "fulfillment": fulfillment_parameters_factory(
                due_date="2024-01-31",
                global_customer="Yes",
            ),
            "ordering": order["parameters"]["ordering"],
        },
    }
    assert mocked_update_order.mock_calls[1].args == (mock_mpt_client, order["id"])
    assert mocked_update_order.mock_calls[1].kwargs == {
        "externalIds": {
            "vendor": adobe_transfer["transferId"],
        },
    }
    assert mocked_update_order.mock_calls[2].args == (mock_mpt_client, order["id"])
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
    assert mocked_update_order.mock_calls[3].args == (mock_mpt_client, order["id"])
    assert mocked_update_order.mock_calls[3].kwargs == {
        "parameters": {
            "fulfillment": fulfillment_parameters_factory(
                customer_id="a-client-id",
                coterm_date="",
                global_customer="Yes",
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
        "externalIds": {
            "vendor": adobe_transfer["transferId"],
        },
    }

    assert mocked_update_order.mock_calls[4].args == (
        mock_mpt_client,
        order["id"],
    )
    assert mocked_update_order.mock_calls[4].kwargs == {
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
    mocked_update_agreement.assert_has_calls([
        mocker.call(
            mock_mpt_client,
            order["agreement"]["id"],
            externalIds={"vendor": "a-client-id"},
        ),
        mocker.call(
            mock_mpt_client,
            order["agreement"]["id"],
            externalIds={"vendor": "a-client-id"},
        ),
    ])
    mocked_add_asset.assert_called_once_with(
        mock_mpt_client, adobe_one_time_subscription, mocker.ANY, adobe_transfer["lineItems"][2]
    )
    mocked_create_subscription.assert_called_once_with(
        mock_mpt_client,
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
                        "externalId": Param.CURRENT_QUANTITY.value,
                        "value": str(adobe_subscription[Param.CURRENT_QUANTITY.value]),
                    },
                    {
                        "externalId": Param.RENEWAL_QUANTITY.value,
                        "value": str(
                            adobe_subscription["autoRenewal"][Param.RENEWAL_QUANTITY.value]
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
    mocked_process_order.assert_called_once_with(mock_mpt_client, order["id"], {"id": "TPL-0000"})
    mocked_complete_order.assert_called_once_with(
        mock_mpt_client,
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
    mock_adobe_client.get_transfer.assert_called_once_with(
        authorization_id, "a-membership-id", adobe_transfer["transferId"]
    )
    mock_adobe_client.get_subscription.assert_has_calls([
        call(authorization_id, "a-client-id", adobe_one_time_subscription["subscriptionId"]),
        call(authorization_id, "a-client-id", adobe_subscription["subscriptionId"]),
        call(authorization_id, "a-client-id", adobe_inactive_subscription["subscriptionId"]),
    ])
    mocked_get_template.assert_has_calls([
        call(
            mock_mpt_client,
            order["agreement"]["product"]["id"],
            MPT_ORDER_STATUS_PROCESSING,
            TEMPLATE_NAME_TRANSFER,
        ),
        call(
            mock_mpt_client,
            order["agreement"]["product"]["id"],
            MPT_ORDER_STATUS_COMPLETED,
            TEMPLATE_NAME_TRANSFER,
        ),
    ])
    mocked_get_onetime.assert_called_with(
        mock_mpt_client,
        order["agreement"]["product"]["id"],
        [line["item"]["id"] for line in order["lines"]],
    )
    mocked_sync_agreement.assert_called_once_with(
        mock_mpt_client,
        mock_adobe_client,
        [order["agreement"]["id"]],
        dry_run=False,
        sync_prices=False,
    )
    mocked_get_gc_main_agreement.assert_has_calls([
        call("PRD-1111-1111", "AUT-1234-4567", "a-membership-id")
    ])
    mocked_get_gc_agreement_deployments_by_main_agreement.assert_called_once_with(
        "PRD-1111-1111", "AGR-2119-4550-8674-5962"
    )


@freeze_time("2024-01-01")
def test_transfer_gc_account_items_with_and_without_deployment_main_agreement_bulk_migrated(
    mocker,
    mock_adobe_client,
    mock_mpt_client,
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
    product_items = items_factory()
    mocker.patch(
        "adobe_vipm.flows.fulfillment.transfer.get_product_items_by_skus",
        return_value=product_items,
    )
    mocker.patch("adobe_vipm.flows.helpers.get_agreement", return_value=agreement)
    mocked_gc_main_agreement = mocker.MagicMock(
        main_agreement_id="main-agreement-id", status=STATUS_GC_PENDING
    )
    mocked_get_gc_main_agreement = mocker.patch(
        "adobe_vipm.flows.fulfillment.transfer.get_gc_main_agreement",
        return_value=mocked_gc_main_agreement,
    )
    mocked_gc_agreement_deployments_by_main_agreement = mocker.MagicMock(
        status=STATUS_GC_CREATED, deployment_id="deployment-id"
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
    mock_adobe_client.preview_transfer.return_value = adobe_transfer_preview
    mock_adobe_client.create_transfer.return_value = adobe_transfer
    mock_adobe_client.get_customer.return_value = adobe_customer
    mock_adobe_client.get_transfer.return_value = adobe_transfer
    mock_adobe_client.get_subscriptions.return_value = {
        "items": [adobe_subscription, adobe_subscription1],
    }
    mock_adobe_client.get_subscription.return_value = adobe_subscription
    mock_adobe_client.get_customer_deployments_active_status.return_value = [
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
    mocked_transfer = mocker.MagicMock(
        membership_id="membership-id",
        customer_id="customer-id",
        transfer_id="a-transfer-id",
        customer_benefits_3yc_status=None,
    )
    mocker.patch(
        "adobe_vipm.flows.fulfillment.transfer.get_transfer_by_authorization_membership_or_customer",
        return_value=mocked_transfer,
    )
    mock_adobe_client.update_subscription.return_value = adobe_subscription
    mocker.patch(
        "adobe_vipm.flows.fulfillment.transfer.get_adobe_client", return_value=mock_adobe_client
    )
    order = order_factory(order_parameters=transfer_order_parameters_factory())
    mocked_update_order = mocker.patch("adobe_vipm.flows.fulfillment.shared.update_order")
    mocker.patch(
        "adobe_vipm.flows.utils.order.get_product_onetime_items_by_ids",
        return_value=items_factory(item_id=2, external_vendor_id="99999999CA"),
    )

    fulfill_order(mock_mpt_client, order)

    authorization_id = order["authorization"]["id"]
    assert mocked_update_order.mock_calls[0].args == (mock_mpt_client, order["id"])
    assert mocked_update_order.mock_calls[0].kwargs == {
        "parameters": {
            "fulfillment": fulfillment_parameters_factory(
                due_date="2024-01-31",
            ),
            "ordering": order["parameters"]["ordering"],
        },
    }
    mock_adobe_client.get_transfer.assert_called_once_with(
        authorization_id, "membership-id", adobe_transfer["transferId"]
    )
    mocked_get_gc_main_agreement.assert_called_once_with(
        "PRD-1111-1111", "AUT-1234-4567", "a-membership-id"
    )
    assert order["status"] == MPT_ORDER_STATUS_PROCESSING


@freeze_time("2012-01-14 12:00:01")
def test_fulfill_transfer_migrated_order_all_items_expired_add_new_item(
    mocker,
    mock_adobe_client,
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
    mocker.patch("adobe_vipm.flows.fulfillment.transfer.get_gc_main_agreement", return_value=None)
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
        "adobe_vipm.flows.fulfillment.shared.set_processing_template"
    )

    mocked_update_order = mocker.patch("adobe_vipm.flows.fulfillment.shared.update_order")
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

    mock_adobe_client.get_transfer.return_value = adobe_transfer
    mock_adobe_client.get_customer.return_value = adobe_customer
    mock_adobe_client.get_subscriptions.return_value = {
        "items": [
            adobe_subscription,
            adobe_inactive_subscription,
            adobe_one_time_subscription,
        ]
    }
    mock_adobe_client.get_subscription.return_value = adobe_subscription

    adobe_preview_order = adobe_order_factory(ORDER_TYPE_PREVIEW)
    mock_adobe_client.create_preview_order.return_value = adobe_preview_order
    mock_adobe_client.create_new_order.return_value = new_order

    mocker.patch(
        "adobe_vipm.flows.fulfillment.transfer.get_adobe_client", return_value=mock_adobe_client
    )
    mocker.patch("adobe_vipm.flows.helpers.get_adobe_client", return_value=mock_adobe_client)
    mocker.patch(
        "adobe_vipm.flows.fulfillment.shared.get_adobe_client", return_value=mock_adobe_client
    )

    fulfill_order(mock_mpt_client, order)

    membership_id_param = get_ordering_parameter(updated_order, Param.MEMBERSHIP_ID.value)

    mocked_get_transfer.assert_called_once_with(
        order["agreement"]["product"]["id"],
        adobe_authorizations_file["authorizations"][0]["authorization_id"],
        membership_id_param["value"],
    )

    mocked_process_order.assert_called_once_with(mock_mpt_client, order["id"], {"id": "TPL-0000"})

    assert mocked_update_order.mock_calls[0].args == (mock_mpt_client, order["id"])
    assert mocked_update_order.mock_calls[0].kwargs == {"parameters": order["parameters"]}
    mock_sync_agreements_by_agreement_ids.assert_called_once_with(
        mock_mpt_client, mock_adobe_client, [agreement["id"]], dry_run=False, sync_prices=False
    )


@freeze_time("2012-01-14 12:00:01")
def test_fulfill_transfer_migrated_order_offer_id_expired(
    mocker,
    mock_adobe_client,
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

    mocked_transfer = mocker.MagicMock(
        membership_id="membership-id",
        customer_id="customer-id",
        transfer_id="transfer-id",
        customer_benefits_3yc_status=None,
    )

    adobe_customer = adobe_customer_factory()
    updated_order = order_factory(
        fulfillment_parameters=fulfillment_parameters_factory(
            due_date="2012-02-13",
        ),
        order_parameters=transfer_order_parameters_factory(
            company_name=None,
            address=None,
            contact=None,
        ),
        external_ids={"vendor": "transfer-id"},
    )

    product_items = items_factory()
    transfer_items = adobe_items_factory(subscription_id="inactive-sub-id", offer_id="65304999CA")
    adobe_subscription = adobe_subscription_factory(offer_id="65304578CA2", current_quantity=170)
    adobe_transfer = adobe_transfer_factory(items=transfer_items)
    new_order = adobe_order_factory(order_type=ORDER_TYPE_NEW, status=AdobeStatus.PENDING.value)
    adobe_preview_order = adobe_order_factory(ORDER_TYPE_PREVIEW)

    mocker.patch("adobe_vipm.flows.helpers.get_agreement", return_value=agreement)
    mocker.patch(
        "adobe_vipm.flows.fulfillment.transfer.add_subscription",
        return_value=subscriptions_factory(commitment_date="2024-08-04")[0],
    )
    mocker.patch(
        "adobe_vipm.flows.fulfillment.transfer.get_product_items_by_skus",
        return_value=product_items,
    )
    mocker.patch(
        "adobe_vipm.flows.fulfillment.transfer.get_transfer_by_authorization_membership_or_customer",
        return_value=mocked_transfer,
    )
    mocker.patch("adobe_vipm.flows.fulfillment.transfer.get_gc_main_agreement", return_value=None)
    mocker.patch(
        "adobe_vipm.flows.fulfillment.transfer.get_gc_agreement_deployments_by_main_agreement",
        return_value=None,
    )
    mocker.patch(
        "adobe_vipm.flows.utils.order.get_product_onetime_items_by_ids",
        return_value=items_factory(item_id=2, external_vendor_id="99999999CA"),
    )
    mocker.patch("adobe_vipm.flows.fulfillment.shared.set_processing_template")
    mocked_update_order = mocker.patch("adobe_vipm.flows.fulfillment.shared.update_order")
    mocker.patch(
        "adobe_vipm.flows.fulfillment.shared.get_product_template_or_default",
        side_effect=[{"id": "TPL-0000"}, {"id": "TPL-1111"}],
    )
    mock_sync_main_agreement = mocker.patch(
        "adobe_vipm.flows.fulfillment.transfer.sync_main_agreement"
    )

    mock_adobe_client.get_transfer.return_value = adobe_transfer
    mock_adobe_client.get_customer.return_value = adobe_customer
    mock_adobe_client.get_subscriptions.return_value = {"items": [adobe_subscription]}
    mock_adobe_client.get_subscription.return_value = adobe_subscription
    mock_adobe_client.create_preview_order.return_value = adobe_preview_order
    mock_adobe_client.create_new_order.return_value = new_order
    mock_adobe_client.update_subscription.side_effect = AdobeAPIError(
        400, {"error": "Error updating subscription"}
    )

    fulfill_order(mock_mpt_client, order)

    mocked_update_order.assert_has_calls([
        mocker.call(mock_mpt_client, order["id"], parameters=updated_order["parameters"])
    ])

    mock_sync_main_agreement.assert_called_once_with(
        None, "PRD-1111-1111", "AUT-1234-4567", "customer-id"
    )
