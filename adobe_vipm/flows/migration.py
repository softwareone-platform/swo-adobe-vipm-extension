import logging
from datetime import date, datetime

from django.conf import settings

from adobe_vipm.adobe.client import get_adobe_client
from adobe_vipm.adobe.constants import (
    STATUS_3YC_COMMITTED,
    STATUS_PENDING,
    STATUS_PROCESSED,
    STATUS_TRANSFER_ALREADY_TRANSFERRED,
)
from adobe_vipm.adobe.errors import (
    AdobeAPIError,
    AuthorizationNotFoundError,
    ResellerNotFoundError,
)
from adobe_vipm.adobe.utils import get_3yc_commitment
from adobe_vipm.flows.airtable import (
    create_offers,
    get_offer_ids_by_membership_id,
    get_transfer_link,
    get_transfers_to_check,
    get_transfers_to_process,
)
from adobe_vipm.flows.nav import terminate_contract
from adobe_vipm.notifications import (
    Button,
    FactsSection,
    send_error,
    send_exception,
    send_warning,
)

RECOVERABLE_TRANSFER_ERRORS = (
    "RETURNABLE_PURCHASE",
    "IN_WINDOW_NO_RENEWAL",
    "IN_WINDOW_PARTIAL_RENEWAL",
    "EXTENDED_TERM_3YC",
)

logger = logging.getLogger(__name__)


def get_transfer_link_button(transfer):
    link = get_transfer_link(transfer)
    if link:
        return Button(transfer.membership_id, link)


def fill_customer_data(transfer, customer):
    transfer.customer_company_name = customer["companyProfile"]["companyName"]
    transfer.customer_preferred_language = customer["companyProfile"][
        "preferredLanguage"
    ]

    address = customer["companyProfile"]["address"]
    transfer.customer_address_address_line_1 = address["addressLine1"]
    transfer.customer_address_address_line_2 = address["addressLine2"]
    transfer.customer_address_city = address["city"]
    transfer.customer_address_region = address["region"]
    transfer.customer_address_postal_code = address["postalCode"]
    transfer.customer_address_country = address["country"]
    transfer.customer_address_phone_number = address["phoneNumber"]

    contact = customer["companyProfile"]["contacts"][0]
    transfer.customer_contact_first_name = contact["firstName"]
    transfer.customer_contact_last_name = contact["lastName"]
    transfer.customer_contact_email = contact["email"]
    transfer.customer_contact_phone_number = contact.get("phoneNumber")

    commitment = get_3yc_commitment(customer)
    if not commitment:
        return transfer

    transfer.customer_benefits_3yc_start_date = date.fromisoformat(
        commitment["startDate"]
    )
    transfer.customer_benefits_3yc_end_date = date.fromisoformat(commitment["endDate"])
    transfer.customer_benefits_3yc_status = commitment["status"]

    for mq in commitment["minimumQuantities"]:
        setattr(
            transfer,
            f"customer_benefits_3yc_minimum_quantity_{mq['offerType'].lower()}",
            mq["quantity"],
        )

    return transfer


def check_retries(transfer):
    max_retries = int(
        settings.EXTENSION_CONFIG.get("MIGRATION_RUNNING_MAX_RETRIES", 15)
    )
    transfer.retry_count += 1
    if transfer.retry_count < max_retries:
        transfer.updated_at = datetime.now()
        transfer.save()
        return

    transfer.migration_error_description = f"Max retries ({max_retries}) exceeded."
    transfer.status = "failed"
    transfer.updated_at = datetime.now()
    transfer.save()

    facts = None

    if transfer.adobe_error_code:
        facts = FactsSection(
            "Last error from Adobe",
            {transfer.adobe_error_code: transfer.adobe_error_description},
        )
    send_error(
        "Migration max retries exceeded.",
        f"The maximum amount of retries ({max_retries}) "
        f"has been exceeded for the Membership **{transfer.membership_id}**.",
        button=get_transfer_link_button(transfer),
        facts=facts,
    )


def check_reschedules(transfer):
    max_reschedule = int(
        settings.EXTENSION_CONFIG.get("MIGRATION_RESCHEDULE_MAX_RETRIES", 60)
    )
    transfer.reschedule_count += 1
    if transfer.reschedule_count < max_reschedule:
        transfer.updated_at = datetime.now()
        transfer.save()
        return

    transfer.migration_error_description = (
        f"Max reschedules ({max_reschedule}) exceeded."
    )
    transfer.status = "failed"
    transfer.updated_at = datetime.now()
    transfer.save()
    send_warning(
        "Migration max reschedules exceeded.",
        f"The maximum amount of reschedules ({max_reschedule}) "
        f"has been exceeded for the Membership **{transfer.membership_id}**.",
        facts=FactsSection(
            "Last error from Adobe",
            {transfer.adobe_error_code: transfer.adobe_error_description},
        ),
        button=get_transfer_link_button(transfer),
    )


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

    transfers_to_process = get_transfers_to_process(product_id)
    logger.info(f"Found {len(transfers_to_process)} transfers for product {product_id}")
    for transfer in transfers_to_process:
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
                    check_reschedules(transfer)
                else:
                    transfer.status = "failed"
                    transfer.migration_error_description = (
                        "Adobe error received during transfer preview."
                    )
                    transfer.updated_at = datetime.now()
                    transfer.save()
                    send_exception(
                        "Adobe error received during transfer preview.",
                        "An unexpected error has been received from Adobe asking for preview "
                        f"of transfer for Membership **{transfer.membership_id}**.",
                        facts=FactsSection(
                            "Last error from Adobe",
                            {
                                transfer.adobe_error_code: transfer.adobe_error_description
                            },
                        ),
                        button=get_transfer_link_button(transfer),
                    )
                continue
        except AuthorizationNotFoundError as e:
            transfer.status = "failed"
            transfer.migration_error_description = str(e)
            transfer.updated_at = datetime.now()
            transfer.save()
            send_exception(
                "Marketplace Platform configuration error during transfer.",
                str(e),
                facts=FactsSection(
                    "Transfer error",
                    {
                        "AuthorizationNotFoundError": transfer.migration_error_description
                    },
                ),
                button=get_transfer_link_button(transfer),
            )
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
            transfer.updated_at = datetime.now()
            transfer.save()
            send_exception(
                "Adobe error received during transfer creation.",
                "An unexpected error has been received from Adobe creating the "
                f"transfer for Membership **{transfer.membership_id}**.",
                facts=FactsSection(
                    "Last error from Adobe",
                    {transfer.adobe_error_code: transfer.adobe_error_description},
                ),
                button=get_transfer_link_button(transfer),
            )
            continue
        except ResellerNotFoundError as e:
            transfer.status = "failed"
            transfer.migration_error_description = str(e)
            transfer.updated_at = datetime.now()
            transfer.save()
            send_exception(
                "Marketplace Platform configuration error during transfer.",
                str(e),
                facts=FactsSection(
                    "Transfer error",
                    {"ResellerNotFoundError": transfer.migration_error_description},
                ),
                button=get_transfer_link_button(transfer),
            )
            continue

        transfer.transfer_id = adobe_transfer["transferId"]
        transfer.status = "running"
        transfer.updated_at = datetime.now()
        transfer.save()


def check_running_transfers_for_product(product_id):
    client = get_adobe_client()

    transfers_to_check = get_transfers_to_check(product_id)
    logger.info(
        f"Found {len(transfers_to_check)} running transfers for product {product_id}"
    )
    for transfer in transfers_to_check:
        adobe_transfer = None
        try:
            adobe_transfer = client.get_transfer(
                transfer.authorization_uk,
                transfer.membership_id,
                transfer.transfer_id,
            )
        except AdobeAPIError as api_err:
            transfer.adobe_error_code = api_err.code
            transfer.adobe_error_description = str(api_err)
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
            transfer.updated_at = datetime.now()
            transfer.save()
            send_exception(
                "Unexpected status retrieving a transfer.",
                f"An unexpected status ({adobe_transfer['status']}) has been received from Adobe "
                f"retrieving the transfer for Membership **{transfer.membership_id}**.",
                facts=FactsSection(
                    "Last error from Adobe",
                    {transfer.adobe_error_code: transfer.adobe_error_description},
                ),
                button=get_transfer_link_button(transfer),
            )
            continue

        transfer.customer_id = adobe_transfer["customerId"]

        customer = None
        try:
            customer = client.get_customer(
                transfer.authorization_uk, transfer.customer_id
            )
        except AdobeAPIError as api_err:
            transfer.adobe_error_code = api_err.code
            transfer.adobe_error_description = str(api_err)
            check_retries(transfer)
            continue

        transfer = fill_customer_data(transfer, customer)

        if transfer.customer_benefits_3yc_status != STATUS_3YC_COMMITTED:
            subscriptions = client.get_subscriptions(
                transfer.authorization_uk,
                transfer.customer_id,
            )
            try:
                for subscription in subscriptions["items"]:
                    if subscription["status"] != STATUS_PROCESSED:
                        continue
                    client.update_subscription(
                        transfer.authorization_uk,
                        transfer.customer_id,
                        subscription["subscriptionId"],
                        auto_renewal=False,
                    )
            except AdobeAPIError as api_err:
                transfer.adobe_error_code = api_err.code
                transfer.adobe_error_description = str(api_err)
                check_retries(transfer)
                continue

        terminated, response = terminate_contract(transfer.nav_cco)

        transfer.nav_terminated = terminated
        if not terminated:
            transfer.nav_error = response

        transfer.status = "completed"
        transfer.updated_at = datetime.now()
        transfer.completed_at = datetime.now()
        transfer.save()


def process_transfers():
    for product_id in settings.MPT_PRODUCTS_IDS:
        start_transfers_for_product(product_id)


def check_running_transfers():
    for product_id in settings.MPT_PRODUCTS_IDS:
        check_running_transfers_for_product(product_id)
