from datetime import date, datetime

from django.conf import settings

from adobe_vipm.adobe.client import get_adobe_client
from adobe_vipm.adobe.constants import (
    STATUS_PENDING,
    STATUS_PROCESSED,
    STATUS_TRANSFER_ALREADY_TRANSFERRED,
)
from adobe_vipm.adobe.errors import AdobeAPIError
from adobe_vipm.flows.airtable import (
    create_offers,
    get_offer_ids_by_membership_id,
    get_transfers_to_check,
    get_transfers_to_process,
)

RECOVERABLE_TRANSFER_ERRORS = (
    "RETURNABLE_PURCHASE",
    "IN_WINDOW_NO_RENEWAL",
    "IN_WINDOW_PARTIAL_RENEWAL",
    "EXTENDED_TERM_3YC",
)


def check_retries(transfer):
    max_retries = int(
        settings.EXTENSION_CONFIG.get("MIGRATION_RUNNING_MAX_RETRIES", 15)
    )
    transfer.retry_count += 1
    if transfer.retry_count < max_retries:
        transfer.save()
        return

    transfer.migration_error_description = f"Max retries ({max_retries}) exceeded."
    transfer.status = "failed"
    transfer.save()


def populate_offers_for_transfer(product_id, transfer, transfer_preview):
    existing_offers = get_offer_ids_by_membership_id(product_id, transfer.membership_id)

    offers = [
        {
            "transfer": [transfer],
            "offer_id": item["offerId"],
            "quantity": item["quantity"],
            "renewal_date": date.fromisoformat(item["renewalDate"]),
        }
        for item in transfer_preview["items"]
        if item["offerId"] not in existing_offers
    ]

    create_offers(product_id, offers)


def start_transfers_for_product(product_id):
    client = get_adobe_client()

    for transfer in get_transfers_to_process(product_id):
        transfer_preview = None
        try:
            transfer_preview = client.preview_transfer(
                transfer.authorization_uk,
                transfer.membership_id,
            )
        except AdobeAPIError as api_err:
            if api_err.code != STATUS_TRANSFER_ALREADY_TRANSFERRED:
                transfer.adobe_error_code = api_err.code
                transfer.adobe_error_description = str(api_err)
                if any(x in str(api_err) for x in RECOVERABLE_TRANSFER_ERRORS):
                    transfer.status = "rescheduled"
                    transfer.migration_error_description = (
                        "Adobe transient error received during transfer preview."
                    )
                else:
                    transfer.status = "failed"
                    transfer.migration_error_description = (
                        "Adobe error received during transfer preview."
                    )

                transfer.save()
                continue

        if transfer_preview:
            populate_offers_for_transfer(
                product_id,
                transfer,
                transfer_preview,
            )

        adobe_transfer = None

        try:
            adobe_transfer = client.create_transfer(
                transfer.authorization_uk,
                transfer.seller_uk,
                transfer.record_id,
                transfer.membership_id,
            )
        except AdobeAPIError as api_err:
            transfer.adobe_error_code = api_err.code
            transfer.adobe_error_description = str(api_err)
            transfer.migration_error_description = (
                "Adobe error received during transfer creation."
            )
            transfer.status = "failed"
            transfer.save()
            continue

        transfer.transfer_id = adobe_transfer["transferId"]
        transfer.status = "running"
        transfer.save()


def check_running_transfers_for_product(product_id):
    client = get_adobe_client()

    transfers_to_check = get_transfers_to_check(product_id)

    for transfer in transfers_to_check:
        adobe_transfer = None
        try:
            adobe_transfer = client.get_transfer(
                transfer.authorization_uk,
                transfer.membership_id,
                transfer.transfer_id,
            )
        except AdobeAPIError as api_err:
            transfer.return_code = api_err.code
            transfer.return_description = str(api_err)
            check_retries(transfer)
            continue

        if adobe_transfer["status"] == STATUS_PENDING:
            check_retries(transfer)
            continue

        elif adobe_transfer["status"] != STATUS_PROCESSED:
            transfer.migration_error_description = (
                f"Unexpected status ({adobe_transfer['status']}) "
                "received from Adobe while retrieving transfer."
            )
            transfer.status = "failed"
            transfer.save()
            continue

        transfer.customer_id = adobe_transfer["customerId"]
        transfer.status = "completed"
        transfer.completed_at = datetime.now()
        transfer.save()


def process_transfers():
    for product_id in settings.MPT_PRODUCTS_IDS:
        start_transfers_for_product(product_id)


def check_running_transfers():
    for product_id in settings.MPT_PRODUCTS_IDS:
        check_running_transfers_for_product(product_id)
