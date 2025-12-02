import datetime as dt
from collections import defaultdict
from dataclasses import dataclass
from functools import cache

from django.conf import settings
from mpt_extension_sdk.mpt_http.utils import find_first
from mpt_extension_sdk.runtime.djapp.conf import get_for_product
from pyairtable.formulas import (
    AND,
    EQUAL,
    FIELD,
    GREATER,
    LESS_EQUAL,
    LOWER,
    NOT_EQUAL,
    OR,
    STR_VALUE,
    to_airtable_value,
)
from pyairtable.orm import Model, fields
from requests import HTTPError

from adobe_vipm.adobe.errors import AdobeProductNotFoundError
from adobe_vipm.utils import get_commitment_start_date

STATUS_INIT = "init"
STATUS_RUNNING = "running"
STATUS_RESCHEDULED = "rescheduled"
STATUS_DUPLICATED = "duplicated"
STATUS_SYNCHRONIZED = "synchronized"
STATUS_GC_CREATED = "created"
STATUS_GC_ERROR = "error"
STATUS_GC_PENDING = "pending"
STATUS_GC_TRANSFERRED = "transferred"
TYPE_3YC_CONSUMABLE = "Consumable"
TYPE_3YC_LICENSE = "License"

PRICELIST_CACHE = defaultdict(list)


@dataclass(frozen=True)
class AirTableBaseInfo:
    """Airtable base info for access information."""

    api_key: str
    base_id: str

    @staticmethod
    def for_migrations(product_id: str):
        """
        Returns an AirTableBaseInfo object with the base identifier of the base.

        That contains the migrations tables and the API key for a given product.

        Args:
            product_id: Identifier of the product.

        Returns:
            AirTableBaseInfo: The base info.
        """
        return AirTableBaseInfo(
            api_key=settings.EXTENSION_CONFIG["AIRTABLE_API_TOKEN"],
            base_id=get_for_product(settings, "AIRTABLE_BASES", product_id),
        )

    @staticmethod
    def for_pricing(product_id: str):
        """
        Returns an AirTableBaseInfo object with the base identifier of the base.

        That contains the pricing tables and the API key for a given product.

        Args:
            product_id: Identifier of the product.

        Returns:
            AirTableBaseInfo: The base info.
        """
        return AirTableBaseInfo(
            api_key=settings.EXTENSION_CONFIG["AIRTABLE_API_TOKEN"],
            base_id=get_for_product(settings, "AIRTABLE_PRICING_BASES", product_id),
        )

    @staticmethod
    def for_sku_mapping():
        """
        Returns an AirTableBaseInfo object with the base identifier of the base.

        That contains the sku mapping table and the API key for a given product.

        Args:
            product_id: Identifier of the product.

        Returns:
            AirTableBaseInfo: The base info.
        """
        return AirTableBaseInfo(
            api_key=settings.EXTENSION_CONFIG["AIRTABLE_API_TOKEN"],
            base_id=settings.EXTENSION_CONFIG["AIRTABLE_SKU_MAPPING_BASE"],
        )


@cache
def get_transfer_model(base_info: AirTableBaseInfo):
    """
    Returns the Transfer model class connected to the right base and with the right API key.

    Args:
        base_info: The base info instance.

    Returns:
        Transfer: The AirTable Transfer model.
    """

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
        customer_address_address_line_1 = fields.TextField("customer_address_address_line_1")
        customer_address_address_line_2 = fields.TextField("customer_address_address_line_2")
        customer_address_city = fields.TextField("customer_address_city")
        customer_address_region = fields.TextField("customer_address_region")
        customer_address_postal_code = fields.TextField("customer_address_postal_code")
        customer_address_country = fields.TextField("customer_address_country")
        customer_address_phone_number = fields.TextField("customer_address_phone_number")
        customer_contact_first_name = fields.TextField("customer_contact_first_name")
        customer_contact_last_name = fields.TextField("customer_contact_last_name")
        customer_contact_email = fields.TextField("customer_contact_email")
        customer_contact_phone_number = fields.TextField("customer_contact_phone_number")
        customer_benefits_3yc_start_date = fields.DateField("customer_benefits_3yc_start_date")
        customer_benefits_3yc_end_date = fields.DateField("customer_benefits_3yc_end_date")
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
def get_gc_main_agreement_model(base_info: AirTableBaseInfo):
    """
    Retrieves the Global Customer (gc) main agreement model based on the provided base information.

    This method returns the GCMainAgreement model class connected to the right base and with the
    right API key.

    Args:
        base_info: The base info instance.

    Returns:
        GCMainAgreement: The AirTable GCMainAgreement model.
    """

    class GCMainAgreement(Model):
        membership_id = fields.TextField("membership_id")
        authorization_uk = fields.TextField("authorization_uk")
        main_agreement_id = fields.TextField("main_agreement_id")
        transfer_id = fields.TextField("transfer_id")
        customer_id = fields.TextField("customer_id")
        status = fields.SelectField("status")
        error_description = fields.TextField("error_description")
        created_at = fields.DatetimeField("created_at", readonly=True)
        updated_at = fields.DatetimeField("updated_at", readonly=True)
        created_by = fields.TextField("created_by", readonly=True)
        updated_by = fields.TextField("updated_by", readonly=True)

        class Meta:
            table_name = "Global Customer Main Agreements"
            api_key = base_info.api_key
            base_id = base_info.base_id

    return GCMainAgreement


@cache
def get_gc_agreement_deployment_model(base_info: AirTableBaseInfo):
    """
    Retrieves the Global Customer agreement deployment model.

    This method returns the GCAgreementDeployments model class connected to the right base
    and with the right API key.

    Args:
        base_info: The base info instance.

    Returns:
        GCAgreementDeployments: The AirTable GCAgreementDeployments (Global Customer Agreement
        Deployments) model.
    """

    class GCAgreementDeployment(Model):
        deployment_id = fields.TextField("deployment_id")
        main_agreement_id = fields.TextField("main_agreement_id")
        account_id = fields.TextField("account_id")
        seller_id = fields.TextField("seller_id")
        product_id = fields.TextField("product_id")
        membership_id = fields.TextField("membership_id")
        transfer_id = fields.TextField("transfer_id")
        status = fields.SelectField("status")
        customer_id = fields.TextField("customer_id")
        deployment_currency = fields.TextField("deployment_currency")
        deployment_country = fields.TextField("deployment_country")
        licensee_id = fields.TextField("licensee_id")
        agreement_id = fields.TextField("agreement_id")
        authorization_id = fields.TextField("authorization_id")
        price_list_id = fields.TextField("price_list_id")
        listing_id = fields.TextField("listing_id")
        error_description = fields.TextField("error_description")
        created_at = fields.DatetimeField("created_at", readonly=True)
        updated_at = fields.DatetimeField("updated_at", readonly=True)
        created_by = fields.TextField("created_by", readonly=True)
        updated_by = fields.TextField("updated_by", readonly=True)

        class Meta:
            table_name = "Global Customer Agreement Deployments"
            api_key = base_info.api_key
            base_id = base_info.base_id

    return GCAgreementDeployment


@cache
def get_offer_model(base_info: AirTableBaseInfo):
    """
    Returns the Offer model class connected to the right base and with the right API key.

    Args:
        base_info: The base info instance.

    Returns:
        Offer: The AirTable Offer model.
    """
    transfer_model = get_transfer_model(base_info)

    class Offer(Model):
        transfer = fields.LinkField("membership_id", transfer_model, lazy=True)
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


def get_offer_ids_by_membership_id(product_id: str, membership_id: str) -> list[str]:
    """
    Returns a list of SKUs associated with a given membership_id.

    Args:
        product_id: The ID of the product to which the membership refers to.
        membership_id: The membership ID used to retrieve the list of SKUs.

    Returns:
        list: List of SKUs that belong to the given membership.
    """
    offer_model = get_offer_model(AirTableBaseInfo.for_migrations(product_id))
    formula = EQUAL(FIELD("membership_id"), STR_VALUE(membership_id))

    return [offer.offer_id for offer in offer_model.all(formula=formula)]


def create_offers(product_id: str, offers: list):
    """
    Creates a list of Offer objects in batch.

    Args:
        product_id: The ID of the product used to determine the AirTable base.
        offers: List of Offer objects to create.
    """
    offer_model = get_offer_model(AirTableBaseInfo.for_migrations(product_id))
    offer_model.batch_save([offer_model(**offer) for offer in offers])


def get_transfers_to_process(product_id: str):
    """
    Get a list of transfers that must be submitted to Adobe.

    Args:
        product_id: The ID of the product used to determine the AirTable base.

    Returns:
        list: List of Transfer objects.
    """
    transfer_model = get_transfer_model(AirTableBaseInfo.for_migrations(product_id))
    return transfer_model.all(
        formula=OR(
            EQUAL(FIELD("status"), STR_VALUE(STATUS_INIT)),
            EQUAL(FIELD("status"), STR_VALUE(STATUS_RESCHEDULED)),
        ),
    )


def get_transfers_to_check(product_id: str):
    """
    Returns a list of transfers currently in running state.

    Args:
        product_id: The ID of the product used to determine the AirTable base.

    Returns:
        list: List of running transfers.
    """
    transfer_model = get_transfer_model(AirTableBaseInfo.for_migrations(product_id))
    return transfer_model.all(
        formula=EQUAL(FIELD("status"), STR_VALUE(STATUS_RUNNING)),
    )


def get_transfer_by_authorization_membership_or_customer(
    product_id: str, authorization_uk: str, membership_or_customer_id: str
):
    """
    Retrieve a Transfer object.

    Given the authorization ID and the membership ID or the customer ID.

    Args:
        product_id: The ID of the product used to determine the AirTable base.
        authorization_uk: The ID of the authorization.
        membership_or_customer_id: Either a membership ID or a customer ID.

    Returns:
        Transfer: The Transfer if it has been found, None otherwise.
    """
    transfer_model = get_transfer_model(AirTableBaseInfo.for_migrations(product_id))
    transfers = transfer_model.all(
        formula=AND(
            EQUAL(FIELD("authorization_uk"), STR_VALUE(authorization_uk)),
            OR(
                EQUAL(
                    LOWER(FIELD("membership_id")),
                    LOWER(STR_VALUE(membership_or_customer_id)),
                ),
                EQUAL(FIELD("customer_id"), STR_VALUE(membership_or_customer_id)),
            ),
            NOT_EQUAL(FIELD("status"), STR_VALUE(STATUS_DUPLICATED)),
        ),
    )

    return transfers[0] if transfers else None


def get_transfer_link(transfer) -> str:
    """
    Generate a link to a record of the Transfer table in the AirTable UI.

    Args:
        transfer (Transfer): The Transfer object for which the link must be generated.

    Returns:
        str: The link to the transfer record or None in case of an error.
    """
    try:
        base_id = transfer.Meta.base_id
        table_id = transfer.get_table().id
        view_id = transfer.get_table().schema().view("Transfer View").id
        record_id = transfer.id
    except HTTPError:
        return None

    return f"https://airtable.com/{base_id}/{table_id}/{view_id}/{record_id}"


@cache
def get_pricelist_model(base_info: AirTableBaseInfo):
    """
    Returns the PriceList model class connected to the right base and with the right API key.

    Args:
        base_info: The base info instance.

    Returns:
        PriceList: The AirTable PriceList model.
    """

    class PriceList(Model):
        record_id = fields.TextField("id", readonly=True)
        sku = fields.TextField("sku")
        partial_sku = fields.TextField("partial_sku", readonly=True)
        item_name = fields.TextField("item_name")
        discount_level = fields.TextField("discount_level", readonly=True)
        valid_from = fields.DateField("valid_from")
        valid_until = fields.DateField("valid_until")
        currency = fields.SelectField("currency")
        # TODO: should be decimal
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


def get_prices_for_skus(product_id: str, currency: str, skus: list[str]) -> dict:
    """
    Given a currency and a list of SKUs it retrieves the purchase price.

    For each SKU in the given currency.

    Args:
        product_id: The ID of the product used to determine the AirTable base.
        currency: The currency for which the price must be retrieved.
        skus: List of SKUs which purchase prices must be retrieved.

    Returns:
        dict: A dictionary with SKU, purchase price items.
    """
    pricelist_model = get_pricelist_model(AirTableBaseInfo.for_pricing(product_id))
    items = pricelist_model.all(
        formula=AND(
            EQUAL(FIELD("currency"), to_airtable_value(currency)),
            EQUAL(FIELD("valid_until"), "BLANK()"),
            OR(
                *[EQUAL(FIELD("sku"), to_airtable_value(sku)) for sku in skus],
            ),
        ),
    )
    return {item.sku: item.unit_pp for item in items}


def get_skus_with_available_prices(product_id: str, currency: str, skus: list[str]) -> set:
    """
    Given a currency and a list of SKUs it retrieves the skus if the price is available.

    Args:
        product_id: The ID of the product used to determine the AirTable base.
        currency: The currency for which the skus must be retrieved.
        skus: List of SKUs which skus must be retrieved.

    Returns:
        set: A set of SKUs if the price is available.
    """
    pricelist_model = get_pricelist_model(AirTableBaseInfo.for_pricing(product_id))
    items = pricelist_model.all(
        formula=AND(
            EQUAL(FIELD("currency"), to_airtable_value(currency)),
            EQUAL(FIELD("valid_until"), "BLANK()"),
            OR(
                *[EQUAL(FIELD("partial_sku"), to_airtable_value(sku)) for sku in skus],
            ),
        ),
    )
    return {item.partial_sku for item in items}


def get_prices_for_3yc_skus(  # noqa: C901
    product_id: str, currency: str, start_date: dt.date, skus: list[str]
) -> dict:
    """
    Given a currency and a list of SKUs and the 3YC start date it retrieves the purchase price.

    For each SKU in the given currency from the pricelist that was valid
    when the 3YC started.
    Such prices are cached since they will not change ever to reduce the amount of API calls
    to the AirTable API.

    Args:
        product_id: The ID of the product used to determine the AirTable base.
        currency: The currency for which the price must be retrieved.
        start_date: The date in which the 3YC started.
        skus: List of SKUs which purchase prices must be retrieved.

    Returns:
        dict: A dictionary with SKU, purchase price items.
    """
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

    pricelist_model = get_pricelist_model(AirTableBaseInfo.for_pricing(product_id))

    items = pricelist_model.all(
        formula=AND(
            EQUAL(FIELD("currency"), to_airtable_value(currency)),
            OR(
                EQUAL(FIELD("valid_until"), "BLANK()"),
                AND(
                    LESS_EQUAL(FIELD("valid_from"), STR_VALUE(to_airtable_value(start_date))),
                    GREATER(FIELD("valid_until"), STR_VALUE(to_airtable_value(start_date))),
                ),
            ),
            OR(
                *[EQUAL(FIELD("sku"), to_airtable_value(sku)) for sku in skus_to_lookup],
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


def get_sku_price(
    adobe_customer: dict, offer_ids: list[str], product_id: str, deployment_currency: str
) -> dict[str, float]:
    """
    Get the SKU price considering the level discount and the 3YC commitment.

    Args:
        adobe_customer: Adobe customer
        offer_ids: List of Adobe offer ids
        product_id: ID of the product
        deployment_currency: deployment currency

    Returns:
        dict: Sku price if is available, empty dict otherwise.
    """
    commitment_start_date = get_commitment_start_date(adobe_customer)

    if commitment_start_date:
        prices = get_prices_for_3yc_skus(
            product_id, deployment_currency, commitment_start_date, offer_ids
        )
    else:
        prices = get_prices_for_skus(product_id, deployment_currency, offer_ids)
    return prices or {}


def create_gc_agreement_deployments(product_id: str, agreement_deployments: list):
    """
    Add a new Global Customer (GC) agreement deployments on Airtable for a given product.

    This method creates a list of GCAgreementDeployment objects on Airtable in batch.

    Args:
        product_id: The ID of the product used to determine the AirTable base.
        agreement_deployments: List of GCAgreementDeployment object to create.
    """
    gc_agreement_deployment_model = get_gc_agreement_deployment_model(
        AirTableBaseInfo.for_migrations(product_id)
    )
    gc_agreement_deployment_model.batch_save([
        gc_agreement_deployment_model(**agreement_deployment)
        for agreement_deployment in agreement_deployments
    ])


def create_gc_main_agreement(product_id: str, main_agreement: dict):
    """
    Add a new Global Customer (GC) main agreement on Airtable for a given product.

    This method creates a GCMainAgreement object on Airtable.

    Args:
        product_id: The ID of the product used to determine the AirTable base.
        main_agreement: The main agreement object to create.
    """
    gc_main_agreement_model = get_gc_main_agreement_model(
        AirTableBaseInfo.for_migrations(product_id),
    )
    gc_main_agreement_model(**main_agreement).save()


def get_gc_main_agreement(product_id: str, authorization_uk: str, membership_or_customer_id: str):
    """
    Retrieves the Global Customer (gc) main agreement for a given product.

    This retrieve a GCMainAgreement object associated with the specified
    product, using the provided authorization and membership or customer ID.

    Args:
        product_id: The ID of the product used to determine the AirTable base.
        authorization_uk: The ID of the authorization.
        membership_or_customer_id: Either a membership ID or a customer ID.

    Returns:
        GCMainAgreement: The GCMainOrder if it has been found,
        None otherwise.
    """
    gc_main_agreement_model = get_gc_main_agreement_model(
        AirTableBaseInfo.for_migrations(product_id),
    )
    gc_main_agreements = gc_main_agreement_model.all(
        formula=AND(
            EQUAL(FIELD("authorization_uk"), STR_VALUE(authorization_uk)),
            OR(
                EQUAL(FIELD("membership_id"), STR_VALUE(membership_or_customer_id)),
                EQUAL(FIELD("customer_id"), STR_VALUE(membership_or_customer_id)),
            ),
        ),
    )
    return gc_main_agreements[0] if gc_main_agreements else None


def get_gc_agreement_deployments_by_main_agreement(product_id: str, main_agreement_id: str):
    """
    Retrieves Global Customer (gc) agreement deployments associated with a specific main agreement.

    This method retrieve the list of GCAgreementDeployment objects linked to the specified
    main agreement ID for the given product.

    Args:
        product_id: The ID of the product used to determine the AirTable base.
        main_agreement_id: The ID of the main agreement.

    Returns:
        GCAgreementDeployment: The list of GCAgreementDeployment
    """
    gc_agreement_deployment_model = get_gc_agreement_deployment_model(
        AirTableBaseInfo.for_migrations(product_id)
    )
    return gc_agreement_deployment_model.all(
        formula=AND(
            EQUAL(FIELD("main_agreement_id"), STR_VALUE(main_agreement_id)),
        ),
    )


def get_gc_agreement_deployments_to_check(product_id: str):
    """
    Retrieves Global Customer (gc) agreement deployments that require verification or review.

    This method retrieve the list of GCAgreementDeployment objects associated with the
    specified product that are in pending or error state

    Args:
        product_id: The ID of the product used to determine the AirTable base.

    Returns:
        GCAgreementDeployment: The list of GCAgreementDeployment
    """
    gc_agreement_deployment_model = get_gc_agreement_deployment_model(
        AirTableBaseInfo.for_migrations(product_id)
    )
    return gc_agreement_deployment_model.all(
        formula=OR(
            EQUAL(FIELD("status"), STR_VALUE(STATUS_GC_PENDING)),
            EQUAL(FIELD("status"), STR_VALUE(STATUS_GC_ERROR)),
        ),
    )


def get_agreement_deployment_view_link(product_id: str) -> str | None:
    """
    Generate a link to a record of the Agreement Deployments table in the AirTable UI.

    Args:
        product_id: The ID of the product used to determine the AirTable base.

    Returns:
        str | None: The link to the agreement deployments record or None in case of an error.
    """
    try:
        gc_agreement_deployment_model = get_gc_agreement_deployment_model(
            AirTableBaseInfo.for_migrations(product_id)
        )
        base_id = gc_agreement_deployment_model.Meta.base_id
        table_id = gc_agreement_deployment_model.get_table().id
        view_id = (
            gc_agreement_deployment_model.get_table()
            .schema()
            .view(
                "Agreement Deployments View",
            )
            .id
        )
        record_id = gc_agreement_deployment_model.id
    except HTTPError:
        return None

    return f"https://airtable.com/{base_id}/{table_id}/{view_id}/{record_id}"


@cache
def get_sku_adobe_mapping_model(base_info: AirTableBaseInfo):
    """
    Returns the AdobeProductMapping model class connected to the right base.

    Args:
        base_info: The base info instance.

    Returns:
        AdobeProductMapping: The AirTable AdobeProductMapping model.
    """

    class AdobeProductMapping(Model):
        vendor_external_id = fields.TextField("vendor_external_id")
        sku = fields.TextField("sku")
        segment = fields.SelectField("segment")
        name = fields.TextField("name")
        type_3yc = fields.SelectField("type_3yc")

        class Meta:
            table_name = "SKU Mapping"
            api_key = base_info.api_key
            base_id = base_info.base_id

        @classmethod
        def from_short_id(cls, vendor_external_id: str):
            """
            Returns the AdobeProductMapping entity for the cutted Adobe SKU.

            Args:
                vendor_external_id: cutted Adobe SKU.

            Returns:
                AdobeProductMapping: entity of the AdobeProductMapping.
            """
            entity = cls.first(
                formula=EQUAL(FIELD("vendor_external_id"), STR_VALUE(vendor_external_id))
            )
            if entity is None:
                raise AdobeProductNotFoundError(
                    f"AdobeProduct with vendor_external_id `{vendor_external_id}` not found."
                )

            return entity

        def is_consumable(self) -> bool:
            """Check if the SKU is a consumable."""
            return self.type_3yc == TYPE_3YC_CONSUMABLE

        def is_license(self) -> bool:
            """Check if the SKU is a license."""
            return self.type_3yc == TYPE_3YC_LICENSE

        def is_valid_3yc_type(self) -> bool:
            """Check if the SKU is a valid 3YC type."""
            return self.is_consumable() or self.is_license()

    return AdobeProductMapping


def get_adobe_product_by_marketplace_sku(vendor_external_id: str):
    """
    Get an AdobeProductMapping object by the vendor_external_id.

    Args:
        vendor_external_id: The vendor external id to search for the AdobeProductMapping.

    Raises:
        AdobeProductNotFoundError: If no AdobeProductMapping exists for the given
        vendor external id.
    """
    adobe_item_model = get_sku_adobe_mapping_model(AirTableBaseInfo.for_sku_mapping())
    return adobe_item_model.from_short_id(vendor_external_id)


@cache
def get_adobe_sku(vendor_item_id: str) -> str:
    """
    Retrieves full sku with first discount level based on cutted Adobe SKU.

    Uses AdobeProductMapping table

    Args:
        vendor_item_id: cutted Adobe SKU.

    Returns:
        str: full sku with first discount level.
    """
    return get_adobe_product_by_marketplace_sku(vendor_item_id).sku
