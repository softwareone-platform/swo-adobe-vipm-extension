from dataclasses import dataclass
from functools import cache

from django.conf import settings
from pyairtable.formulas import EQUAL, FIELD, OR, STR_VALUE
from pyairtable.orm import Model, fields
from swo.mpt.extensions.runtime.djapp.conf import to_postfix


@dataclass(frozen=True)
class AirTableBaseInfo:
    api_key: str
    base_id: str

    @staticmethod
    def for_product(product_id):
        return AirTableBaseInfo(
            api_key=settings.EXTENSION_CONFIG["AIRTABLE_API_TOKEN"],
            base_id=settings.EXTENSION_CONFIG[f"AIRTABLE_BASE_{to_postfix(product_id)}"],
        )


@cache
def get_transfer_model(base_info):
    class Transfer(Model):
        membership_id = fields.TextField("membership_id")
        customer_name = fields.TextField("customer_name")
        customer_country = fields.TextField("customer_country")
        customer_contact_name = fields.TextField("customer_contact_name")
        customer_contact_email = fields.TextField("customer_contact_email")
        authorization_uk = fields.TextField("authorization_uk")
        seller_uk = fields.TextField("seller_uk")
        record_id = fields.TextField("record_id", readonly=True)
        transfer_id = fields.TextField("transfer_id")
        customer_id = fields.TextField("customer_id")
        mpt_order_id = fields.TextField("mpt_order_id")
        adobe_error_code = fields.TextField("adobe_error_code")
        adobe_error_description = fields.TextField("adobe_error_description")
        retry_count = fields.NumberField("retry_count")
        status = fields.SelectField("status")
        migration_error_description = fields.TextField("migration_error_description")
        created_at = fields.DatetimeField("created_at", readonly=True)
        updated_at = fields.DatetimeField("updated_at", readonly=True)
        completed_at = fields.DatetimeField("completed_at")
        synchronized_at = fields.DatetimeField("synchronized_at")

        class Meta:
            table_name = "Transfers"
            api_key = base_info.api_key
            base_id = base_info.base_id

    return Transfer


@cache
def get_offer_model(base_info):
    Transfer = get_transfer_model(base_info)
    class Offer(Model):
        transfer = fields.LinkField("membership_id", Transfer, lazy=True)
        offer_id = fields.TextField("offer_id")
        quantity = fields.NumberField("quantity")
        renewal_date = fields.DateField("renewal_date")
        subscription_id = fields.TextField("subscription_id")
        created_at = fields.DatetimeField("created_at", readonly=True)
        updated_at = fields.DatetimeField("updated_at", readonly=True)

        class Meta:
            table_name = "Offers"
            api_key = base_info.api_key
            base_id = base_info.base_id

    return Offer


def get_offer_ids_by_membership_id(product_id, membership_id):
    Offer = get_offer_model(AirTableBaseInfo.for_product(product_id))
    return [
        offer.offer_id
        for offer in Offer.all(
            formula=EQUAL(FIELD("membership_id"), STR_VALUE(membership_id))
        )
    ]


def create_offers(product_id, offers):
    Offer = get_offer_model(AirTableBaseInfo.for_product(product_id))
    Offer.batch_save([Offer(**offer) for offer in offers])


def get_transfers_to_process(product_id):
    Transfer = get_transfer_model(AirTableBaseInfo.for_product(product_id))
    return Transfer.all(
        formula=OR(
            EQUAL(FIELD("status"), STR_VALUE("init")),
            EQUAL(FIELD("status"), STR_VALUE("rescheduled")),
        ),
    )

def get_transfers_to_check(product_id):
    Transfer = get_transfer_model(AirTableBaseInfo.for_product(product_id))
    return Transfer.all(
        formula=EQUAL(FIELD("status"), STR_VALUE("running")),
    )
