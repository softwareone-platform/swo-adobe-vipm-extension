from collections import defaultdict
from dataclasses import dataclass
from functools import cache

from django.conf import settings
from pyairtable.formulas import (
    AND,
    EQUAL,
    FIELD,
    GREATER,
    LESS_EQUAL,
    NOT_EQUAL,
    OR,
    STR_VALUE,
    to_airtable_value,
)
from pyairtable.orm import Model, fields
from requests import HTTPError
from swo.mpt.extensions.runtime.djapp.conf import get_for_product

from adobe_vipm.utils import find_first

STATUS_INIT = "init"
STATUS_RUNNING = "running"
STATUS_RESCHEDULED = "rescheduled"
STATUS_DUPLICATED = "duplicated"
STATUS_SYNCHRONIZED = "synchronized"

PRICELIST_CACHE = defaultdict(list)


@dataclass(frozen=True)
class AirTableBaseInfo:
    api_key: str
    base_id: str

    @staticmethod
    def for_migrations(product_id):
        return AirTableBaseInfo(
            api_key=settings.EXTENSION_CONFIG["AIRTABLE_API_TOKEN"],
            base_id=get_for_product(settings, "AIRTABLE_BASES", product_id),
        )

    @staticmethod
    def for_pricing(product_id):
        return AirTableBaseInfo(
            api_key=settings.EXTENSION_CONFIG["AIRTABLE_API_TOKEN"],
            base_id=get_for_product(settings, "AIRTABLE_PRICING_BASES", product_id),
        )


@cache
def get_transfer_model(base_info):
    class Transfer(Model):
        membership_id = fields.TextField("membership_id")
        authorization_uk = fields.TextField("authorization_uk")
        seller_uk = fields.TextField("seller_uk")
        nav_cco = fields.TextField("nav_cco")
        record_id = fields.TextField("record_id", readonly=True)
        transfer_id = fields.TextField("transfer_id")
        customer_id = fields.TextField("customer_id")
        customer_company_name = fields.TextField("customer_company_name")
        customer_preferred_language = fields.TextField("customer_preferred_language")
        customer_address_address_line_1 = fields.TextField(
            "customer_address_address_line_1"
        )
        customer_address_address_line_2 = fields.TextField(
            "customer_address_address_line_2"
        )
        customer_address_city = fields.TextField("customer_address_city")
        customer_address_region = fields.TextField("customer_address_region")
        customer_address_postal_code = fields.TextField("customer_address_postal_code")
        customer_address_country = fields.TextField("customer_address_country")
        customer_address_phone_number = fields.TextField(
            "customer_address_phone_number"
        )
        customer_contact_first_name = fields.TextField("customer_contact_first_name")
        customer_contact_last_name = fields.TextField("customer_contact_last_name")
        customer_contact_email = fields.TextField("customer_contact_email")
        customer_contact_phone_number = fields.TextField(
            "customer_contact_phone_number"
        )
        customer_benefits_3yc_start_date = fields.DateField(
            "customer_benefits_3yc_start_date"
        )
        customer_benefits_3yc_end_date = fields.DateField(
            "customer_benefits_3yc_end_date"
        )
        customer_benefits_3yc_status = fields.TextField("customer_benefits_3yc_status")
        customer_benefits_3yc_minimum_quantity_license = fields.NumberField(
            "customer_benefits_3yc_minimum_quantity_license",
        )
        customer_benefits_3yc_minimum_quantity_consumables = fields.NumberField(
            "customer_benefits_3yc_minimum_quantity_consumables",
        )
        adobe_error_code = fields.TextField("adobe_error_code")
        adobe_error_description = fields.TextField("adobe_error_description")
        retry_count = fields.NumberField("retry_count")
        reschedule_count = fields.NumberField("reschedule_count")
        mpt_order_id = fields.TextField("mpt_order_id")
        nav_terminated = fields.CheckboxField("nav_terminated")
        nav_error = fields.TextField("nav_error")
        status = fields.SelectField("status")
        migration_error_description = fields.TextField("migration_error_description")
        created_at = fields.DatetimeField("created_at", readonly=True)
        updated_at = fields.DatetimeField("updated_at")
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
    Offer = get_offer_model(AirTableBaseInfo.for_migrations(product_id))
    return [
        offer.offer_id
        for offer in Offer.all(
            formula=EQUAL(FIELD("membership_id"), STR_VALUE(membership_id))
        )
    ]


def create_offers(product_id, offers):
    Offer = get_offer_model(AirTableBaseInfo.for_migrations(product_id))
    Offer.batch_save([Offer(**offer) for offer in offers])


def get_transfers_to_process(product_id):
    Transfer = get_transfer_model(AirTableBaseInfo.for_migrations(product_id))
    return Transfer.all(
        formula=OR(
            EQUAL(FIELD("status"), STR_VALUE(STATUS_INIT)),
            EQUAL(FIELD("status"), STR_VALUE(STATUS_RESCHEDULED)),
        ),
    )


def get_transfers_to_check(product_id):
    Transfer = get_transfer_model(AirTableBaseInfo.for_migrations(product_id))
    return Transfer.all(
        formula=EQUAL(FIELD("status"), STR_VALUE(STATUS_RUNNING)),
    )


def get_transfer_by_authorization_membership_or_customer(
    product_id, authorization_uk, membership_or_customer_id
):
    Transfer = get_transfer_model(AirTableBaseInfo.for_migrations(product_id))
    transfers = Transfer.all(
        formula=AND(
            EQUAL(FIELD("authorization_uk"), STR_VALUE(authorization_uk)),
            OR(
                EQUAL(FIELD("membership_id"), STR_VALUE(membership_or_customer_id)),
                EQUAL(FIELD("customer_id"), STR_VALUE(membership_or_customer_id)),
            ),
            NOT_EQUAL(FIELD("status"), STR_VALUE(STATUS_DUPLICATED)),
        ),
    )

    return transfers[0] if transfers else None


def get_transfer_link(transfer):
    try:
        base_id = transfer.Meta.base_id
        table_id = transfer.get_table().id
        view_id = transfer.get_table().schema().view("Transfer View").id
        record_id = transfer.id
        return f"https://airtable.com/{base_id}/{table_id}/{view_id}/{record_id}"
    except HTTPError:
        pass


@cache
def get_pricelist_model(base_info):
    class PriceList(Model):
        record_id = fields.TextField("id", readonly=True)
        sku = fields.TextField("sku")
        partial_sku = fields.TextField("partial_sku", readonly=True)
        item_name = fields.TextField("item_name")
        discount_level = fields.TextField("discount_level", readonly=True)
        valid_from = fields.DateField("valid_from")
        valid_until = fields.DateField("valid_until")
        currency = fields.SelectField("currency")
        unit_pp = fields.NumberField("unit_pp")
        unit_lp = fields.NumberField("unit_lp")
        status = fields.SelectField("status")
        created_at = fields.CreatedTimeField("created_at", readonly=True)
        created_by = fields.CreatedByField("created_by", readonly=True)
        updated_at = fields.LastModifiedTimeField("updated_at", readonly=True)
        updated_by = fields.LastModifiedByField("updated_by", readonly=True)

        class Meta:
            table_name = "PriceList"
            api_key = base_info.api_key
            base_id = base_info.base_id

    return PriceList


def get_prices_for_skus(product_id, currency, skus):
    PriceList = get_pricelist_model(AirTableBaseInfo.for_pricing(product_id))
    items = PriceList.all(
        formula=AND(
            EQUAL(FIELD("currency"), to_airtable_value(currency)),
            EQUAL(FIELD("valid_until"), "BLANK()"),
            OR(
                *[EQUAL(FIELD("sku"), to_airtable_value(sku)) for sku in skus],
            ),
        ),
    )
    return {item.sku: item.unit_pp for item in items}


def get_prices_for_3yc_skus(product_id, currency, start_date, skus):
    prices = {}
    for sku in skus:
        pricelist_item = find_first(
            lambda item: item["currency"] == currency
            and item["valid_from"] <= start_date
            and item["valid_until"] > start_date,
            PRICELIST_CACHE[sku],
        )
        if pricelist_item:
            prices[sku] = pricelist_item["unit_pp"]

    skus_to_lookup = sorted(set(skus) - set(prices.keys()))
    if not skus_to_lookup:
        return prices

    PriceList = get_pricelist_model(AirTableBaseInfo.for_pricing(product_id))

    items = PriceList.all(
        formula=AND(
            EQUAL(FIELD("currency"), to_airtable_value(currency)),
            OR(
                EQUAL(FIELD("valid_until"), "BLANK()"),
                AND(
                    LESS_EQUAL(
                        FIELD("valid_from"), STR_VALUE(to_airtable_value(start_date))
                    ),
                    GREATER(
                        FIELD("valid_until"), STR_VALUE(to_airtable_value(start_date))
                    ),
                ),
            ),
            OR(
                *[
                    EQUAL(FIELD("sku"), to_airtable_value(sku))
                    for sku in skus_to_lookup
                ],
            ),
        ),
        sort=["-valid_until"],
    )
    for item in items:
        if item.valid_until:
            PRICELIST_CACHE[item.sku].append(
                {
                    "currency": item.currency,
                    "valid_from": item.valid_from,
                    "valid_until": item.valid_until,
                    "unit_pp": item.unit_pp,
                },
            )
        if item.sku not in prices:
            prices[item.sku] = item.unit_pp
    return prices
