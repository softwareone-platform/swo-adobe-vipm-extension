from datetime import date, datetime

import pytest
from freezegun import freeze_time

from adobe_vipm.adobe.constants import AdobeStatus
from adobe_vipm.adobe.errors import (
    AdobeAPIError,
    AuthorizationNotFoundError,
    ResellerNotFoundError,
)
from adobe_vipm.airtable.models import (
    STATUS_GC_PENDING,
    STATUS_RUNNING,
)
from adobe_vipm.flows.errors import AirTableAPIError
from adobe_vipm.flows.migration import (
    check_running_transfers,
    check_running_transfers_for_product,
    get_transfer_link_button,
    process_transfers,
    start_transfers_for_product,
)
from adobe_vipm.notifications import Button, FactsSection


@pytest.fixture()
def mock_transfer(mocker):
    return mocker.MagicMock(
        authorization_uk="auth-uk",
        membership_id="membership-id",
        record_id="record-id",
        seller_uk="seller-uk",
    )


def test_start_transfers_for_product(
    mocker,
    adobe_preview_transfer_factory,
    adobe_transfer_factory,
    adobe_items_factory,
    mock_transfer,
):
    mocked_get_transfer_to_process = mocker.patch(
        "adobe_vipm.flows.migration.get_transfers_to_process",
        return_value=[mock_transfer],
    )

    mocked_get_offer_ids_by_membership_id = mocker.patch(
        "adobe_vipm.flows.migration.get_offer_ids_by_membership_id",
        return_value=[],
    )
    mocked_create_offers = mocker.patch(
        "adobe_vipm.flows.migration.create_offers",
    )

    adobe_preview_transfer = adobe_preview_transfer_factory(
        items=adobe_items_factory(renewal_date="2022-10-11"),
    )
    adobe_transfer = adobe_transfer_factory()

    mocked_adobe_client = mocker.MagicMock()
    mocked_adobe_client.preview_transfer.return_value = adobe_preview_transfer
    mocked_adobe_client.create_transfer.return_value = adobe_transfer
    mocker.patch(
        "adobe_vipm.flows.migration.get_adobe_client",
        return_value=mocked_adobe_client,
    )

    start_transfers_for_product("product-id")

    mocked_get_transfer_to_process.assert_called_once_with("product-id")
    mocked_adobe_client.preview_transfer.assert_called_once_with(
        mock_transfer.authorization_uk,
        mock_transfer.membership_id,
    )
    mocked_get_offer_ids_by_membership_id.assert_called_once_with(
        "product-id",
        mock_transfer.membership_id,
    )
    mocked_create_offers.assert_called_once_with(
        "product-id",
        [
            {
                "transfer": [mock_transfer],
                "offer_id": adobe_preview_transfer["items"][0]["offerId"],
                "quantity": adobe_preview_transfer["items"][0]["quantity"],
                "renewal_date": date.fromisoformat(
                    adobe_preview_transfer["items"][0]["renewalDate"]
                ),
            },
        ],
    )
    mock_transfer.save.assert_called_once()
    assert mock_transfer.transfer_id == adobe_transfer["transferId"]
    assert mock_transfer.status == STATUS_RUNNING


def test_start_transfers_for_product_preview_already_transferred(
    mocker,
    adobe_api_error_factory,
    adobe_transfer_factory,
    mock_transfer,
):
    mocker.patch(
        "adobe_vipm.flows.migration.get_transfers_to_process",
        return_value=[mock_transfer],
    )

    mocked_populate_offers_for_transfer = mocker.patch(
        "adobe_vipm.flows.migration.populate_offers_for_transfer",
    )

    mocked_adobe_client = mocker.MagicMock()
    mocked_adobe_client.preview_transfer.side_effect = AdobeAPIError(
        400,
        adobe_api_error_factory(
            code=AdobeStatus.STATUS_TRANSFER_ALREADY_TRANSFERRED,
            message="Already transferred",
        ),
    )
    mocker.patch(
        "adobe_vipm.flows.migration.get_adobe_client",
        return_value=mocked_adobe_client,
    )

    start_transfers_for_product("product-id")

    mocked_adobe_client.preview_transfer.assert_called_once_with(
        mock_transfer.authorization_uk,
        mock_transfer.membership_id,
    )

    mock_transfer.save.assert_not_called()
    mocked_populate_offers_for_transfer.assert_not_called()


@pytest.mark.parametrize(
    "reason",
    [
        "RETURNABLE_PURCHASE",
        "IN_WINDOW_NO_RENEWAL",
        "IN_WINDOW_PARTIAL_RENEWAL",
        "EXTENDED_TERM_3YC",
    ],
)
def test_start_transfers_for_product_preview_recoverable_error(
    mocker,
    adobe_api_error_factory,
    reason,
    mock_transfer,
):
    mock_transfer.reschedule_count = 0
    mocker.patch(
        "adobe_vipm.flows.migration.get_transfers_to_process",
        return_value=[mock_transfer],
    )

    mocked_adobe_client = mocker.MagicMock()
    error = AdobeAPIError(
        400,
        adobe_api_error_factory(
            code=AdobeStatus.STATUS_TRANSFER_INELIGIBLE,
            message="Cannot be transferred",
            details=[f"Reason: {reason}"],
        ),
    )
    mocked_adobe_client.preview_transfer.side_effect = error

    mocker.patch(
        "adobe_vipm.flows.migration.get_adobe_client",
        return_value=mocked_adobe_client,
    )

    start_transfers_for_product("product-id")

    mocked_adobe_client.preview_transfer.assert_called_once_with(
        mock_transfer.authorization_uk,
        mock_transfer.membership_id,
    )

    mock_transfer.save.assert_called_once()
    assert mock_transfer.adobe_error_code == AdobeStatus.STATUS_TRANSFER_INELIGIBLE
    assert mock_transfer.adobe_error_description == str(error)
    assert mock_transfer.status == "rescheduled"
    assert mock_transfer.migration_error_description == (
        "Adobe transient error received during transfer preview."
    )


def test_start_transfers_for_product_preview_unrecoverable_error(
    mocker,
    adobe_api_error_factory,
    mock_transfer,
):
    mocker.patch(
        "adobe_vipm.flows.migration.get_transfers_to_process",
        return_value=[mock_transfer],
    )

    mocked_send_exception = mocker.patch(
        "adobe_vipm.flows.migration.send_exception",
    )
    mocker.patch(
        "adobe_vipm.flows.migration.get_transfer_link",
        return_value="https://link.to.transfer",
    )

    mocked_adobe_client = mocker.MagicMock()
    error = AdobeAPIError(
        400,
        adobe_api_error_factory(
            code=AdobeStatus.STATUS_TRANSFER_INELIGIBLE,
            message="Cannot be transferred",
            details=["Reason: BAD_MARKET_SEGMENT"],
        ),
    )
    mocked_adobe_client.preview_transfer.side_effect = error

    mocker.patch(
        "adobe_vipm.flows.migration.get_adobe_client",
        return_value=mocked_adobe_client,
    )

    start_transfers_for_product("product-id")

    mocked_adobe_client.preview_transfer.assert_called_once_with(
        mock_transfer.authorization_uk,
        mock_transfer.membership_id,
    )

    mock_transfer.save.assert_called_once()
    assert mock_transfer.adobe_error_code == AdobeStatus.STATUS_TRANSFER_INELIGIBLE
    assert mock_transfer.adobe_error_description == str(error)
    assert mock_transfer.status == "failed"
    assert mock_transfer.migration_error_description == (
        "An unexpected error has been received from Adobe asking for preview "
            f"of transfer for Membership **{mock_transfer.membership_id}**."
    )
    mocked_send_exception.assert_called_once_with(
        "Adobe error received during transfer preview.",
        "An unexpected error has been received from Adobe asking "
        "for preview of transfer for Membership **membership-id**.",
        facts=FactsSection(
            title="Last error from Adobe",
            data={"5117": "5117 - Cannot be transferred: Reason: BAD_MARKET_SEGMENT"},
        ),
        button=Button(label="membership-id", url="https://link.to.transfer"),
    )


def test_start_transfers_for_product_error(
    mocker,
    adobe_preview_transfer_factory,
    adobe_api_error_factory,
    adobe_items_factory,
    mock_transfer,
):
    mocked_get_transfer_to_process = mocker.patch(
        "adobe_vipm.flows.migration.get_transfers_to_process",
        return_value=[mock_transfer],
    )

    mocked_send_exception = mocker.patch(
        "adobe_vipm.flows.migration.send_exception",
    )
    mocker.patch(
        "adobe_vipm.flows.migration.get_transfer_link",
        return_value="https://link.to.transfer",
    )

    mocked_get_offer_ids_by_membership_id = mocker.patch(
        "adobe_vipm.flows.migration.get_offer_ids_by_membership_id",
        return_value=[],
    )
    mocked_create_offers = mocker.patch(
        "adobe_vipm.flows.migration.create_offers",
    )

    adobe_preview_transfer = adobe_preview_transfer_factory(
        items=adobe_items_factory(renewal_date="2022-10-11"),
    )
    error = AdobeAPIError(
        400,
        adobe_api_error_factory(
            code="9999",
            message="Unexpected error",
        ),
    )

    mocked_adobe_client = mocker.MagicMock()
    mocked_adobe_client.preview_transfer.return_value = adobe_preview_transfer

    mocked_adobe_client.create_transfer.side_effect = error
    mocker.patch(
        "adobe_vipm.flows.migration.get_adobe_client",
        return_value=mocked_adobe_client,
    )

    start_transfers_for_product("product-id")

    mocked_get_transfer_to_process.assert_called_once_with("product-id")
    mocked_adobe_client.preview_transfer.assert_called_once_with(
        mock_transfer.authorization_uk,
        mock_transfer.membership_id,
    )
    mocked_get_offer_ids_by_membership_id.assert_called_once_with(
        "product-id",
        mock_transfer.membership_id,
    )
    mocked_create_offers.assert_called_once_with(
        "product-id",
        [
            {
                "transfer": [mock_transfer],
                "offer_id": adobe_preview_transfer["items"][0]["offerId"],
                "quantity": adobe_preview_transfer["items"][0]["quantity"],
                "renewal_date": date.fromisoformat(
                    adobe_preview_transfer["items"][0]["renewalDate"]
                ),
            },
        ],
    )
    mock_transfer.save.assert_called_once()
    assert mock_transfer.status == "failed"
    assert mock_transfer.adobe_error_code == error.code
    assert mock_transfer.adobe_error_description == str(error)
    assert (
        mock_transfer.migration_error_description
        == "An unexpected error has been received from Adobe creating the "
        f"transfer for Membership **{mock_transfer.membership_id}**."
    )

    mocked_send_exception.assert_called_once_with(
        "Adobe error received during transfer creation.",
        "An unexpected error has been received from Adobe creating "
        "the transfer for Membership **membership-id**.",
        facts=FactsSection(title="Last error from Adobe", data={"9999": "9999 - Unexpected error"}),
        button=Button(label="membership-id", url="https://link.to.transfer"),
    )


def test_start_transfers_for_product_no_authorization_found_error(
    mocker,
    adobe_api_error_factory,
    mock_transfer,
):
    mocked_get_transfer_to_process = mocker.patch(
        "adobe_vipm.flows.migration.get_transfers_to_process",
        return_value=[mock_transfer],
    )

    mocked_send_exception = mocker.patch(
        "adobe_vipm.flows.migration.send_exception",
    )
    mocker.patch(
        "adobe_vipm.flows.migration.get_transfer_link",
        return_value="https://link.to.transfer",
    )

    error = AuthorizationNotFoundError("Authorization is not found")

    mocked_adobe_client = mocker.MagicMock()
    mocked_adobe_client.preview_transfer.side_effect = error

    mocker.patch(
        "adobe_vipm.flows.migration.get_adobe_client",
        return_value=mocked_adobe_client,
    )

    start_transfers_for_product("product-id")

    mocked_get_transfer_to_process.assert_called_once_with("product-id")
    mocked_adobe_client.preview_transfer.assert_called_once_with(
        mock_transfer.authorization_uk,
        mock_transfer.membership_id,
    )
    mock_transfer.save.assert_called_once()
    assert mock_transfer.status == "failed"
    assert mock_transfer.migration_error_description == "Authorization is not found"

    mocked_send_exception.assert_called_once_with(
        "Marketplace Platform configuration error during transfer.",
        "Authorization is not found",
        facts=FactsSection(
            title="Transfer error",
            data={"AuthorizationNotFoundError": mock_transfer.migration_error_description},
        ),
        button=Button(label="membership-id", url="https://link.to.transfer"),
    )


def test_start_transfers_for_product_reseller_not_found_error(
    mocker,
    adobe_preview_transfer_factory,
    adobe_items_factory,
    mock_transfer,
):
    mocked_get_transfer_to_process = mocker.patch(
        "adobe_vipm.flows.migration.get_transfers_to_process",
        return_value=[mock_transfer],
    )

    mocked_send_exception = mocker.patch(
        "adobe_vipm.flows.migration.send_exception",
    )
    mocker.patch(
        "adobe_vipm.flows.migration.get_transfer_link",
        return_value="https://link.to.transfer",
    )

    mocked_get_offer_ids_by_membership_id = mocker.patch(
        "adobe_vipm.flows.migration.get_offer_ids_by_membership_id",
        return_value=[],
    )
    mocked_create_offers = mocker.patch(
        "adobe_vipm.flows.migration.create_offers",
    )

    adobe_preview_transfer = adobe_preview_transfer_factory(
        items=adobe_items_factory(renewal_date="2022-10-11"),
    )
    error = ResellerNotFoundError("Reseller is not found")

    mocked_adobe_client = mocker.MagicMock()
    mocked_adobe_client.preview_transfer.return_value = adobe_preview_transfer

    mocked_adobe_client.create_transfer.side_effect = error
    mocker.patch(
        "adobe_vipm.flows.migration.get_adobe_client",
        return_value=mocked_adobe_client,
    )

    start_transfers_for_product("product-id")

    mocked_get_transfer_to_process.assert_called_once_with("product-id")
    mocked_adobe_client.preview_transfer.assert_called_once_with(
        mock_transfer.authorization_uk,
        mock_transfer.membership_id,
    )
    mocked_get_offer_ids_by_membership_id.assert_called_once_with(
        "product-id",
        mock_transfer.membership_id,
    )
    mocked_create_offers.assert_called_once_with(
        "product-id",
        [
            {
                "transfer": [mock_transfer],
                "offer_id": adobe_preview_transfer["items"][0]["offerId"],
                "quantity": adobe_preview_transfer["items"][0]["quantity"],
                "renewal_date": date.fromisoformat(
                    adobe_preview_transfer["items"][0]["renewalDate"]
                ),
            },
        ],
    )
    mock_transfer.save.assert_called_once()
    assert mock_transfer.status == "failed"
    assert mock_transfer.migration_error_description == str(error)

    mocked_send_exception.assert_called_once_with(
        "Marketplace Platform configuration error during transfer.",
        "Reseller is not found",
        facts=FactsSection(
            title="Transfer error",
            data={"ResellerNotFoundError": mock_transfer.migration_error_description},
        ),
        button=Button(label="membership-id", url="https://link.to.transfer"),
    )


def test_checking_running_transfers_for_product(
    mocker,
    adobe_transfer_factory,
    adobe_subscription_factory,
    mock_transfer,
):
    mock_transfer.nav_cco = "nav-cco"
    mock_transfer.transfer_id = "transfer-id"
    mock_transfer.status = "running"
    mock_transfer.nav_error = None
    mock_transfer.customer_benefits_3yc_status = None

    mocked_get_transfer_to_check = mocker.patch(
        "adobe_vipm.flows.migration.get_transfers_to_check",
        return_value=[mock_transfer],
    )
    mocked_terminate_contract = mocker.patch(
        "adobe_vipm.flows.migration.terminate_contract",
        return_value=(True, '200 - {"id": "whatever"}'),
    )

    adobe_transfer = adobe_transfer_factory(
        status=AdobeStatus.STATUS_PROCESSED,
        customer_id="customer-id",
    )

    customer = {
        "companyProfile": {
            "companyName": "Migrated Company",
            "preferredLanguage": "en-US",
            "address": {
                "addressLine1": "addressLine1",
                "addressLine2": "addressLine2",
                "city": "city",
                "region": "region",
                "postalCode": "postalCode",
                "country": "country",
                "phoneNumber": "phoneNumber",
            },
            "contacts": [
                {
                    "firstName": "firstName",
                    "lastName": "lastName",
                    "email": "email",
                    "phoneNumber": "phoneNumber",
                },
            ],
        }
    }

    sub_active = adobe_subscription_factory()
    sub_inactive = adobe_subscription_factory(status=AdobeStatus.STATUS_INACTIVE_OR_GENERIC_FAILURE)

    mocked_adobe_client = mocker.MagicMock()
    mocked_adobe_client.get_transfer.return_value = adobe_transfer
    mocked_adobe_client.get_customer.return_value = customer
    mocked_adobe_client.get_subscriptions.return_value = {"items": [sub_active, sub_inactive]}
    mocker.patch(
        "adobe_vipm.flows.migration.get_adobe_client",
        return_value=mocked_adobe_client,
    )

    with freeze_time("2024-01-01 12:00:00"):
        check_running_transfers_for_product("product-id")

        mocked_get_transfer_to_check.assert_called_once_with("product-id")
        mocked_adobe_client.get_transfer.assert_called_once_with(
            mock_transfer.authorization_uk,
            mock_transfer.membership_id,
            mock_transfer.transfer_id,
        )
        mock_transfer.save.assert_called_once()

        assert mock_transfer.customer_company_name == customer["companyProfile"]["companyName"]
        assert (
            mock_transfer.customer_preferred_language
            == customer["companyProfile"]["preferredLanguage"]
        )

        address = customer["companyProfile"]["address"]
        assert mock_transfer.customer_address_address_line_1 == address["addressLine1"]
        assert mock_transfer.customer_address_address_line_2 == address["addressLine2"]
        assert mock_transfer.customer_address_city == address["city"]
        assert mock_transfer.customer_address_region == address["region"]
        assert mock_transfer.customer_address_postal_code == address["postalCode"]
        assert mock_transfer.customer_address_country == address["country"]
        assert mock_transfer.customer_address_phone_number == address["phoneNumber"]

        contact = customer["companyProfile"]["contacts"][0]
        assert mock_transfer.customer_contact_first_name == contact["firstName"]
        assert mock_transfer.customer_contact_last_name == contact["lastName"]
        assert mock_transfer.customer_contact_email == contact["email"]
        assert mock_transfer.customer_contact_phone_number == contact["phoneNumber"]

        mocked_terminate_contract.assert_called_once_with("nav-cco")
        assert mock_transfer.nav_terminated is True
        assert mock_transfer.nav_error is None

        assert mock_transfer.status == "completed"
        assert mock_transfer.completed_at == datetime.now()

        mocked_adobe_client.update_subscription.assert_called_once_with(
            mock_transfer.authorization_uk,
            mock_transfer.customer_id,
            sub_active["subscriptionId"],
            auto_renewal=False,
        )


def test_checking_running_transfers_for_product_with_no_profile_address(
    mocker,
    adobe_transfer_factory,
    adobe_subscription_factory,
    mock_transfer,
):
    mock_transfer.nav_cco = "nav-cco"
    mock_transfer.transfer_id = "transfer-id"
    mock_transfer.status = "running"
    mock_transfer.nav_error = None
    mock_transfer.customer_benefits_3yc_status = None

    mocked_get_transfer_to_check = mocker.patch(
        "adobe_vipm.flows.migration.get_transfers_to_check",
        return_value=[mock_transfer],
    )
    mocked_terminate_contract = mocker.patch(
        "adobe_vipm.flows.migration.terminate_contract",
        return_value=(True, '200 - {"id": "whatever"}'),
    )

    adobe_transfer = adobe_transfer_factory(
        status=AdobeStatus.STATUS_PROCESSED,
        customer_id="customer-id",
    )

    customer = {
        "companyProfile": {
            "companyName": "Migrated Company",
            "preferredLanguage": "en-US",
            "contacts": [
                {
                    "firstName": "firstName",
                    "lastName": "lastName",
                    "email": "email",
                    "phoneNumber": "phoneNumber",
                },
            ],
        }
    }

    sub_active = adobe_subscription_factory()
    sub_inactive = adobe_subscription_factory(status=AdobeStatus.STATUS_INACTIVE_OR_GENERIC_FAILURE)

    mocked_adobe_client = mocker.MagicMock()
    mocked_adobe_client.get_transfer.return_value = adobe_transfer
    mocked_adobe_client.get_customer.return_value = customer
    mocked_adobe_client.get_subscriptions.return_value = {"items": [sub_active, sub_inactive]}
    mocker.patch(
        "adobe_vipm.flows.migration.get_adobe_client",
        return_value=mocked_adobe_client,
    )

    with freeze_time("2024-01-01 12:00:00"):
        check_running_transfers_for_product("product-id")

        mocked_get_transfer_to_check.assert_called_once_with("product-id")
        mocked_adobe_client.get_transfer.assert_called_once_with(
            mock_transfer.authorization_uk,
            mock_transfer.membership_id,
            mock_transfer.transfer_id,
        )
        mock_transfer.save.assert_called_once()

        assert mock_transfer.customer_company_name == customer["companyProfile"]["companyName"]
        assert (
            mock_transfer.customer_preferred_language
            == customer["companyProfile"]["preferredLanguage"]
        )

        assert mock_transfer.customer_address_address_line_1 == ""
        assert mock_transfer.customer_address_address_line_2 == ""
        assert mock_transfer.customer_address_city == ""
        assert mock_transfer.customer_address_region == ""
        assert mock_transfer.customer_address_postal_code == ""
        assert mock_transfer.customer_address_country == ""
        assert mock_transfer.customer_address_phone_number == ""

        contact = customer["companyProfile"]["contacts"][0]
        assert mock_transfer.customer_contact_first_name == contact["firstName"]
        assert mock_transfer.customer_contact_last_name == contact["lastName"]
        assert mock_transfer.customer_contact_email == contact["email"]
        assert mock_transfer.customer_contact_phone_number == contact["phoneNumber"]

        mocked_terminate_contract.assert_called_once_with("nav-cco")
        assert mock_transfer.nav_terminated is True
        assert mock_transfer.nav_error is None

        assert mock_transfer.status == "completed"
        assert mock_transfer.completed_at == datetime.now()

        mocked_adobe_client.update_subscription.assert_called_once_with(
            mock_transfer.authorization_uk,
            mock_transfer.customer_id,
            sub_active["subscriptionId"],
            auto_renewal=False,
        )


def test_checking_running_transfers_for_product_3yc(
    mocker,
    adobe_transfer_factory,
    adobe_customer_factory,
    adobe_commitment_factory,
    mock_transfer,
):
    mock_transfer.transfer_id = "transfer-id"
    mock_transfer.status = "running"
    mocker.patch(
        "adobe_vipm.flows.migration.terminate_contract",
        return_value=(True, ""),
    )
    mocker.patch(
        "adobe_vipm.flows.migration.get_transfers_to_check",
        return_value=[mock_transfer],
    )

    adobe_transfer = adobe_transfer_factory(
        status=AdobeStatus.STATUS_PROCESSED,
        customer_id="customer-id",
    )

    commitment = adobe_commitment_factory(licenses=10, consumables=30)
    customer = adobe_customer_factory(commitment=commitment)

    mocked_adobe_client = mocker.MagicMock()
    mocked_adobe_client.get_transfer.return_value = adobe_transfer
    mocked_adobe_client.get_customer.return_value = customer
    mocker.patch(
        "adobe_vipm.flows.migration.get_adobe_client",
        return_value=mocked_adobe_client,
    )

    check_running_transfers_for_product("product-id")

    assert mock_transfer.customer_benefits_3yc_start_date == date.fromisoformat(
        commitment["startDate"]
    )
    assert mock_transfer.customer_benefits_3yc_end_date == date.fromisoformat(commitment["endDate"])
    assert mock_transfer.customer_benefits_3yc_status == commitment["status"]
    assert mock_transfer.customer_benefits_3yc_minimum_quantity_license == 10
    assert mock_transfer.customer_benefits_3yc_minimum_quantity_consumables == 30

    mocked_adobe_client.update_subscription.assert_not_called()


def test_checking_running_transfers_for_product_error_retry(
    mocker,
    adobe_api_error_factory,
    mock_transfer,
):
    mock_transfer.transfer_id = "transfer-id"
    mock_transfer.status = "running"
    mock_transfer.retry_count = 0
    mock_transfer.reschedule_count = 0

    mocker.patch(
        "adobe_vipm.flows.migration.get_transfers_to_check",
        return_value=[mock_transfer],
    )

    error = AdobeAPIError(
        400,
        adobe_api_error_factory(
            code="9999",
            message="Unexpected error",
        ),
    )

    mocked_adobe_client = mocker.MagicMock()
    mocked_adobe_client.get_transfer.side_effect = error

    mocker.patch(
        "adobe_vipm.flows.migration.get_adobe_client",
        return_value=mocked_adobe_client,
    )

    check_running_transfers_for_product("product-id")

    mock_transfer.save.assert_called_once()
    assert mock_transfer.status == "running"
    assert mock_transfer.adobe_error_code == error.code
    assert mock_transfer.adobe_error_description == str(error)
    assert mock_transfer.retry_count == 1


def test_checking_running_transfers_for_product_get_customer_error_retry(
    mocker,
    adobe_api_error_factory,
    adobe_transfer_factory,
    mock_transfer,
):
    mock_transfer.transfer_id = "transfer-id"
    mock_transfer.status = "running"
    mock_transfer.retry_count = 0
    mock_transfer.reschedule_count = 0

    mocker.patch(
        "adobe_vipm.flows.migration.get_transfers_to_check",
        return_value=[mock_transfer],
    )

    adobe_transfer = adobe_transfer_factory(
        status=AdobeStatus.STATUS_PROCESSED,
        customer_id="customer-id",
    )

    error = AdobeAPIError(
        400,
        adobe_api_error_factory(
            code="9999",
            message="Unexpected error",
        ),
    )

    mocked_adobe_client = mocker.MagicMock()
    mocked_adobe_client.get_transfer.return_value = adobe_transfer
    mocked_adobe_client.get_customer.side_effect = error

    mocker.patch(
        "adobe_vipm.flows.migration.get_adobe_client",
        return_value=mocked_adobe_client,
    )

    check_running_transfers_for_product("product-id")

    mock_transfer.save.assert_called_once()
    assert mock_transfer.status == "running"
    assert mock_transfer.adobe_error_code == error.code
    assert mock_transfer.adobe_error_description == str(error)
    assert mock_transfer.retry_count == 1


def test_checking_running_transfers_for_product_update_subs_error_retry(
    mocker,
    adobe_api_error_factory,
    adobe_transfer_factory,
    adobe_subscription_factory,
    mock_transfer,
):
    mock_transfer.transfer_id = "transfer-id"
    mock_transfer.status = "running"
    mock_transfer.retry_count = 0
    mock_transfer.reschedule_count = 0
    mock_transfer.customer_benefits_3yc_status = None

    mocker.patch(
        "adobe_vipm.flows.migration.get_transfers_to_check",
        return_value=[mock_transfer],
    )

    adobe_transfer = adobe_transfer_factory(
        status=AdobeStatus.STATUS_PROCESSED,
        customer_id="customer-id",
    )

    error = AdobeAPIError(
        400,
        adobe_api_error_factory(
            code="9999",
            message="Unexpected error",
        ),
    )

    customer = {
        "companyProfile": {
            "companyName": "Migrated Company",
            "preferredLanguage": "en-US",
            "address": {
                "addressLine1": "addressLine1",
                "addressLine2": "addressLine2",
                "city": "city",
                "region": "region",
                "postalCode": "postalCode",
                "country": "country",
                "phoneNumber": "phoneNumber",
            },
            "contacts": [
                {
                    "firstName": "firstName",
                    "lastName": "lastName",
                    "email": "email",
                    "phoneNumber": "phoneNumber",
                },
            ],
        }
    }

    mocked_adobe_client = mocker.MagicMock()
    mocked_adobe_client.get_transfer.return_value = adobe_transfer
    mocked_adobe_client.get_customer.return_value = customer
    mocked_adobe_client.get_subscriptions.return_value = {"items": [adobe_subscription_factory()]}
    mocked_adobe_client.update_subscription.side_effect = error
    mocker.patch(
        "adobe_vipm.flows.migration.get_adobe_client",
        return_value=mocked_adobe_client,
    )

    check_running_transfers_for_product("product-id")

    mock_transfer.save.assert_called_once()
    assert mock_transfer.status == "running"
    assert mock_transfer.adobe_error_code == error.code
    assert mock_transfer.adobe_error_description == str(error)
    assert mock_transfer.retry_count == 1


def test_checking_running_transfers_for_product_error_max_retries_exceeded(
    mocker,
    settings,
    adobe_api_error_factory,
    mock_transfer,
):
    settings.EXTENSION_CONFIG = {"MIGRATION_RUNNING_MAX_RETRIES": 15}
    mock_transfer.transfer_id = "transfer-id"
    mock_transfer.status = "running"
    mock_transfer.retry_count = 14
    mock_transfer.reschedule_count = 0

    mocker.patch(
        "adobe_vipm.flows.migration.get_transfers_to_check",
        return_value=[mock_transfer],
    )
    mocked_send_error = mocker.patch(
        "adobe_vipm.flows.migration.send_error",
    )
    mocker.patch(
        "adobe_vipm.flows.migration.get_transfer_link",
        return_value="https://link.to.transfer",
    )

    error = AdobeAPIError(
        400,
        adobe_api_error_factory(
            code="9999",
            message="Unexpected error",
        ),
    )

    mocked_adobe_client = mocker.MagicMock()
    mocked_adobe_client.get_transfer.side_effect = error

    mocker.patch(
        "adobe_vipm.flows.migration.get_adobe_client",
        return_value=mocked_adobe_client,
    )

    check_running_transfers_for_product("product-id")

    mock_transfer.save.assert_called_once()
    assert mock_transfer.status == "failed"
    assert mock_transfer.adobe_error_code == error.code
    assert mock_transfer.adobe_error_description == str(error)
    assert mock_transfer.retry_count == 15

    mocked_send_error.assert_called_once_with(
        "Migration max retries exceeded.",
        "The maximum amount of retries (15) has been exceeded for "
        "the Membership **membership-id**.",
        button=Button(label="membership-id", url="https://link.to.transfer"),
        facts=FactsSection(title="Last error from Adobe", data={"9999": "9999 - Unexpected error"}),
    )


def test_checking_running_transfers_for_product_pending_retry(
    mocker,
    adobe_transfer_factory,
    mock_transfer,
):
    mock_transfer.transfer_id = "transfer-id"
    mock_transfer.status = "running"
    mock_transfer.retry_count = 0
    mock_transfer.reschedule_count = 0

    mocker.patch(
        "adobe_vipm.flows.migration.get_transfers_to_check",
        return_value=[mock_transfer],
    )

    mocked_adobe_client = mocker.MagicMock()
    mocked_adobe_client.get_transfer.return_value = adobe_transfer_factory(
        status=AdobeStatus.STATUS_PENDING,
    )

    mocker.patch(
        "adobe_vipm.flows.migration.get_adobe_client",
        return_value=mocked_adobe_client,
    )

    check_running_transfers_for_product("product-id")

    mock_transfer.save.assert_called_once()
    assert mock_transfer.status == "running"
    assert mock_transfer.retry_count == 1


def test_checking_running_transfers_for_product_unexpected_status(
    mocker,
    adobe_transfer_factory,
    mock_transfer,
):
    mock_transfer.transfer_id = "transfer-id"
    mock_transfer.status = "running"
    mock_transfer.retry_count = 0
    mock_transfer.reschedule_count = 0
    mock_transfer.adobe_error_code = "code"
    mock_transfer.adobe_error_description = "message"

    mocker.patch(
        "adobe_vipm.flows.migration.get_transfers_to_check",
        return_value=[mock_transfer],
    )
    mocked_send_exception = mocker.patch(
        "adobe_vipm.flows.migration.send_exception",
    )
    mocker.patch(
        "adobe_vipm.flows.migration.get_transfer_link",
        return_value="https://link.to.transfer",
    )

    adobe_transfer = adobe_transfer_factory(
        status="9999",
    )

    mocked_adobe_client = mocker.MagicMock()
    mocked_adobe_client.get_transfer.return_value = adobe_transfer

    mocker.patch(
        "adobe_vipm.flows.migration.get_adobe_client",
        return_value=mocked_adobe_client,
    )

    check_running_transfers_for_product("product-id")

    mock_transfer.save.assert_called_once()
    assert mock_transfer.status == "failed"
    assert mock_transfer.migration_error_description == (
        f"Unexpected status ({adobe_transfer['status']}) "
        "received from Adobe while retrieving transfer."
    )
    mocked_send_exception.assert_called_once_with(
        "Unexpected status retrieving a transfer.",
        "An unexpected status (9999) has been received from Adobe "
        "retrieving the transfer for Membership **membership-id**.",
        button=Button("membership-id", "https://link.to.transfer"),
        facts=FactsSection("Last error from Adobe", {"code": "message"}),
    )


@freeze_time("2025-04-06 12:30:00")
def test_checking_running_transfers_for_product_authorization_not_found(mocker, mock_transfer):
    mock_transfer.status = (STATUS_RUNNING,)
    mock_transfer.updated_at = (None,)
    mock_transfer.migration_error_description = (None,)

    mocker.patch(
        "adobe_vipm.flows.migration.get_transfers_to_check",
        return_value=[mock_transfer],
    )
    mocked_adobe_client = mocker.MagicMock()
    message_error = f"Authorization with uk/id {mock_transfer.authorization_uk} not found."
    mocked_adobe_client.get_transfer.side_effect = [AuthorizationNotFoundError(message_error)]
    mocker.patch(
        "adobe_vipm.flows.migration.get_adobe_client",
        return_value=mocked_adobe_client,
    )

    check_running_transfers_for_product("product-id")

    mock_transfer.save.assert_called_once()
    assert mock_transfer.status == "failed"
    assert mock_transfer.updated_at == datetime(2025, 4, 6, 12, 30)
    assert mock_transfer.migration_error_description == message_error


def test_checking_running_transfers_with_gc_exists_for_product(
    mocker,
    adobe_transfer_factory,
    adobe_subscription_factory,
    mock_transfer,
):
    mock_transfer.nav_cco = "nav-cco"
    mock_transfer.transfer_id = "transfer-id"
    mock_transfer.status = "running"
    mock_transfer.nav_error = None
    mock_transfer.customer_benefits_3yc_status = None

    mocked_get_transfer_to_check = mocker.patch(
        "adobe_vipm.flows.migration.get_transfers_to_check",
        return_value=[mock_transfer],
    )
    mocked_terminate_contract = mocker.patch(
        "adobe_vipm.flows.migration.terminate_contract",
        return_value=(True, '200 - {"id": "whatever"}'),
    )

    adobe_transfer = adobe_transfer_factory(
        status=AdobeStatus.STATUS_PROCESSED,
        customer_id="customer-id",
    )

    customer = {
        "companyProfile": {
            "companyName": "Migrated Company",
            "preferredLanguage": "en-US",
            "address": {
                "addressLine1": "addressLine1",
                "addressLine2": "addressLine2",
                "city": "city",
                "region": "region",
                "postalCode": "postalCode",
                "country": "country",
                "phoneNumber": "phoneNumber",
            },
            "contacts": [
                {
                    "firstName": "firstName",
                    "lastName": "lastName",
                    "email": "email",
                    "phoneNumber": "phoneNumber",
                },
            ],
        },
        "globalSalesEnabled": True,
    }

    mocked_gc_main_agreement = {
        "membership_id": "membership-id",
        "main_agreement_id": "main-agreement-id",
        "transfer_id": "transfer-id",
        "status": STATUS_GC_PENDING,
        "error_description": "",
    }

    sub_active = adobe_subscription_factory()
    sub_inactive = adobe_subscription_factory(status=AdobeStatus.STATUS_INACTIVE_OR_GENERIC_FAILURE)

    mocked_adobe_client = mocker.MagicMock()
    mocked_adobe_client.get_transfer.return_value = adobe_transfer
    mocked_adobe_client.get_customer.return_value = customer
    mocked_adobe_client.get_subscriptions.return_value = {"items": [sub_active, sub_inactive]}
    mocker.patch(
        "adobe_vipm.flows.migration.get_adobe_client",
        return_value=mocked_adobe_client,
    )

    mocker.patch(
        "adobe_vipm.flows.migration.get_gc_main_agreement",
        return_value=mocked_gc_main_agreement,
    )

    mocked_create_gc_main_agreement = mocker.patch(
        "adobe_vipm.flows.migration.create_gc_main_agreement"
    )

    with freeze_time("2024-01-01 12:00:00"):
        check_running_transfers_for_product("product-id")

        mocked_get_transfer_to_check.assert_called_once_with("product-id")
        mocked_adobe_client.get_transfer.assert_called_once_with(
            mock_transfer.authorization_uk,
            mock_transfer.membership_id,
            mock_transfer.transfer_id,
        )
        mock_transfer.save.assert_called_once()

        assert mock_transfer.customer_company_name == customer["companyProfile"]["companyName"]
        assert (
            mock_transfer.customer_preferred_language
            == customer["companyProfile"]["preferredLanguage"]
        )

        address = customer["companyProfile"]["address"]
        assert mock_transfer.customer_address_address_line_1 == address["addressLine1"]
        assert mock_transfer.customer_address_address_line_2 == address["addressLine2"]
        assert mock_transfer.customer_address_city == address["city"]
        assert mock_transfer.customer_address_region == address["region"]
        assert mock_transfer.customer_address_postal_code == address["postalCode"]
        assert mock_transfer.customer_address_country == address["country"]
        assert mock_transfer.customer_address_phone_number == address["phoneNumber"]

        contact = customer["companyProfile"]["contacts"][0]
        assert mock_transfer.customer_contact_first_name == contact["firstName"]
        assert mock_transfer.customer_contact_last_name == contact["lastName"]
        assert mock_transfer.customer_contact_email == contact["email"]
        assert mock_transfer.customer_contact_phone_number == contact["phoneNumber"]

        mocked_terminate_contract.assert_called_once_with("nav-cco")
        assert mock_transfer.nav_terminated is True
        assert mock_transfer.nav_error is None

        assert mock_transfer.status == "completed"
        assert mock_transfer.completed_at == datetime.now()

        mocked_adobe_client.update_subscription.assert_called_once_with(
            mock_transfer.authorization_uk,
            mock_transfer.customer_id,
            sub_active["subscriptionId"],
            auto_renewal=False,
        )

        mocked_create_gc_main_agreement.assert_not_called()


def test_checking_running_transfers_with_gc_exists_for_product_with_no_profile_address(
    mocker,
    adobe_transfer_factory,
    adobe_subscription_factory,
    mock_transfer,
):
    mock_transfer.nav_cco = "nav-cco"
    mock_transfer.transfer_id = "transfer-id"
    mock_transfer.status = "running"
    mock_transfer.nav_error = None
    mock_transfer.customer_benefits_3yc_status = None

    mocked_get_transfer_to_check = mocker.patch(
        "adobe_vipm.flows.migration.get_transfers_to_check",
        return_value=[mock_transfer],
    )
    mocked_terminate_contract = mocker.patch(
        "adobe_vipm.flows.migration.terminate_contract",
        return_value=(True, '200 - {"id": "whatever"}'),
    )

    adobe_transfer = adobe_transfer_factory(
        status=AdobeStatus.STATUS_PROCESSED,
        customer_id="customer-id",
    )

    customer = {
        "companyProfile": {
            "companyName": "Migrated Company",
            "preferredLanguage": "en-US",
            "contacts": [
                {
                    "firstName": "firstName",
                    "lastName": "lastName",
                    "email": "email",
                    "phoneNumber": "phoneNumber",
                },
            ],
        },
        "globalSalesEnabled": True,
    }

    mocked_gc_main_agreement = {
        "membership_id": "membership-id",
        "main_agreement_id": "main-agreement-id",
        "transfer_id": "transfer-id",
        "status": STATUS_GC_PENDING,
        "error_description": "",
    }

    sub_active = adobe_subscription_factory()
    sub_inactive = adobe_subscription_factory(status=AdobeStatus.STATUS_INACTIVE_OR_GENERIC_FAILURE)

    mocked_adobe_client = mocker.MagicMock()
    mocked_adobe_client.get_transfer.return_value = adobe_transfer
    mocked_adobe_client.get_customer.return_value = customer
    mocked_adobe_client.get_subscriptions.return_value = {"items": [sub_active, sub_inactive]}
    mocker.patch(
        "adobe_vipm.flows.migration.get_adobe_client",
        return_value=mocked_adobe_client,
    )

    mocker.patch(
        "adobe_vipm.flows.migration.get_gc_main_agreement",
        return_value=mocked_gc_main_agreement,
    )

    mocked_create_gc_main_agreement = mocker.patch(
        "adobe_vipm.flows.migration.create_gc_main_agreement"
    )

    with freeze_time("2024-01-01 12:00:00"):
        check_running_transfers_for_product("product-id")

        mocked_get_transfer_to_check.assert_called_once_with("product-id")
        mocked_adobe_client.get_transfer.assert_called_once_with(
            mock_transfer.authorization_uk,
            mock_transfer.membership_id,
            mock_transfer.transfer_id,
        )
        mock_transfer.save.assert_called_once()

        assert mock_transfer.customer_company_name == customer["companyProfile"]["companyName"]
        assert (
            mock_transfer.customer_preferred_language
            == customer["companyProfile"]["preferredLanguage"]
        )

        assert mock_transfer.customer_address_address_line_1 == ""
        assert mock_transfer.customer_address_address_line_2 == ""
        assert mock_transfer.customer_address_city == ""
        assert mock_transfer.customer_address_region == ""
        assert mock_transfer.customer_address_postal_code == ""
        assert mock_transfer.customer_address_country == ""
        assert mock_transfer.customer_address_phone_number == ""

        contact = customer["companyProfile"]["contacts"][0]
        assert mock_transfer.customer_contact_first_name == contact["firstName"]
        assert mock_transfer.customer_contact_last_name == contact["lastName"]
        assert mock_transfer.customer_contact_email == contact["email"]
        assert mock_transfer.customer_contact_phone_number == contact["phoneNumber"]

        mocked_terminate_contract.assert_called_once_with("nav-cco")
        assert mock_transfer.nav_terminated is True
        assert mock_transfer.nav_error is None

        assert mock_transfer.status == "completed"
        assert mock_transfer.completed_at == datetime.now()

        mocked_adobe_client.update_subscription.assert_called_once_with(
            mock_transfer.authorization_uk,
            mock_transfer.customer_id,
            sub_active["subscriptionId"],
            auto_renewal=False,
        )

        mocked_create_gc_main_agreement.assert_not_called()


def test_checking_running_transfers_with_gc_not_exists_for_product(
    mocker,
    adobe_transfer_factory,
    adobe_subscription_factory,
    mock_transfer,
):
    mocked_product_id = "product-id"
    mock_transfer.nav_cco = "nav-cco"
    mock_transfer.transfer_id = "transfer-id"
    mock_transfer.status = "running"
    mock_transfer.nav_error = None
    mock_transfer.customer_benefits_3yc_status = None
    mock_transfer.customer_id = ""

    mocked_get_transfer_to_check = mocker.patch(
        "adobe_vipm.flows.migration.get_transfers_to_check",
        return_value=[mock_transfer],
    )
    mocked_terminate_contract = mocker.patch(
        "adobe_vipm.flows.migration.terminate_contract",
        return_value=(True, '200 - {"id": "whatever"}'),
    )

    adobe_transfer = adobe_transfer_factory(
        status=AdobeStatus.STATUS_PROCESSED,
        customer_id="customer-id",
    )

    customer = {
        "companyProfile": {
            "companyName": "Migrated Company",
            "preferredLanguage": "en-US",
            "address": {
                "addressLine1": "addressLine1",
                "addressLine2": "addressLine2",
                "city": "city",
                "region": "region",
                "postalCode": "postalCode",
                "country": "country",
                "phoneNumber": "phoneNumber",
            },
            "contacts": [
                {
                    "firstName": "firstName",
                    "lastName": "lastName",
                    "email": "email",
                    "phoneNumber": "phoneNumber",
                },
            ],
        },
        "globalSalesEnabled": True,
    }

    mocked_gc_main_agreement_data = {
        "authorization_uk": mock_transfer.authorization_uk,
        "membership_id": mock_transfer.membership_id,
        "transfer_id": mock_transfer.transfer_id,
        "customer_id": "customer-id",
        "status": STATUS_GC_PENDING,
    }

    sub_active = adobe_subscription_factory()
    sub_inactive = adobe_subscription_factory(status=AdobeStatus.STATUS_INACTIVE_OR_GENERIC_FAILURE)

    mocked_adobe_client = mocker.MagicMock()
    mocked_adobe_client.get_transfer.return_value = adobe_transfer
    mocked_adobe_client.get_customer.return_value = customer
    mocked_adobe_client.get_subscriptions.return_value = {"items": [sub_active, sub_inactive]}
    mocker.patch(
        "adobe_vipm.flows.migration.get_adobe_client",
        return_value=mocked_adobe_client,
    )

    mocker.patch(
        "adobe_vipm.flows.migration.get_gc_main_agreement",
        return_value=None,
    )

    mocked_create_gc_main_agreement = mocker.patch(
        "adobe_vipm.flows.migration.create_gc_main_agreement"
    )

    with freeze_time("2024-01-01 12:00:00"):
        check_running_transfers_for_product(mocked_product_id)

        mocked_get_transfer_to_check.assert_called_once_with(mocked_product_id)
        mocked_adobe_client.get_transfer.assert_called_once_with(
            mock_transfer.authorization_uk,
            mock_transfer.membership_id,
            mock_transfer.transfer_id,
        )
        mock_transfer.save.assert_called_once()

        assert mock_transfer.customer_company_name == customer["companyProfile"]["companyName"]
        assert (
            mock_transfer.customer_preferred_language
            == customer["companyProfile"]["preferredLanguage"]
        )

        address = customer["companyProfile"]["address"]
        assert mock_transfer.customer_address_address_line_1 == address["addressLine1"]
        assert mock_transfer.customer_address_address_line_2 == address["addressLine2"]
        assert mock_transfer.customer_address_city == address["city"]
        assert mock_transfer.customer_address_region == address["region"]
        assert mock_transfer.customer_address_postal_code == address["postalCode"]
        assert mock_transfer.customer_address_country == address["country"]
        assert mock_transfer.customer_address_phone_number == address["phoneNumber"]

        contact = customer["companyProfile"]["contacts"][0]
        assert mock_transfer.customer_contact_first_name == contact["firstName"]
        assert mock_transfer.customer_contact_last_name == contact["lastName"]
        assert mock_transfer.customer_contact_email == contact["email"]
        assert mock_transfer.customer_contact_phone_number == contact["phoneNumber"]

        mocked_terminate_contract.assert_called_once_with("nav-cco")
        assert mock_transfer.nav_terminated is True
        assert mock_transfer.nav_error is None

        assert mock_transfer.status == "completed"
        assert mock_transfer.completed_at == datetime.now()

        mocked_adobe_client.update_subscription.assert_called_once_with(
            mock_transfer.authorization_uk,
            mock_transfer.customer_id,
            sub_active["subscriptionId"],
            auto_renewal=False,
        )

        mocked_create_gc_main_agreement.assert_called_once_with(
            mocked_product_id,
            mocked_gc_main_agreement_data,
        )


def test_checking_running_transfers_with_gc_not_exists_for_product_with_no_profile_address(
    mocker,
    adobe_transfer_factory,
    adobe_subscription_factory,
    mock_transfer,
):
    mocked_product_id = "product-id"
    mock_transfer.nav_cco = "nav-cco"
    mock_transfer.transfer_id = "transfer-id"
    mock_transfer.status = "running"
    mock_transfer.nav_error = None
    mock_transfer.customer_benefits_3yc_status = None
    mock_transfer.customer_id = ""

    mocked_get_transfer_to_check = mocker.patch(
        "adobe_vipm.flows.migration.get_transfers_to_check",
        return_value=[mock_transfer],
    )
    mocked_terminate_contract = mocker.patch(
        "adobe_vipm.flows.migration.terminate_contract",
        return_value=(True, '200 - {"id": "whatever"}'),
    )

    adobe_transfer = adobe_transfer_factory(
        status=AdobeStatus.STATUS_PROCESSED,
        customer_id="customer-id",
    )

    customer = {
        "companyProfile": {
            "companyName": "Migrated Company",
            "preferredLanguage": "en-US",
            "contacts": [
                {
                    "firstName": "firstName",
                    "lastName": "lastName",
                    "email": "email",
                    "phoneNumber": "phoneNumber",
                },
            ],
        },
        "globalSalesEnabled": True,
    }

    mocked_gc_main_agreement_data = {
        "authorization_uk": mock_transfer.authorization_uk,
        "membership_id": mock_transfer.membership_id,
        "transfer_id": mock_transfer.transfer_id,
        "customer_id": "customer-id",
        "status": STATUS_GC_PENDING,
    }

    sub_active = adobe_subscription_factory()
    sub_inactive = adobe_subscription_factory(status=AdobeStatus.STATUS_INACTIVE_OR_GENERIC_FAILURE)

    mocked_adobe_client = mocker.MagicMock()
    mocked_adobe_client.get_transfer.return_value = adobe_transfer
    mocked_adobe_client.get_customer.return_value = customer
    mocked_adobe_client.get_subscriptions.return_value = {"items": [sub_active, sub_inactive]}
    mocker.patch(
        "adobe_vipm.flows.migration.get_adobe_client",
        return_value=mocked_adobe_client,
    )

    mocker.patch(
        "adobe_vipm.flows.migration.get_gc_main_agreement",
        return_value=None,
    )

    mocked_create_gc_main_agreement = mocker.patch(
        "adobe_vipm.flows.migration.create_gc_main_agreement"
    )

    with freeze_time("2024-01-01 12:00:00"):
        check_running_transfers_for_product(mocked_product_id)

        mocked_get_transfer_to_check.assert_called_once_with(mocked_product_id)
        mocked_adobe_client.get_transfer.assert_called_once_with(
            mock_transfer.authorization_uk,
            mock_transfer.membership_id,
            mock_transfer.transfer_id,
        )
        mock_transfer.save.assert_called_once()

        assert mock_transfer.customer_company_name == customer["companyProfile"]["companyName"]
        assert (
            mock_transfer.customer_preferred_language
            == customer["companyProfile"]["preferredLanguage"]
        )

        assert mock_transfer.customer_address_address_line_1 == ""
        assert mock_transfer.customer_address_address_line_2 == ""
        assert mock_transfer.customer_address_city == ""
        assert mock_transfer.customer_address_region == ""
        assert mock_transfer.customer_address_postal_code == ""
        assert mock_transfer.customer_address_country == ""
        assert mock_transfer.customer_address_phone_number == ""

        contact = customer["companyProfile"]["contacts"][0]
        assert mock_transfer.customer_contact_first_name == contact["firstName"]
        assert mock_transfer.customer_contact_last_name == contact["lastName"]
        assert mock_transfer.customer_contact_email == contact["email"]
        assert mock_transfer.customer_contact_phone_number == contact["phoneNumber"]

        mocked_terminate_contract.assert_called_once_with("nav-cco")
        assert mock_transfer.nav_terminated is True
        assert mock_transfer.nav_error is None

        assert mock_transfer.status == "completed"
        assert mock_transfer.completed_at == datetime.now()

        mocked_adobe_client.update_subscription.assert_called_once_with(
            mock_transfer.authorization_uk,
            mock_transfer.customer_id,
            sub_active["subscriptionId"],
            auto_renewal=False,
        )

        mocked_create_gc_main_agreement.assert_called_once_with(
            mocked_product_id,
            mocked_gc_main_agreement_data,
        )


def test_checking_running_transfers_with_gc_not_exists_and_airtable_error_for_product(
    mocker,
    adobe_transfer_factory,
    adobe_subscription_factory,
    airtable_error_factory,
    mock_transfer,
):
    mocked_product_id = "product-id"
    mock_transfer.nav_cco = "nav-cco"
    mock_transfer.transfer_id = "transfer-id"
    mock_transfer.status = "running"
    mock_transfer.nav_error = None
    mock_transfer.customer_benefits_3yc_status = None
    mock_transfer.customer_id = ""

    error = AirTableAPIError(
        400,
        airtable_error_factory(
            "Bad Request",
            "BAD_REQUEST",
        ),
    )

    mocked_send_error = mocker.patch("adobe_vipm.flows.migration.send_error")

    mocked_get_transfer_to_check = mocker.patch(
        "adobe_vipm.flows.migration.get_transfers_to_check",
        return_value=[mock_transfer],
    )
    mocked_terminate_contract = mocker.patch(
        "adobe_vipm.flows.migration.terminate_contract",
        return_value=(True, '200 - {"id": "whatever"}'),
    )

    adobe_transfer = adobe_transfer_factory(
        status=AdobeStatus.STATUS_PROCESSED,
        customer_id="customer-id",
    )

    customer = {
        "companyProfile": {
            "companyName": "Migrated Company",
            "preferredLanguage": "en-US",
            "address": {
                "addressLine1": "addressLine1",
                "addressLine2": "addressLine2",
                "city": "city",
                "region": "region",
                "postalCode": "postalCode",
                "country": "country",
                "phoneNumber": "phoneNumber",
            },
            "contacts": [
                {
                    "firstName": "firstName",
                    "lastName": "lastName",
                    "email": "email",
                    "phoneNumber": "phoneNumber",
                },
            ],
        },
        "globalSalesEnabled": True,
    }

    mocked_gc_main_agreement_data = {
        "authorization_uk": mock_transfer.authorization_uk,
        "membership_id": mock_transfer.membership_id,
        "transfer_id": mock_transfer.transfer_id,
        "customer_id": "customer-id",
        "status": STATUS_GC_PENDING,
    }

    sub_active = adobe_subscription_factory()
    sub_inactive = adobe_subscription_factory(status=AdobeStatus.STATUS_INACTIVE_OR_GENERIC_FAILURE)

    mocked_adobe_client = mocker.MagicMock()
    mocked_adobe_client.get_transfer.return_value = adobe_transfer
    mocked_adobe_client.get_customer.return_value = customer
    mocked_adobe_client.get_subscriptions.return_value = {"items": [sub_active, sub_inactive]}
    mocker.patch(
        "adobe_vipm.flows.migration.get_adobe_client",
        return_value=mocked_adobe_client,
    )

    mocker.patch(
        "adobe_vipm.flows.migration.get_gc_main_agreement",
        return_value=None,
    )

    mocked_create_gc_main_agreement = mocker.patch(
        "adobe_vipm.flows.migration.create_gc_main_agreement",
        side_effect=error,
    )

    with freeze_time("2024-01-01 12:00:00"):
        check_running_transfers_for_product(mocked_product_id)

        mocked_get_transfer_to_check.assert_called_once_with(mocked_product_id)
        mocked_adobe_client.get_transfer.assert_called_once_with(
            mock_transfer.authorization_uk,
            mock_transfer.membership_id,
            mock_transfer.transfer_id,
        )
        mock_transfer.save.assert_called_once()

        assert mock_transfer.customer_company_name == customer["companyProfile"]["companyName"]
        assert (
            mock_transfer.customer_preferred_language
            == customer["companyProfile"]["preferredLanguage"]
        )

        address = customer["companyProfile"]["address"]
        assert mock_transfer.customer_address_address_line_1 == address["addressLine1"]
        assert mock_transfer.customer_address_address_line_2 == address["addressLine2"]
        assert mock_transfer.customer_address_city == address["city"]
        assert mock_transfer.customer_address_region == address["region"]
        assert mock_transfer.customer_address_postal_code == address["postalCode"]
        assert mock_transfer.customer_address_country == address["country"]
        assert mock_transfer.customer_address_phone_number == address["phoneNumber"]

        contact = customer["companyProfile"]["contacts"][0]
        assert mock_transfer.customer_contact_first_name == contact["firstName"]
        assert mock_transfer.customer_contact_last_name == contact["lastName"]
        assert mock_transfer.customer_contact_email == contact["email"]
        assert mock_transfer.customer_contact_phone_number == contact["phoneNumber"]

        mocked_terminate_contract.assert_called_once_with("nav-cco")
        assert mock_transfer.nav_terminated is True
        assert mock_transfer.nav_error is None

        assert mock_transfer.status == "completed"
        assert mock_transfer.completed_at == datetime.now()

        mocked_adobe_client.update_subscription.assert_called_once_with(
            mock_transfer.authorization_uk,
            mock_transfer.customer_id,
            sub_active["subscriptionId"],
            auto_renewal=False,
        )

        mocked_create_gc_main_agreement.assert_called_once_with(
            mocked_product_id,
            mocked_gc_main_agreement_data,
        )

        mocked_send_error.assert_called_once_with(
            "Error saving Global Customer Main Agreement",
            "An error occurred while saving the Global Customer Main Agreement.",
            button=get_transfer_link_button(mock_transfer),
            facts=FactsSection(
                "Error from checking running transfers",
                "400 - Bad Request",
            ),
        )


def test_checking_running_transfers_with_gc_not_exists_no_address_and_airtable_error_for_product(
    mocker,
    adobe_transfer_factory,
    adobe_subscription_factory,
    airtable_error_factory,
    mock_transfer,
):
    mocked_product_id = "product-id"
    mock_transfer.nav_cco = "nav-cco"
    mock_transfer.transfer_id = "transfer-id"
    mock_transfer.status = "running"
    mock_transfer.nav_error = None
    mock_transfer.customer_benefits_3yc_status = None
    mock_transfer.customer_id = ""

    error = AirTableAPIError(
        400,
        airtable_error_factory(
            "Bad Request",
            "BAD_REQUEST",
        ),
    )

    mocked_send_error = mocker.patch("adobe_vipm.flows.migration.send_error")

    mocked_get_transfer_to_check = mocker.patch(
        "adobe_vipm.flows.migration.get_transfers_to_check",
        return_value=[mock_transfer],
    )
    mocked_terminate_contract = mocker.patch(
        "adobe_vipm.flows.migration.terminate_contract",
        return_value=(True, '200 - {"id": "whatever"}'),
    )

    adobe_transfer = adobe_transfer_factory(
        status=AdobeStatus.STATUS_PROCESSED,
        customer_id="customer-id",
    )

    customer = {
        "companyProfile": {
            "companyName": "Migrated Company",
            "preferredLanguage": "en-US",
            "contacts": [
                {
                    "firstName": "firstName",
                    "lastName": "lastName",
                    "email": "email",
                    "phoneNumber": "phoneNumber",
                },
            ],
        },
        "globalSalesEnabled": True,
    }

    mocked_gc_main_agreement_data = {
        "authorization_uk": mock_transfer.authorization_uk,
        "membership_id": mock_transfer.membership_id,
        "transfer_id": mock_transfer.transfer_id,
        "customer_id": "customer-id",
        "status": STATUS_GC_PENDING,
    }

    sub_active = adobe_subscription_factory()
    sub_inactive = adobe_subscription_factory(status=AdobeStatus.STATUS_INACTIVE_OR_GENERIC_FAILURE)

    mocked_adobe_client = mocker.MagicMock()
    mocked_adobe_client.get_transfer.return_value = adobe_transfer
    mocked_adobe_client.get_customer.return_value = customer
    mocked_adobe_client.get_subscriptions.return_value = {"items": [sub_active, sub_inactive]}
    mocker.patch(
        "adobe_vipm.flows.migration.get_adobe_client",
        return_value=mocked_adobe_client,
    )

    mocker.patch(
        "adobe_vipm.flows.migration.get_gc_main_agreement",
        return_value=None,
    )

    mocked_create_gc_main_agreement = mocker.patch(
        "adobe_vipm.flows.migration.create_gc_main_agreement",
        side_effect=error,
    )

    with freeze_time("2024-01-01 12:00:00"):
        check_running_transfers_for_product(mocked_product_id)

        mocked_get_transfer_to_check.assert_called_once_with(mocked_product_id)
        mocked_adobe_client.get_transfer.assert_called_once_with(
            mock_transfer.authorization_uk,
            mock_transfer.membership_id,
            mock_transfer.transfer_id,
        )
        mock_transfer.save.assert_called_once()

        assert mock_transfer.customer_company_name == customer["companyProfile"]["companyName"]
        assert (
            mock_transfer.customer_preferred_language
            == customer["companyProfile"]["preferredLanguage"]
        )

        assert mock_transfer.customer_address_address_line_1 == ""
        assert mock_transfer.customer_address_address_line_2 == ""
        assert mock_transfer.customer_address_city == ""
        assert mock_transfer.customer_address_region == ""
        assert mock_transfer.customer_address_postal_code == ""
        assert mock_transfer.customer_address_country == ""
        assert mock_transfer.customer_address_phone_number == ""

        contact = customer["companyProfile"]["contacts"][0]
        assert mock_transfer.customer_contact_first_name == contact["firstName"]
        assert mock_transfer.customer_contact_last_name == contact["lastName"]
        assert mock_transfer.customer_contact_email == contact["email"]
        assert mock_transfer.customer_contact_phone_number == contact["phoneNumber"]

        mocked_terminate_contract.assert_called_once_with("nav-cco")
        assert mock_transfer.nav_terminated is True
        assert mock_transfer.nav_error is None

        assert mock_transfer.status == "completed"
        assert mock_transfer.completed_at == datetime.now()

        mocked_adobe_client.update_subscription.assert_called_once_with(
            mock_transfer.authorization_uk,
            mock_transfer.customer_id,
            sub_active["subscriptionId"],
            auto_renewal=False,
        )

        mocked_create_gc_main_agreement.assert_called_once_with(
            mocked_product_id,
            mocked_gc_main_agreement_data,
        )

        mocked_send_error.assert_called_once_with(
            "Error saving Global Customer Main Agreement",
            "An error occurred while saving the Global Customer Main Agreement.",
            button=get_transfer_link_button(mock_transfer),
            facts=FactsSection(
                "Error from checking running transfers",
                "400 - Bad Request",
            ),
        )


def test_process_transfers(mocker, settings):
    settings.MPT_PRODUCTS_IDS = ["PRD-1111", "PRD-2222"]
    mocked_start_transfers_for_product = mocker.patch(
        "adobe_vipm.flows.migration.start_transfers_for_product",
    )
    process_transfers()

    assert mocked_start_transfers_for_product.mock_calls[0].args == ("PRD-1111",)
    assert mocked_start_transfers_for_product.mock_calls[1].args == ("PRD-2222",)


def test_check_running_transfers(mocker, settings):
    settings.MPT_PRODUCTS_IDS = ["PRD-1111", "PRD-2222"]
    mocked_check_running_transfers_for_product = mocker.patch(
        "adobe_vipm.flows.migration.check_running_transfers_for_product",
    )
    check_running_transfers()

    assert mocked_check_running_transfers_for_product.mock_calls[0].args == ("PRD-1111",)
    assert mocked_check_running_transfers_for_product.mock_calls[1].args == ("PRD-2222",)


def test_start_transfers_for_product_preview_recoverable_error_max_reschedules_exceeded(
    mocker,
    settings,
    adobe_api_error_factory,
    mock_transfer,
):
    settings.EXTENSION_CONFIG = {"MIGRATION_RESCHEDULE_MAX_RETRIES": 15}
    mock_transfer.reschedule_count = 14

    mocker.patch(
        "adobe_vipm.flows.migration.get_transfers_to_process",
        return_value=[mock_transfer],
    )

    mocked_send_warning = mocker.patch(
        "adobe_vipm.flows.migration.send_warning",
    )
    mocker.patch(
        "adobe_vipm.flows.migration.get_transfer_link",
        return_value="https://link.to.transfer",
    )

    mocked_adobe_client = mocker.MagicMock()
    error = AdobeAPIError(
        400,
        adobe_api_error_factory(
            code=AdobeStatus.STATUS_TRANSFER_INELIGIBLE,
            message="Cannot be transferred",
            details=["Reason: RETURNABLE_PURCHASE"],
        ),
    )
    mocked_adobe_client.preview_transfer.side_effect = error

    mocker.patch(
        "adobe_vipm.flows.migration.get_adobe_client",
        return_value=mocked_adobe_client,
    )

    start_transfers_for_product("product-id")

    mocked_adobe_client.preview_transfer.assert_called_once_with(
        mock_transfer.authorization_uk,
        mock_transfer.membership_id,
    )

    mock_transfer.save.assert_called_once()
    assert mock_transfer.adobe_error_code == AdobeStatus.STATUS_TRANSFER_INELIGIBLE
    assert mock_transfer.adobe_error_description == str(error)
    assert mock_transfer.status == "failed"
    assert mock_transfer.reschedule_count == 15
    assert mock_transfer.migration_error_description == ("Max reschedules (15) exceeded.")
    mocked_send_warning.assert_called_once_with(
        "Migration max reschedules exceeded.",
        "The maximum amount of reschedules (15) has been exceeded for the Membership "
        "**membership-id**.",
        button=Button(label="membership-id", url="https://link.to.transfer"),
        facts=FactsSection(
            title="Last error from Adobe",
            data={"5117": "5117 - Cannot be transferred: Reason: RETURNABLE_PURCHASE"},
        ),
    )


def test_checking_running_transfers_for_product_terminate_contract_error(
    mocker,
    adobe_transfer_factory,
    adobe_customer_factory,
    mock_transfer,
):
    mock_transfer.nav_cco = "nav-cco"
    mock_transfer.transfer_id = "transfer-id"
    mock_transfer.status = "running"
    mock_transfer.nav_error = None

    mocker.patch(
        "adobe_vipm.flows.migration.get_transfers_to_check",
        return_value=[mock_transfer],
    )
    mocked_terminate_contract = mocker.patch(
        "adobe_vipm.flows.migration.terminate_contract",
        return_value=(False, "internal server error"),
    )

    adobe_transfer = adobe_transfer_factory(
        status=AdobeStatus.STATUS_PROCESSED,
        customer_id="customer-id",
    )

    customer = adobe_customer_factory()

    mocked_adobe_client = mocker.MagicMock()
    mocked_adobe_client.get_transfer.return_value = adobe_transfer
    mocked_adobe_client.get_customer.return_value = customer
    mocker.patch(
        "adobe_vipm.flows.migration.get_adobe_client",
        return_value=mocked_adobe_client,
    )

    with freeze_time("2024-01-01 12:00:00"):
        check_running_transfers_for_product("product-id")

        mocked_terminate_contract.assert_called_once_with("nav-cco")
        assert mock_transfer.nav_terminated is False
        assert mock_transfer.nav_error == "internal server error"

        assert mock_transfer.status == "completed"
        assert mock_transfer.completed_at == datetime.now()


@pytest.mark.parametrize(
    ("return_value", "expected_value"),
    [
        (None, None),
        ("https://link.to.transfer", Button("label", "https://link.to.transfer")),
    ],
)
def test_get_transfer_link_button(mocker, return_value, expected_value):
    mocker.patch("adobe_vipm.flows.migration.get_transfer_link", return_value=return_value)
    mocked_transfer = mocker.MagicMock()
    mocked_transfer.membership_id = "label"
    assert get_transfer_link_button(mocked_transfer) == expected_value


def test_checking_gc_main_agreement_when_exists(mocker, mock_transfer):
    mock_transfer.customer_id = "customer-id"
    mock_transfer.transfer_id = "transfer-id"

    mocked_gc_main_agreement = {
        "membership_id": "membership-id",
        "main_agreement_id": "main-agreement-id",
        "transfer_id": "transfer-id",
        "status": STATUS_GC_PENDING,
        "error_description": "",
    }

    mocker.patch(
        "adobe_vipm.flows.migration.get_gc_main_agreement",
        return_value=mocked_gc_main_agreement,
    )

    mocked_create_gc_main_agreement = mocker.patch(
        "adobe_vipm.flows.migration.create_gc_main_agreement"
    )

    mocked_create_gc_main_agreement.assert_not_called()
