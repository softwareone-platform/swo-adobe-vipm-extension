import logging

from django.conf import settings
from mpt_extension_sdk.core.utils import setup_client, setup_operations_client
from mpt_extension_sdk.mpt_http.mpt import (
    create_agreement,
    create_agreement_subscription,
    create_asset,
    create_listing,
    get_agreement,
    get_agreement_asset_by_external_id,
    get_agreement_subscription_by_external_id,
    get_authorizations_by_currency_and_seller_id,
    get_gc_price_list_by_currency,
    get_licensee,
    get_listing_by_id,
    get_listings_by_price_list_and_seller_and_authorization,
    get_product_items_by_skus,
    get_product_template_or_default,
    update_agreement,
)

from adobe_vipm.adobe.client import get_adobe_client
from adobe_vipm.adobe.constants import AdobeStatus
from adobe_vipm.adobe.utils import (
    sanitize_company_name,
    sanitize_first_last_name,
)
from adobe_vipm.airtable.models import (
    STATUS_GC_CREATED,
    STATUS_GC_ERROR,
    get_gc_agreement_deployments_to_check,
    get_sku_price,
)
from adobe_vipm.flows.constants import (
    GLOBAL_SUFFIX,
    MARKET_SEGMENT_COMMERCIAL,
    MPT_ORDER_STATUS_COMPLETED,
    TEMPLATE_NAME_TRANSFER,
    Param,
)
from adobe_vipm.flows.utils import (
    get_address,
    get_market_segment,
    get_sku_with_discount_level,
    split_phone_number,
)
from adobe_vipm.utils import get_partial_sku

logger = logging.getLogger(__name__)


# TODO: get function also changes state for agreement deployment :-(
def get_adobe_subscriptions_by_deployment(adobe_client, authorization_id, agreement_deployment):
    """
    Retrieve adobe subscriptions for specific agreement deployment.

    Args:
        adobe_client (AdobeClient): Adobe API client.
        authorization_id (str): Agreement auth id.
        agreement_deployment (AgreementDeployment): agreement deployment.

    Returns:
        list[dict]: List of adobe subscriptions.
    """
    try:
        adobe_subscriptions = adobe_client.get_subscriptions(
            authorization_id, agreement_deployment.customer_id
        )
    except Exception as error:
        logger.exception("Error getting Adobe transfer order.")
        agreement_deployment.status = STATUS_GC_ERROR
        agreement_deployment.error_description = f"Error getting Adobe transfer order: {error}"
        agreement_deployment.save()
        return None

    return [
        item
        for item in adobe_subscriptions["items"]
        if item.get("deploymentId", "") == agreement_deployment.deployment_id
    ]


def get_authorization(mpt_client, agreement_deployment):
    """
    Retrieve authorization ID for the agreement deployment.

    Args:
        mpt_client (MPTClient): The MPT client instance.
        agreement_deployment (AgreementDeployment): The agreement deployment instance.

    Returns:
        str: The authorization ID if found, None otherwise.
    """
    if agreement_deployment.authorization_id:
        return agreement_deployment.authorization_id

    try:
        authorizations = get_authorizations_by_currency_and_seller_id(
            mpt_client,
            agreement_deployment.product_id,
            agreement_deployment.deployment_currency,
            agreement_deployment.seller_id,
        )
    except Exception as error:
        logger.exception("Error getting authorization.")
        agreement_deployment.status = STATUS_GC_ERROR
        agreement_deployment.error_description = f"Error getting authorization: {error}"
        agreement_deployment.save()
        return None

    if not authorizations:
        logger.error(
            "Authorization not found for agreement deployment %s",
            agreement_deployment.deployment_id,
        )
        agreement_deployment.status = STATUS_GC_ERROR
        agreement_deployment.error_description = (
            f"There are no Authorizations for the currency "
            f"'{agreement_deployment.deployment_currency}', "
            f"product '{agreement_deployment.product_id}' and seller '"
            f"{agreement_deployment.seller_id}'"
        )
        agreement_deployment.save()
        return None

    if len(authorizations) > 1:
        authorization_ids = [auth["id"] for auth in authorizations]
        logger.error(
            "More than one authorization found for agreement deployment %s",
            agreement_deployment.deployment_id,
        )
        agreement_deployment.status = STATUS_GC_ERROR
        agreement_deployment.error_description = (
            f"There are more than one Authorizations available for the currency "
            f"'{agreement_deployment.deployment_currency}' "
            f"and seller '{agreement_deployment.seller_id}': {authorization_ids}."
            f"Please update the Authorization column with the selected value"
        )
        agreement_deployment.save()
        return None

    agreement_deployment.authorization_id = authorizations[0]["id"]
    agreement_deployment.save()
    return authorizations[0]["id"]


def get_price_list_id(mpt_client, agreement_deployment):
    """
    Retrieve price list ID for the agreement deployment.

    Args:
        mpt_client (MPTClient): The MPT client instance.
        agreement_deployment (AgreementDeployment): The agreement deployment instance.

    Returns:
        str: The price list ID if found, None otherwise.
    """
    if agreement_deployment.price_list_id:
        return agreement_deployment.price_list_id

    try:
        price_lists = get_gc_price_list_by_currency(
            mpt_client,
            agreement_deployment.product_id,
            agreement_deployment.deployment_currency,
        )
    except Exception as error:
        logger.exception("Error getting price list.")
        agreement_deployment.status = STATUS_GC_ERROR
        agreement_deployment.error_description = f"Error getting price list: {error}"
        agreement_deployment.save()
        return None

    global_price_lists = list(
        filter(
            lambda price_list: price_list.get("externalIds", {})
            .get("vendor", "")
            .endswith(GLOBAL_SUFFIX),
            price_lists,
        )
    )

    if not global_price_lists:
        logger.error(
            "Global price list not found for agreement deployment %s",
            agreement_deployment.deployment_id,
        )
        agreement_deployment.status = STATUS_GC_ERROR
        agreement_deployment.error_description = (
            f"There is no global price list for currency "
            f"'{agreement_deployment.deployment_currency}'. "
            "Please update the price list column with the selected value"
        )
        agreement_deployment.save()
        return None

    if len(global_price_lists) > 1:
        logger.error(
            "More than one price list found for agreement deployment %s",
            agreement_deployment.deployment_id,
        )
        price_list_ids = [price_list["id"] for price_list in price_lists]
        agreement_deployment.status = STATUS_GC_ERROR
        agreement_deployment.error_description = (
            f"There is more than one global price list available for currency "
            f"'{agreement_deployment.deployment_currency}': {price_list_ids}. "
            "Please update the price list column with the selected value"
        )
        agreement_deployment.save()
        return None

    price_list_id = global_price_lists[0]["id"]

    agreement_deployment.price_list_id = price_list_id
    agreement_deployment.save()
    return price_list_id


def get_listing(mpt_client, authorization_id, price_list_id, agreement_deployment):
    """
    Retrieve or create a listing for the agreement deployment.

    Args:
        mpt_client (MPTClient): The MPT client instance.
        authorization_id (str): The authorization ID.
        price_list_id (str): The price list ID.
        agreement_deployment (AgreementDeployment): The agreement deployment instance.

    Returns:
        dict: The listing if found or created, None otherwise.
    """
    if agreement_deployment.listing_id:
        return get_listing_by_id(mpt_client, agreement_deployment.listing_id)

    try:
        listings = get_listings_by_price_list_and_seller_and_authorization(
            mpt_client,
            agreement_deployment.product_id,
            price_list_id,
            agreement_deployment.seller_id,
            authorization_id,
        )
    except Exception as error:
        logger.exception("Error getting listings.")
        agreement_deployment.status = STATUS_GC_ERROR
        agreement_deployment.error_description = f"Error getting listings: {error}"
        agreement_deployment.save()
        return None

    if len(listings) > 1:
        logger.error(
            "More than one listing found for agreement deployment %s",
            agreement_deployment.deployment_id,
        )
        listing_ids = [listing["id"] for listing in listings]
        agreement_deployment.status = STATUS_GC_ERROR
        agreement_deployment.error_description = (
            f"There is more than one listing available for currency "
            f"'{agreement_deployment.deployment_currency}': {listing_ids}. "
            "Please update the listing column with the selected value"
        )
        agreement_deployment.save()
        return None

    if not listings:
        logger.info(
            "Listing not found for agreement deployment %s. Proceed to create new listing",
            agreement_deployment.deployment_id,
        )

        listing = {
            "authorization": {"id": authorization_id},
            "priceList": {"id": price_list_id},
            "product": {"id": agreement_deployment.product_id},
            "seller": {"id": agreement_deployment.seller_id},
            "notes": "",
            "primary": False,
        }
        try:
            listing = create_listing(mpt_client, listing)
            logger.info("New listing created %s", listing["id"])
        except Exception as error:
            logger.exception("Error creating listing: %s", listing)
            agreement_deployment.status = STATUS_GC_ERROR
            agreement_deployment.error_description = f"Error creating listing: {error}"
            agreement_deployment.save()
            return None
    else:
        listing = listings[0]

    agreement_deployment.listing_id = listing["id"]
    agreement_deployment.save()
    return listing


def create_gc_agreement_deployment(
    mpt_o_client,
    agreement_deployment,
    adobe_customer,
    customer_deployment_ids,
    main_agreement,
    listing,
    licensee,
):
    """
    Create a global customer agreement deployment.

    Args:
        mpt_o_client (MPTClient): The MPT Operations client instance.
        agreement_deployment (AgreementDeployment): The agreement deployment instance.
        adobe_customer (dict): The Adobe customer data.
        customer_deployment_ids (list): List of customer deployment IDs.
        main_agreement (dict): Main Agreement representation from MPT API
        listing (dict): The listing data.
        licensee (dict): The licensee data.

    Returns:
        str: The agreement ID if created, None otherwise.
    """
    product_name = listing["product"]["name"]
    vendor_id = listing["vendor"]["id"]
    buyer_id = licensee["buyer"]["id"]
    account_name = licensee["account"]["name"]

    if agreement_deployment.agreement_id:
        return agreement_deployment.agreement_id

    try:
        address = adobe_customer["companyProfile"].get("address", {})
        contact = adobe_customer["companyProfile"]["contacts"][0]
        param_address = get_address(address)

        param_contact = {
            "firstName": sanitize_first_last_name(contact["firstName"]),
            "lastName": sanitize_first_last_name(contact["lastName"]),
            "email": contact["email"],
            "phone": split_phone_number(contact.get("phoneNumber"), address.get("country", "")),
        }

        template = get_product_template_or_default(
            mpt_o_client,
            agreement_deployment.product_id,
            MPT_ORDER_STATUS_COMPLETED,
            TEMPLATE_NAME_TRANSFER,
        )

        ordering_parameters = [
            {"externalId": Param.AGREEMENT_TYPE.value, "value": "Migrate"},
            {
                "externalId": Param.COMPANY_NAME.value,
                "value": sanitize_company_name(adobe_customer["companyProfile"]["companyName"]),
            },
            {"externalId": Param.CONTACT.value, "value": param_contact},
            {
                "externalId": Param.MEMBERSHIP_ID.value,
                "value": agreement_deployment.membership_id,
            },
        ]
        if address:
            ordering_parameters.append({"externalId": Param.ADDRESS.value, "value": param_address})

        fulfillment_parameters = [
            {"externalId": Param.GLOBAL_CUSTOMER.value, "value": ["Yes"]},
            {
                "externalId": Param.DEPLOYMENT_ID.value,
                "value": agreement_deployment.deployment_id,
            },
            {
                "externalId": Param.DEPLOYMENTS.value,
                "value": ",".join(customer_deployment_ids),
            },
            {
                "externalId": Param.CUSTOMER_ID.value,
                "value": agreement_deployment.customer_id,
            },
            {
                "externalId": Param.COTERM_DATE.value,
                "value": adobe_customer["cotermDate"],
            },
        ]

        gc_agreement_deployment = {
            "status": "Active",
            "listing": {"id": agreement_deployment.listing_id},
            "product": {"id": agreement_deployment.product_id},
            "authorization": {"id": agreement_deployment.authorization_id},
            "vendor": {"id": vendor_id},
            "client": {"id": agreement_deployment.account_id},
            "name": f"{product_name} for {account_name} - "
            f"{agreement_deployment.deployment_country}",
            "lines": [],
            "subscriptions": [],
            "parameters": {
                "ordering": ordering_parameters,
                "fulfillment": fulfillment_parameters,
            },
            "licensee": {"id": agreement_deployment.licensee_id},
            "buyer": {"id": buyer_id},
            "seller": {"id": agreement_deployment.seller_id},
            "externalIds": {"vendor": adobe_customer["customerId"]},
            "template": template,
            "termsAndConditions": [],
        }
        agreement = create_agreement(mpt_o_client, gc_agreement_deployment)
        logger.info("Created GC agreement deployment %s", agreement["id"])

        agreement_deployment.agreement_id = agreement["id"]
        agreement_deployment.save()

        return agreement["id"]
    except Exception as error:
        logger.exception("Error creating agreement deployment.")
        agreement_deployment.status = STATUS_GC_ERROR
        agreement_deployment.error_description = f"Error creating agreement deployment: {error}"
        agreement_deployment.save()
        return None


def create_gc_agreement_asset(
    mpt_client, agreement_deployment, adobe_subscription, gc_agreement_id, buyer_id, item, price
):
    """Create a global customer agreement asset.

    Args:
        mpt_client (MPTClient): The MPT client instance.
        agreement_deployment (AgreementDeployment): The agreement deployment instance.
        adobe_subscription (dict): The Adobe subscription data.
        gc_agreement_id (str): The global customer agreement ID.
        buyer_id (str): The buyer ID.
        item (dict): The item data.
        price (float | None): price.
    """
    adobe_subscription_id = adobe_subscription["subscriptionId"]
    logger.info("Creating GC agreement asset for %s", adobe_subscription_id)

    unit_price = {}
    if price is not None:
        unit_price = {"price": {"unitPP": price}}

    asset = {
        "status": "Active",
        "name": f"Asset for {item['name']}",
        "agreement": {"id": gc_agreement_id},
        "parameters": {
            "fulfillment": [
                {
                    "externalId": Param.ADOBE_SKU.value,
                    "value": adobe_subscription["offerId"],
                },
                {
                    "externalId": Param.CURRENT_QUANTITY.value,
                    "value": str(adobe_subscription[Param.CURRENT_QUANTITY]),
                },
                {
                    "externalId": Param.USED_QUANTITY.value,
                    "value": str(adobe_subscription[Param.USED_QUANTITY]),
                },
            ]
        },
        "externalIds": {"vendor": adobe_subscription_id},
        "lines": [
            {
                "quantity": adobe_subscription[Param.CURRENT_QUANTITY.value],
                "item": item,
                **unit_price,
            }
        ],
        "startDate": adobe_subscription["creationDate"],
        "product": {"id": agreement_deployment.product_id},
        "buyer": {"id": buyer_id},
        "licensee": {"id": agreement_deployment.licensee_id},
        "seller": {"id": agreement_deployment.seller_id},
    }
    asset = create_asset(mpt_client, asset)
    logger.info("Created GC agreement asset %s", asset["id"])


def create_gc_agreement_subscription(
    mpt_client, agreement_deployment, adobe_subscription, gc_agreement_id, buyer_id, item, price
):
    """
    Create a global customer agreement subscription.

    Args:
        mpt_client (MPTClient): The MPT client instance.
        agreement_deployment (AgreementDeployment): The agreement deployment instance.
        adobe_subscription (dict): The Adobe subscription data.
        gc_agreement_id (str): The global customer agreement ID.
        buyer_id (str): The buyer ID.
        item (dict): The item data.
        price (float): price.

    Returns:
        None
    """
    logger.info("Creating GC agreement subscription for %s", adobe_subscription["subscriptionId"])

    unit_price = {}
    if price is not None:
        unit_price = {"price": {"unitPP": price}}

    subscription = {
        "status": "Active",
        "name": f"Subscription for {item['name']}",
        "agreement": {"id": gc_agreement_id},
        "parameters": {
            "fulfillment": [
                {"externalId": Param.ADOBE_SKU.value, "value": adobe_subscription["offerId"]},
                {
                    "externalId": Param.CURRENT_QUANTITY.value,
                    "value": str(adobe_subscription[Param.CURRENT_QUANTITY.value]),
                },
                {
                    "externalId": Param.RENEWAL_QUANTITY.value,
                    "value": str(adobe_subscription["autoRenewal"][Param.RENEWAL_QUANTITY.value]),
                },
                {
                    "externalId": Param.RENEWAL_DATE.value,
                    "value": str(adobe_subscription["renewalDate"]),
                },
            ]
        },
        "externalIds": {"vendor": adobe_subscription["subscriptionId"]},
        "lines": [
            {
                "quantity": adobe_subscription[Param.CURRENT_QUANTITY.value],
                "item": item,
                **unit_price,
            }
        ],
        "startDate": adobe_subscription["creationDate"],
        "commitmentDate": adobe_subscription["renewalDate"],
        "autoRenew": adobe_subscription["autoRenewal"]["enabled"],
        "product": {"id": agreement_deployment.product_id},
        "buyer": {"id": buyer_id},
        "licensee": {"id": agreement_deployment.licensee_id},
        "seller": {"id": agreement_deployment.seller_id},
    }
    subscription = create_agreement_subscription(mpt_client, subscription)
    logger.info("Created GC agreement subscription %s", subscription["id"])


def enable_subscription_auto_renewal(
    adobe_client, authorization_id, adobe_customer, adobe_subscription
):
    """
    Enables auto renewal on adobe subscription.

    Args:
        adobe_client (AdobeClient): Adobe API client.
        authorization_id (str): MPT authorization id.
        adobe_customer (dict): The Adobe customer.
        adobe_subscription (dict): Adobe subscription.

    Returns:
        None
    """
    if not adobe_subscription["autoRenewal"]["enabled"]:
        logger.info("Enabling auto-renewal for %s", adobe_subscription["subscriptionId"])
        adobe_subscription = adobe_client.update_subscription(
            authorization_id,
            adobe_customer["customerId"],
            adobe_subscription["subscriptionId"],
            auto_renewal=True,
        )
    return adobe_subscription


def process_agreement_deployment(  # noqa: C901
    mpt_client, mpt_o_client, adobe_client, agreement_deployment, product_id
):
    """
    Process the agreement deployment.

    By retrieving necessary data, creating or updating listings, agreements, and subscriptions.

    Args:
        mpt_client (MPTClient): The MPT client instance.
        mpt_o_client (MPT Client): The MPT client authorized under operations account
        adobe_client (AdobeClient): The Adobe client instance.
        agreement_deployment (AgreementDeployment): The agreement deployment instance.
        product_id (str): The product ID.

    Returns:
        None
    """
    logger.info("Processing agreement deployment %s", agreement_deployment.deployment_id)

    if not agreement_deployment.licensee_id:
        logger.info(
            "Licensee not found for agreement deployment %s. Continue",
            agreement_deployment.deployment_id,
        )
        return

    try:
        authorization_id = get_authorization(mpt_client, agreement_deployment)
        if not authorization_id:
            return
        agreement_deployment.authorization_id = authorization_id

        price_list_id = get_price_list_id(mpt_client, agreement_deployment)
        if not price_list_id:
            return
        agreement_deployment.price_list_id = price_list_id

        listing = get_listing(mpt_o_client, authorization_id, price_list_id, agreement_deployment)
        if not listing:
            return
        agreement_deployment.listing_id = listing["id"]

        licensee = get_licensee(mpt_o_client, agreement_deployment.licensee_id)

        main_agreement = get_agreement(mpt_client, agreement_deployment.main_agreement_id)

        adobe_customer = adobe_client.get_customer(
            authorization_id, agreement_deployment.customer_id
        )
        customer_deployments = adobe_client.get_customer_deployments_active_status(
            authorization_id, agreement_deployment.customer_id
        )
        customer_deployment_ids = [
            f"{deployment['deploymentId']} - {deployment['companyProfile']['address']['country']}"
            for deployment in customer_deployments
        ]

        gc_agreement_id = create_gc_agreement_deployment(
            mpt_o_client,
            agreement_deployment,
            adobe_customer,
            customer_deployment_ids,
            main_agreement,
            listing,
            licensee,
        )
        if not gc_agreement_id:
            return

        update_agreement(
            mpt_client,
            gc_agreement_id,
            externalIds={"vendor": adobe_customer["customerId"]},
        )
        adobe_subscriptions = get_adobe_subscriptions_by_deployment(
            adobe_client, authorization_id, agreement_deployment
        )
        if not adobe_subscriptions:
            return

        process_adobe_subscriptions_from_agreement(
            mpt_client,
            adobe_client,
            adobe_subscriptions,
            adobe_customer,
            gc_agreement_id,
            agreement_deployment,
            licensee["buyer"]["id"],
            product_id,
            authorization_id,
        )

        agreement_deployment.status = STATUS_GC_CREATED
        agreement_deployment.error_description = ""
        agreement_deployment.save()

    except Exception as error:
        logger.exception(
            "Error processing agreement deployment %s.",
            agreement_deployment.deployment_id,
        )
        agreement_deployment.status = STATUS_GC_ERROR
        agreement_deployment.error_description = f"Error processing agreement deployment: {error}"
        agreement_deployment.save()


def process_adobe_subscriptions_from_agreement(
    mpt_client,
    adobe_client,
    adobe_subscriptions,
    adobe_customer,
    gc_agreement_id,
    agreement_deployment,
    buyer_id,
    product_id,
    authorization_id,
):
    """Process Adobe subscriptions from agreement deployment.

    Args:
        mpt_client (MPTClient): The MPT client instance.
        adobe_client (AdobeClient): The Adobe client instance.
        adobe_subscriptions (list): List of Adobe subscriptions to process.
        adobe_customer (dict): The Adobe customer data.
        gc_agreement_id (str): The global customer agreement ID.
        agreement_deployment (AgreementDeployment): The agreement deployment instance.
        buyer_id (str): The buyer ID.
        product_id (str): The product ID.
        authorization_id(str): The authorization ID.

    """
    returned_skus = [get_partial_sku(item["offerId"]) for item in adobe_subscriptions]
    items_map = {
        item["externalIds"]["vendor"]: item
        for item in get_product_items_by_skus(mpt_client, product_id, returned_skus)
    }
    offer_ids = [
        get_sku_with_discount_level(adobe_subscription["offerId"], adobe_customer)
        for adobe_subscription in adobe_subscriptions
    ]
    for adobe_subscription in adobe_subscriptions:
        adobe_subscription_id = adobe_subscription["subscriptionId"]
        if adobe_subscription["status"] != AdobeStatus.PROCESSED:
            logger.warning(
                "Subscription %s is in status %s, skip it",
                adobe_subscription_id,
                adobe_subscription["status"],
            )
            continue

        item = items_map.get(get_partial_sku(adobe_subscription["offerId"]))
        if item["terms"]["model"] == "one-time":
            asset = get_agreement_asset_by_external_id(
                mpt_client, gc_agreement_id, adobe_subscription_id
            )
            if asset:
                logger.info(
                    "Asset with external id %s already exists (%s)",
                    adobe_subscription_id,
                    asset["id"],
                )
            else:
                prices = get_sku_price(
                    adobe_customer, offer_ids, product_id, agreement_deployment.deployment_currency
                )
                sku_discount_level = get_sku_with_discount_level(
                    adobe_subscription["offerId"], adobe_customer
                )
                create_gc_agreement_asset(
                    mpt_client,
                    agreement_deployment,
                    adobe_subscription,
                    gc_agreement_id,
                    buyer_id,
                    item,
                    prices.get(sku_discount_level),
                )
        else:
            subscription = get_agreement_subscription_by_external_id(
                mpt_client, gc_agreement_id, adobe_subscription_id
            )
            if subscription:
                logger.info(
                    "Subscription with external id %s already exists (%s)",
                    adobe_subscription_id,
                    subscription["id"],
                )
            else:
                updated_subscription = enable_subscription_auto_renewal(
                    adobe_client, authorization_id, adobe_customer, adobe_subscription
                )

                prices = get_sku_price(
                    adobe_customer, offer_ids, product_id, agreement_deployment.deployment_currency
                )
                sku_discount_level = get_sku_with_discount_level(
                    updated_subscription["offerId"], adobe_customer
                )

                create_gc_agreement_subscription(
                    mpt_client,
                    agreement_deployment,
                    updated_subscription,
                    gc_agreement_id,
                    buyer_id,
                    item,
                    prices.get(sku_discount_level),
                )
                logger.info(
                    "GC agreement subscription created for %s",
                    updated_subscription["subscriptionId"],
                )


def check_gc_agreement_deployments():
    """
    Check and process Global Customer Agreement Deployments for each product ID.

    Product IDs are defined in the settings.

    This function retrieves the Adobe and MPT clients, iterates over the product IDs,
    and processes each agreement deployment.

    Returns:
        None
    """
    adobe_client = get_adobe_client()
    mpt_client = setup_client()
    mpt_o_client = setup_operations_client()

    for product_id in settings.MPT_PRODUCTS_IDS:
        if get_market_segment(product_id) != MARKET_SEGMENT_COMMERCIAL:
            continue
        logger.info("Checking GC agreement deployments for product %s", product_id)
        try:
            agreement_deployments = get_gc_agreement_deployments_to_check(product_id)
            for agreement_deployment in agreement_deployments:
                process_agreement_deployment(
                    mpt_client,
                    mpt_o_client,
                    adobe_client,
                    agreement_deployment,
                    product_id,
                )
        except Exception:
            logger.exception(
                "Error checking GC agreement deployments for product %s.",
                product_id,
            )
