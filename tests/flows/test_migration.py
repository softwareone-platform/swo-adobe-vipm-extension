from datetime import date, datetime

import pytest
from freezegun import freeze_time

from adobe_vipm.adobe.constants import (
    STATUS_PENDING,
    STATUS_PROCESSED,
    STATUS_TRANSFER_ALREADY_TRANSFERRED,
    STATUS_TRANSFER_INELIGIBLE,
)
from adobe_vipm.adobe.errors import AdobeAPIError
from adobe_vipm.flows.migration import (
    check_running_transfers,
    check_running_transfers_for_product,
    process_transfers,
    start_transfers_for_product,
)


def test_start_transfers_for_product(
    mocker, adobe_preview_transfer_factory, adobe_transfer_factory, adobe_items_factory,
):
    mocked_transfer = mocker.MagicMock()
    mocked_transfer.authorization_uk = "auth-uk"
    mocked_transfer.seller_uk = "seller-uk"
    mocked_transfer.membership_id = "membership-id"
    mocked_transfer.record_id = "record-id"

    mocked_get_transfer_to_process = mocker.patch(
        "adobe_vipm.flows.migration.get_transfers_to_process",
        return_value=[mocked_transfer],
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
        mocked_transfer.authorization_uk,
        mocked_transfer.membership_id,
    )
    mocked_get_offer_ids_by_membership_id.assert_called_once_with(
        "product-id",
        mocked_transfer.membership_id,
    )
    mocked_create_offers.assert_called_once_with(
        "product-id",
        [
            {
                "transfer": [mocked_transfer],
                "offer_id": adobe_preview_transfer["items"][0]["offerId"],
                "quantity": adobe_preview_transfer["items"][0]["quantity"],
                "renewal_date": date.fromisoformat(
                    adobe_preview_transfer["items"][0]["renewalDate"]
                ),
            },
        ],
    )
    mocked_transfer.save.assert_called_once()
    assert mocked_transfer.transfer_id == adobe_transfer["transferId"]
    assert mocked_transfer.status == "running"


def test_start_transfers_for_product_preview_already_transferred(
    mocker, adobe_api_error_factory, adobe_transfer_factory
):
    mocked_transfer = mocker.MagicMock()
    mocked_transfer.authorization_uk = "auth-uk"
    mocked_transfer.seller_uk = "seller-uk"
    mocked_transfer.membership_id = "membership-id"
    mocked_transfer.record_id = "record-id"

    mocker.patch(
        "adobe_vipm.flows.migration.get_transfers_to_process",
        return_value=[mocked_transfer],
    )

    mocked_populate_offers_for_transfer = mocker.patch(
        "adobe_vipm.flows.migration.populate_offers_for_transfer",
    )

    adobe_transfer = adobe_transfer_factory()

    mocked_adobe_client = mocker.MagicMock()
    mocked_adobe_client.preview_transfer.side_effect = AdobeAPIError(
        adobe_api_error_factory(
            code=STATUS_TRANSFER_ALREADY_TRANSFERRED,
            message="Already transferred",
        ),
    )
    mocked_adobe_client.create_transfer.return_value = adobe_transfer
    mocker.patch(
        "adobe_vipm.flows.migration.get_adobe_client",
        return_value=mocked_adobe_client,
    )

    start_transfers_for_product("product-id")

    mocked_adobe_client.preview_transfer.assert_called_once_with(
        mocked_transfer.authorization_uk,
        mocked_transfer.membership_id,
    )

    mocked_transfer.save.assert_called_once()
    assert mocked_transfer.transfer_id == adobe_transfer["transferId"]
    assert mocked_transfer.status == "running"
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
):
    mocked_transfer = mocker.MagicMock()
    mocked_transfer.authorization_uk = "auth-uk"
    mocked_transfer.seller_uk = "seller-uk"
    mocked_transfer.membership_id = "membership-id"
    mocked_transfer.record_id = "record-id"

    mocker.patch(
        "adobe_vipm.flows.migration.get_transfers_to_process",
        return_value=[mocked_transfer],
    )

    mocked_adobe_client = mocker.MagicMock()
    error = AdobeAPIError(
        adobe_api_error_factory(
            code=STATUS_TRANSFER_INELIGIBLE,
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
        mocked_transfer.authorization_uk,
        mocked_transfer.membership_id,
    )

    mocked_transfer.save.assert_called_once()
    assert mocked_transfer.adobe_error_code == STATUS_TRANSFER_INELIGIBLE
    assert mocked_transfer.adobe_error_description == str(error)
    assert mocked_transfer.status == "rescheduled"
    assert mocked_transfer.migration_error_description == (
        "Adobe transient error received during transfer preview."
    )


def test_start_transfers_for_product_preview_unrecoverable_error(
    mocker,
    adobe_api_error_factory,
):
    mocked_transfer = mocker.MagicMock()
    mocked_transfer.authorization_uk = "auth-uk"
    mocked_transfer.seller_uk = "seller-uk"
    mocked_transfer.membership_id = "membership-id"
    mocked_transfer.record_id = "record-id"

    mocker.patch(
        "adobe_vipm.flows.migration.get_transfers_to_process",
        return_value=[mocked_transfer],
    )

    mocked_adobe_client = mocker.MagicMock()
    error = AdobeAPIError(
        adobe_api_error_factory(
            code=STATUS_TRANSFER_INELIGIBLE,
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
        mocked_transfer.authorization_uk,
        mocked_transfer.membership_id,
    )

    mocked_transfer.save.assert_called_once()
    assert mocked_transfer.adobe_error_code == STATUS_TRANSFER_INELIGIBLE
    assert mocked_transfer.adobe_error_description == str(error)
    assert mocked_transfer.status == "failed"
    assert mocked_transfer.migration_error_description == (
        "Adobe error received during transfer preview."
    )


def test_start_transfers_for_product_error(
    mocker,
    adobe_preview_transfer_factory,
    adobe_api_error_factory,
    adobe_items_factory,
):
    mocked_transfer = mocker.MagicMock()
    mocked_transfer.authorization_uk = "auth-uk"
    mocked_transfer.seller_uk = "seller-uk"
    mocked_transfer.membership_id = "membership-id"
    mocked_transfer.record_id = "record-id"

    mocked_get_transfer_to_process = mocker.patch(
        "adobe_vipm.flows.migration.get_transfers_to_process",
        return_value=[mocked_transfer],
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
        mocked_transfer.authorization_uk,
        mocked_transfer.membership_id,
    )
    mocked_get_offer_ids_by_membership_id.assert_called_once_with(
        "product-id",
        mocked_transfer.membership_id,
    )
    mocked_create_offers.assert_called_once_with(
        "product-id",
        [
            {
                "transfer": [mocked_transfer],
                "offer_id": adobe_preview_transfer["items"][0]["offerId"],
                "quantity": adobe_preview_transfer["items"][0]["quantity"],
                "renewal_date": date.fromisoformat(
                    adobe_preview_transfer["items"][0]["renewalDate"]
                ),
            },
        ],
    )
    mocked_transfer.save.assert_called_once()
    assert mocked_transfer.status == "failed"
    assert mocked_transfer.adobe_error_code == error.code
    assert mocked_transfer.adobe_error_description == str(error)
    assert (
        mocked_transfer.migration_error_description
        == "Adobe error received during transfer creation."
    )


def test_checking_running_transfers_for_product(
    mocker,
    adobe_transfer_factory,
):
    mocked_transfer = mocker.MagicMock()
    mocked_transfer.authorization_uk = "auth-uk"
    mocked_transfer.seller_uk = "seller-uk"
    mocked_transfer.membership_id = "membership-id"
    mocked_transfer.record_id = "record-id"
    mocked_transfer.transfer_id = "transfer-id"
    mocked_transfer.status = "running"

    mocked_get_transfer_to_check = mocker.patch(
        "adobe_vipm.flows.migration.get_transfers_to_check",
        return_value=[mocked_transfer],
    )

    adobe_transfer = adobe_transfer_factory(
        status=STATUS_PROCESSED,
        customer_id="customer-id",
    )

    mocked_adobe_client = mocker.MagicMock()
    mocked_adobe_client.get_transfer.return_value = adobe_transfer
    mocker.patch(
        "adobe_vipm.flows.migration.get_adobe_client",
        return_value=mocked_adobe_client,
    )

    with freeze_time("2024-01-01 12:00:00"):
        check_running_transfers_for_product("product-id")

        mocked_get_transfer_to_check.assert_called_once_with("product-id")
        mocked_adobe_client.get_transfer.assert_called_once_with(
            mocked_transfer.authorization_uk,
            mocked_transfer.membership_id,
            mocked_transfer.transfer_id,
        )
        mocked_transfer.save.assert_called_once()
        assert mocked_transfer.status == "completed"
        assert mocked_transfer.completed_at == datetime.now()


def test_checking_running_transfers_for_product_error_retry(
    mocker,
    adobe_api_error_factory,
):
    mocked_transfer = mocker.MagicMock()
    mocked_transfer.authorization_uk = "auth-uk"
    mocked_transfer.seller_uk = "seller-uk"
    mocked_transfer.membership_id = "membership-id"
    mocked_transfer.record_id = "record-id"
    mocked_transfer.transfer_id = "transfer-id"
    mocked_transfer.status = "running"
    mocked_transfer.retry_count = 0

    mocker.patch(
        "adobe_vipm.flows.migration.get_transfers_to_check",
        return_value=[mocked_transfer],
    )

    error = AdobeAPIError(
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

    mocked_transfer.save.assert_called_once()
    assert mocked_transfer.status == "running"
    assert mocked_transfer.return_code == error.code
    assert mocked_transfer.return_description == str(error)
    assert mocked_transfer.retry_count == 1


def test_checking_running_transfers_for_product_error_max_retries_exceeded(
    mocker,
    settings,
    adobe_api_error_factory,
):
    settings.EXTENSION_CONFIG["MIGRATION_RUNNING_MAX_RETRIES"] = 15
    mocked_transfer = mocker.MagicMock()
    mocked_transfer.authorization_uk = "auth-uk"
    mocked_transfer.seller_uk = "seller-uk"
    mocked_transfer.membership_id = "membership-id"
    mocked_transfer.record_id = "record-id"
    mocked_transfer.transfer_id = "transfer-id"
    mocked_transfer.status = "running"
    mocked_transfer.retry_count = 14

    mocker.patch(
        "adobe_vipm.flows.migration.get_transfers_to_check",
        return_value=[mocked_transfer],
    )

    error = AdobeAPIError(
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

    mocked_transfer.save.assert_called_once()
    assert mocked_transfer.status == "failed"
    assert mocked_transfer.return_code == error.code
    assert mocked_transfer.return_description == str(error)
    assert mocked_transfer.retry_count == 15


def test_checking_running_transfers_for_product_pending_retry(
    mocker,
    adobe_transfer_factory,
):
    mocked_transfer = mocker.MagicMock()
    mocked_transfer.authorization_uk = "auth-uk"
    mocked_transfer.seller_uk = "seller-uk"
    mocked_transfer.membership_id = "membership-id"
    mocked_transfer.record_id = "record-id"
    mocked_transfer.transfer_id = "transfer-id"
    mocked_transfer.status = "running"
    mocked_transfer.retry_count = 0

    mocker.patch(
        "adobe_vipm.flows.migration.get_transfers_to_check",
        return_value=[mocked_transfer],
    )

    mocked_adobe_client = mocker.MagicMock()
    mocked_adobe_client.get_transfer.return_value = adobe_transfer_factory(
        status=STATUS_PENDING,
    )

    mocker.patch(
        "adobe_vipm.flows.migration.get_adobe_client",
        return_value=mocked_adobe_client,
    )

    check_running_transfers_for_product("product-id")

    mocked_transfer.save.assert_called_once()
    assert mocked_transfer.status == "running"
    assert mocked_transfer.retry_count == 1


def test_checking_running_transfers_for_product_unexpected_status(
    mocker,
    adobe_transfer_factory,
):
    mocked_transfer = mocker.MagicMock()
    mocked_transfer.authorization_uk = "auth-uk"
    mocked_transfer.seller_uk = "seller-uk"
    mocked_transfer.membership_id = "membership-id"
    mocked_transfer.record_id = "record-id"
    mocked_transfer.transfer_id = "transfer-id"
    mocked_transfer.status = "running"
    mocked_transfer.retry_count = 0

    mocker.patch(
        "adobe_vipm.flows.migration.get_transfers_to_check",
        return_value=[mocked_transfer],
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

    mocked_transfer.save.assert_called_once()
    assert mocked_transfer.status == "failed"
    assert mocked_transfer.migration_error_description == (
        f"Unexpected status ({adobe_transfer['status']}) "
        "received from Adobe while retrieving transfer."
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

    assert mocked_check_running_transfers_for_product.mock_calls[0].args == (
        "PRD-1111",
    )
    assert mocked_check_running_transfers_for_product.mock_calls[1].args == (
        "PRD-2222",
    )