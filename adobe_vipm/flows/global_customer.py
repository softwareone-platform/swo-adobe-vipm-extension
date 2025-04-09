import logging

from django.conf import settings
from mpt_extension_sdk.core.utils import setup_client, setup_operations_client
from mpt_extension_sdk.mpt_http.mpt import (
    create_agreement,
    create_agreement_subscription,
    create_listing,
    get_agreement,
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
from adobe_vipm.adobe.constants import STATUS_PROCESSED, STATUS_GC_DEPLOYMENT_ACTIVE
from adobe_vipm.adobe.utils import sanitize_company_name, sanitize_first_last_name
from adobe_vipm.airtable.models import (
    STATUS_GC_CREATED,
    STATUS_GC_ERROR,
    get_gc_agreement_deployments_to_check,
)
from adobe_vipm.flows.constants import (
    GLOBAL_SUFFIX,
    MARKET_SEGMENT_COMMERCIAL,
    MPT_ORDER_STATUS_COMPLETED,
    PARAM_ADDRESS,
    PARAM_ADOBE_SKU,
    PARAM_AGREEMENT_TYPE,
    PARAM_COMPANY_NAME,
    PARAM_CONTACT,
    PARAM_COTERM_DATE,
    PARAM_CURRENT_QUANTITY,
    PARAM_CUSTOMER_ID,
    PARAM_DEPLOYMENT_ID,
    PARAM_DEPLOYMENTS,
    PARAM_GLOBAL_CUSTOMER,
    PARAM_MEMBERSHIP_ID,
    PARAM_RENEWAL_DATE,
    PARAM_RENEWAL_QUANTITY,
    TEMPLATE_NAME_TRANSFER
)
from adobe_vipm.flows.utils import (
    get_market_segment,
    split_phone_number,
)
from adobe_vipm.utils import get_partial_sku

logger = logging.getLogger(__name__)


def get_adobe_subscriptions_by_deployment(
    adobe_client, authorization_id, agreement_deployment
):
    try:
        adobe_subscriptions = adobe_client.get_subscriptions(
            authorization_id, agreement_deployment.customer_id
        )
    except Exception as e:
        logger.exception(f"Error getting Adobe transfer order: {e}")
        agreement_deployment.status = STATUS_GC_ERROR
        agreement_deployment.error_description = (
            f"Error getting Adobe transfer order: {e}"
        )
        agreement_deployment.save()
        return None

    deployment_adobe_subscriptions = [
        item
        for item in adobe_subscriptions["items"]
        if item.get("deploymentId", "") == agreement_deployment.deployment_id
    ]
    return deployment_adobe_subscriptions


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
    except Exception as e:
        logger.exception(f"Error getting authorization: {e}")
        agreement_deployment.status = STATUS_GC_ERROR
        agreement_deployment.error_description = f"Error getting authorization: {e}"
        agreement_deployment.save()
        return None

    if not authorizations:
        logger.exception(
            f"Authorization not found for agreement deployment "
            f"{agreement_deployment.deployment_id}"
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
        logger.exception(
            f"More than one authorization found for agreement deployment "
            f"{agreement_deployment.deployment_id}"
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
    except Exception as e:
        logger.exception(f"Error getting price list: {e}")
        agreement_deployment.status = STATUS_GC_ERROR
        agreement_deployment.error_description = f"Error getting price list: {e}"
        agreement_deployment.save()
        return None

    global_price_lists = []
    for price_list in price_lists:
        if price_list.get("externalIds", {}).get("vendor", "").endswith(GLOBAL_SUFFIX):
            global_price_lists.append(price_list)

    if not global_price_lists:
        logger.exception(
            f"Global price list not found for agreement deployment"
            f" {agreement_deployment.deployment_id}"
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
        logger.exception(
            f"More than one price list found for agreement deployment "
            f"{agreement_deployment.deployment_id}"
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
    except Exception as e:
        logger.exception(f"Error getting listings: {e}")
        agreement_deployment.status = STATUS_GC_ERROR
        agreement_deployment.error_description = f"Error getting listings: {e}"
        agreement_deployment.save()
        return None

    if len(listings) > 1:
        logger.exception(
            f"More than one listing found for agreement deployment "
            f"{agreement_deployment.deployment_id}"
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
            f"Listing not found for agreement deployment {agreement_deployment.deployment_id}."
            f" Proceed to create new listing"
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
            logger.info(f"New listing created {listing['id']}")
        except Exception as e:
            logger.exception(f"Error creating listing: {e}: {listing}")
            agreement_deployment.status = STATUS_GC_ERROR
            agreement_deployment.error_description = f"Error creating listing: {e}"
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
        address = adobe_customer["companyProfile"]["address"]
        contact = adobe_customer["companyProfile"]["contacts"][0]
        param_address = {
            "country": address["country"],
            "state": address["region"],
            "city": address["city"],
            "addressLine1": address["addressLine1"],
            "addressLine2": address["addressLine2"],
            "postCode": address["postalCode"],
        }

        param_contact = {
            "firstName": sanitize_first_last_name(contact["firstName"]),
            "lastName": sanitize_first_last_name(contact["lastName"]),
            "email": contact["email"],
            "phone": split_phone_number(contact.get("phoneNumber"), address["country"]),
        }

        template = get_product_template_or_default(
            mpt_o_client,
            agreement_deployment.product_id,
            MPT_ORDER_STATUS_COMPLETED,
            TEMPLATE_NAME_TRANSFER,
        )

        ordering_parameters = [
            {"externalId": PARAM_AGREEMENT_TYPE, "value": "Migrate"},
            {
                "externalId": PARAM_COMPANY_NAME,
                "value": sanitize_company_name(
                    adobe_customer["companyProfile"]["companyName"]
                ),
            },
            {"externalId": PARAM_ADDRESS, "value": param_address},
            {"externalId": PARAM_CONTACT, "value": param_contact},
            {
                "externalId": PARAM_MEMBERSHIP_ID,
                "value": agreement_deployment.membership_id,
            },
        ]
        fulfillment_parameters = [
            {"externalId": PARAM_GLOBAL_CUSTOMER, "value": ["Yes"]},
            {
                "externalId": PARAM_DEPLOYMENT_ID,
                "value": agreement_deployment.deployment_id,
            },
            {
                "externalId": PARAM_DEPLOYMENTS,
                "value": ",".join(customer_deployment_ids),
            },
            {
                "externalId": PARAM_CUSTOMER_ID,
                "value": agreement_deployment.customer_id,
            },
            {
                "externalId": PARAM_COTERM_DATE,
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
        logger.info(f"Created GC agreement deployment {agreement['id']}")

        agreement_deployment.agreement_id = agreement["id"]
        agreement_deployment.save()

        return agreement["id"]
    except Exception as e:
        logger.exception(f"Error creating agreement deployment: {e}")
        agreement_deployment.status = STATUS_GC_ERROR
        agreement_deployment.error_description = (
            f"Error creating agreement deployment: {e}"
        )
        agreement_deployment.save()
        return None


def create_gc_agreement_subscription(
    mpt_client,
    agreement_deployment,
    adobe_subscription,
    gc_agreement_id,
    buyer_id,
    item,
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

    Returns:
        None
    """
    logger.info(
        f"Creating GC agreement subscription for {adobe_subscription['subscriptionId']}"
    )
    subscription = {
        "status": "Active",
        "name": f"Subscription for {item['name']}",
        "agreement": {"id": gc_agreement_id},
        "parameters": {
            "fulfillment": [
                {"externalId": PARAM_ADOBE_SKU, "value": adobe_subscription["offerId"]},
                {
                    "externalId": PARAM_CURRENT_QUANTITY,
                    "value": str(adobe_subscription["currentQuantity"]),
                },
                {
                    "externalId": PARAM_RENEWAL_QUANTITY,
                    "value": str(adobe_subscription["autoRenewal"]["renewalQuantity"]),
                },
                {
                    "externalId": PARAM_RENEWAL_DATE,
                    "value": str(adobe_subscription["renewalDate"]),
                },
            ]
        },
        "externalIds": {"vendor": adobe_subscription["subscriptionId"]},
        "lines": [{"quantity": adobe_subscription["currentQuantity"], "item": item}],
        "startDate": adobe_subscription["creationDate"],
        "commitmentDate": adobe_subscription["renewalDate"],
        "autoRenew": adobe_subscription["autoRenewal"]["enabled"],
        "product": {"id": agreement_deployment.product_id},
        "buyer": {"id": buyer_id},
        "licensee": {"id": agreement_deployment.licensee_id},
        "seller": {"id": agreement_deployment.seller_id},
    }
    subscription = create_agreement_subscription(mpt_client, subscription)
    logger.info(f"Created GC agreement subscription {subscription['id']}")


def enable_subscription_auto_renewal(
    adobe_client, authorization_id, adobe_customer, adobe_subscription
):
    if not adobe_subscription["autoRenewal"]["enabled"]:
        logger.info(f"Enabling auto-renewal for {adobe_subscription['subscriptionId']}")
        adobe_subscription = adobe_client.update_subscription(
            authorization_id,
            adobe_customer["customerId"],
            adobe_subscription["subscriptionId"],
            auto_renewal=True,
        )
    return adobe_subscription


def process_agreement_deployment(
    mpt_client, mpt_o_client, adobe_client, agreement_deployment, product_id
):
    """
    Process the agreement deployment by retrieving necessary data, creating or updating
    listings, agreements, and subscriptions.

    Args:
        mpt_client (MPTClient): The MPT client instance.
        mpt_o_client (MPT Client): The MPT client authorized under operations account
        adobe_client (AdobeClient): The Adobe client instance.
        agreement_deployment (AgreementDeployment): The agreement deployment instance.
        product_id (str): The product ID.

    Returns:
        None
    """
    logger.info(f"Processing agreement deployment {agreement_deployment.deployment_id}")

    if not agreement_deployment.licensee_id:
        logger.info(
            f"Licensee not found for agreement deployment {agreement_deployment.deployment_id}."
            f" Continue"
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

        listing = get_listing(
            mpt_o_client, authorization_id, price_list_id, agreement_deployment
        )
        if not listing:
            return
        agreement_deployment.listing_id = listing["id"]

        licensee = get_licensee(mpt_o_client, agreement_deployment.licensee_id)

        main_agreement = get_agreement(
            mpt_client, agreement_deployment.main_agreement_id
        )

        adobe_customer = adobe_client.get_customer(
            authorization_id, agreement_deployment.customer_id
        )
        customer_deployments = adobe_client.get_customer_deployments_by_status(
            authorization_id, agreement_deployment.customer_id
        )

        customer_deployment_ids = [
            f'{deployment["deploymentId"]} - {deployment["companyProfile"]["address"]["country"]}'
            for deployment in customer_deployments["items"]
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
        returned_skus = [
            get_partial_sku(item["offerId"]) for item in adobe_subscriptions
        ]

        items_map = {
            item["externalIds"]["vendor"]: item
            for item in get_product_items_by_skus(mpt_client, product_id, returned_skus)
        }

        for adobe_subscription in adobe_subscriptions:
            if adobe_subscription["status"] != STATUS_PROCESSED:
                logger.warning(
                    f"Subscription {adobe_subscription['subscriptionId']} "
                    f"is in status {adobe_subscription['status']}, skip it"
                )
                continue

            item = items_map.get(get_partial_sku(adobe_subscription["offerId"]))
            subscription = get_agreement_subscription_by_external_id(
                mpt_client, gc_agreement_id, adobe_subscription["subscriptionId"]
            )
            if subscription:
                logger.info(
                    f"Subscription with external id {adobe_subscription['subscriptionId']} already"
                    f" exists ({subscription['id']})"
                )
            else:
                adobe_subscription = enable_subscription_auto_renewal(
                    adobe_client, authorization_id, adobe_customer, adobe_subscription
                )
                create_gc_agreement_subscription(
                    mpt_client,
                    agreement_deployment,
                    adobe_subscription,
                    gc_agreement_id,
                    licensee["buyer"]["id"],
                    item,
                )
                logger.info(
                    f"GC agreement subscription created for {adobe_subscription['subscriptionId']}"
                )

        agreement_deployment.status = STATUS_GC_CREATED
        agreement_deployment.error_description = ""
        agreement_deployment.save()

    except Exception as e:
        logger.exception(
            f"Error processing agreement deployment {agreement_deployment.deployment_id}: {e}"
        )
        agreement_deployment.status = STATUS_GC_ERROR
        agreement_deployment.error_description = (
            f"Error processing agreement deployment: {e}"
        )
        agreement_deployment.save()


def check_gc_agreement_deployments():
    """
    Check and process Global Customer Agreement Deployments for each product ID
    defined in the settings.

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
        logger.info(f"Checking GC agreement deployments for product {product_id}")
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
        except Exception as e:
            logger.exception(
                f"Error checking GC agreement deployments for product {product_id}: {e}"
            )
