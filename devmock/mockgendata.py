import copy
import json
import os
import random
from datetime import UTC, datetime

import click
from click import ClickException, Option, UsageError
from faker import Faker

from devmock.utils import (
    cleanup_data_folder,
    generate_random_id,
    get_reference,
    load_agreement,
    load_subscription,
    save_account,
    save_agreement,
    save_buyer,
    save_licensee,
    save_order,
    save_seller,
    save_subscription,
)

GEN_TYPE_TO_ORDER_TYPE = {
    "purchase": "Purchase",
    "upsize": "Change",
    "downsize": "Change",
}


DEFAULT_FIELDS = ["id", "href", "name", "icon"]

ADOBE_CONFIG = json.load(
    open(
        os.path.join(
            os.path.dirname(__file__),
            "..",
            "adobe_vipm",
            "adobe_config.json",
        ),
        "r",
    ),
)


class MutuallyExclusiveOption(Option):
    def __init__(self, *args, **kwargs):
        self.mutually_exclusive = set(kwargs.pop("mutually_exclusive", []))
        help = kwargs.get("help", "")
        if self.mutually_exclusive:
            ex_str = ", ".join(self.mutually_exclusive)
            kwargs["help"] = help + (
                f" NOTE: This option is mutually exclusive with options: [{ex_str}]."
            )
        super(MutuallyExclusiveOption, self).__init__(*args, **kwargs)

    def handle_parse_result(self, ctx, opts, args):
        if self.mutually_exclusive.intersection(opts) and self.name in opts:
            raise UsageError(
                f"Illegal usage: `{self.name}` is mutually exclusive with "
                f"options `{', '.join(self.mutually_exclusive)}`."
            )

        return super(MutuallyExclusiveOption, self).handle_parse_result(ctx, opts, args)


def get_product_by_sku(sku):
    try:
        return next(filter(lambda x: x["product_item_id"] == sku, ADOBE_CONFIG["skus_mapping"]))
    except StopIteration:
        raise Exception(f"Invalid SKU provided: {sku}")


def gen_param(
    name,
    value=None,
    readonly=False,
    hidden=False,
    required=False,
    unique=False,
):
    par_id = generate_random_id("PRM", 16, 4)
    param = {
        "id": par_id,
        "name": name,
        "constraints": {
            "readonly": readonly,
            "hidden": hidden,
            "required": required,
            "unique": unique,
        },
    }
    if value:
        param["value"] = value
    return param


def gen_audit(fake):
    ts = datetime.now(UTC).isoformat()
    user_id = generate_random_id("USR", 8, 4)
    user_name = fake.name()
    return {
        "created": {
            "at": ts,
            "by": {
                "id": user_id,
                "name": user_name,
            },
        },
        "updated": {
            "at": ts,
            "by": {
                "id": user_id,
                "name": user_name,
            },
        },
    }


def gen_contact(fake):
    return {
        "firstName": fake.first_name(),
        "lastName": fake.last_name(),
        "email": fake.email(),
        "phone": f"{fake.country_calling_code()}{fake.msisdn()}",
        "countryCode": fake.country_code(),
    }


def gen_address(fake):
    _, country = fake.locales[0].split("_")
    state = fake.state_abbr()
    postcode = fake.postcode_in_state(state)
    return {
        "addressLine1": fake.street_address(),
        "addressLine2": fake.secondary_address(),
        "postCode": postcode,
        "city": fake.city(),
        "state": state,
        "country": country,
    }


def gen_seller(fake):
    seller_id = generate_random_id("SEL", 8, 4)
    seller = {
        "id": seller_id,
        "name": f"{fake.company()} {fake.company_suffix()}",
        "status": "active",
        "href": f"/v1/accounts/sellers/{seller_id}",
        "icon": f"/static/accounts/{seller_id}/logo.png",
        "address": gen_address(fake),
        "taxes": False,
        "creditLimits": [],
        "buyers": [],
        "audit": gen_audit(fake),
    }
    save_seller(seller)
    return seller


def gen_licensee(fake, buyer, seller):
    lic_id = generate_random_id("LCE", 12, 4)
    licensee = {
        "id": lic_id,
        "name": f"{fake.company()} {fake.company_suffix()}",
        "status": "active",
        "href": f"/v1/accounts/licensees/{lic_id}",
        "icon": f"/static/accounts/{lic_id}/logo.png",
        "useBuyerAddress": False,
        "address": gen_address(fake),
        "contact": gen_contact(fake),
        "audit": gen_audit(fake),
        "account": buyer["account"],
        "buyer": get_reference(buyer),
        "seller": get_reference(seller),
    }
    save_licensee(licensee)
    return licensee


def gen_account(fake, acc_type="Client"):
    acc_id = generate_random_id("ACC", 8, 4)
    account = {
        "id": acc_id,
        "href": f"/v1/accounts/accounts/{acc_id}",
        "name": f"{fake.company()} {fake.company_suffix()}",
        "type": acc_type,
        "status": "Active",
        "icon": f"/static/accounts/{acc_id}/logo.png",
        "address": gen_address(fake),
        "serviceLevel": "Elite",
        "website": fake.url(),
        "technicalSupportEmail": fake.email(),
        "audit": gen_audit(fake),
        "groups": [],
    }
    save_account(account)
    return account


def gen_buyer(fake, client):
    buyer_id = generate_random_id("BUY", 8, 4)
    buyer = {
        "id": buyer_id,
        "name": f"{fake.company()} {fake.company_suffix()}",
        "status": "active",
        "href": f"/v1/accounts/buyers/{buyer_id}",
        "icon": f"/static/accounts/{buyer_id}/logo.png",
        "address": gen_address(fake),
        "taxId": "tax_id",
        "creditLimits": [],
        "sellers": [],
        "audit": gen_audit(fake),
        "contact": gen_contact(fake),
        "account": get_reference(client),
    }
    save_buyer(buyer)
    return buyer


def gen_subscription(item):
    sub_id = generate_random_id("SUB", 16, 4)
    sub = {
        "id": sub_id,
        "href": f"/commerce/subscriptions/{sub_id}",
        "name": f"Subscription for {item['name']}",
        "status": "Updating",
        "startDate": "2023-06-05T19:08:42.3656851+02:00",
        "renewalDate": "2024-07-20T09:50:59.1139069+02:00",
        "terms": {"period": "1m", "commitment": "1y"},
        "price": {
            "margin": 0.01,
            "markup": 0.011,
            "SPxM": 1708.12,
            "SPxY": 20504.00,
            "PPxM": 7.12,
            "PPxY": 88.00,
            "defaultMarkup": 0.15,
            "currency": "USD",
        },
        "items": [item],
    }
    save_subscription(sub)
    return sub


def gen_agreement(fake):
    agr_id = generate_random_id("AGR", 12, 4)
    client = gen_account(fake)
    buyer = gen_buyer(fake, client)
    seller = gen_seller(fake)
    vendor = gen_account(fake, "Vendor")
    licensee = gen_licensee(fake, buyer, seller)
    agreement = {
        "id": agr_id,
        "href": f"/v1/commerce/agreements/{agr_id}",
        "status": "Provisioning",
        "name": f"Adobe VIP MP for {buyer['name']}",
        "vendor": get_reference(vendor),
        "client": get_reference(client),
        "licensee": get_reference(licensee),
        "buyer": get_reference(buyer, DEFAULT_FIELDS),
        "seller": get_reference(seller, DEFAULT_FIELDS),
        "product": {
            "id": "PRD-1111-1111-1111",
            "href": "/catalog/products/PRD-1111-1111-1111",
            "name": "Adobe VIP Marketplace for Commercial",
            "icon": "/static/PRD-1111-1111-1111/logo.png",
        },
        "price": {
            "PPxY": 150,
            "PPxM": 12.50,
            "SPxY": 165,
            "SPxM": 13.75,
            "markup": 0.10,
            "margin": 0.11,
            "currency": "USD",
        },
        "audit": gen_audit(fake),
    }
    save_buyer(buyer)
    save_seller(seller)
    save_agreement(agreement)
    return agreement


def gen_purchase_order(
    fake,
    skus,
    customer_id,
    adobe_order_id,
):
    order_id = generate_random_id("ORD", 16, 4)
    agreement = gen_agreement(fake)
    items = []
    subscriptions = []
    for idx, sku in enumerate(skus, start=1):
        product = get_product_by_sku(sku)
        old_quantity = 0
        quantity = random.randint(1, 5)
        item = {
            "id": f"ITM-1111-1111-1111-{idx:04d}",
            "name": product["name"],
            "quantity": quantity,
            "oldQuantity": old_quantity,
            "lineNumber": idx,
            "productItemId": sku,
        }
        items.append(item)

    order = {
        "id": order_id,
        "type": "Purchase",
        "status": "Processing",
        "agreement": get_reference(agreement, DEFAULT_FIELDS + ["product"]),
        "subscriptions": [get_reference(sub) for sub in subscriptions],
        "items": items,
        "audit": gen_audit(fake),
        "parameters": {
            "order": [
                gen_param("CompanyName"),
                gen_param("PreferredLanguage"),
                gen_param("Address"),
                gen_param("Contact"),
            ],
            "fulfillment": [
                gen_param("RetryCount", "0", hidden=True),
                gen_param("CustomerId", value=customer_id),
            ],
        },
    }
    if adobe_order_id:
        order["externalIDs"] = {
            "vendor": adobe_order_id,
        }
    save_order(order)
    return order


def gen_change_order(fake, agreement_id, skus, change_type):
    order_id = generate_random_id("ORD", 16, 4)
    agreement = load_agreement(agreement_id)
    items = []
    subscriptions = []
    if change_type == "both" and len(agreement.get("subscriptions", [])) < 2:
        raise ClickException(
            "You need at least two subscriptions within the provided "
            "agreement to have both upsizing and downsizing items."
        )

    for line_number, subscription in enumerate(agreement["subscriptions"], start=1):
        sub_data = load_subscription(subscription["id"])
        subscriptions.append(get_reference(sub_data))
        item = sub_data["items"][0]
        new_item = copy.copy(item)
        new_item["oldQuantity"] = item["quantity"]
        if change_type == "upsize":
            rand_prm = (new_item["oldQuantity"] + 1, 9)
        elif change_type == "downsize":
            rand_prm = (1, new_item["oldQuantity"] - 1)
        elif line_number == 1:
            rand_prm = (new_item["oldQuantity"] + 1, 9)
        elif line_number == 2:
            rand_prm = (1, new_item["oldQuantity"] - 1)
        else:
            rand_prm = random.choice(
                [
                    (new_item["oldQuantity"] + 1, 9),
                    (1, new_item["oldQuantity"] - 1),
                ],
            )
        new_item["quantity"] = random.randint(*rand_prm)
        items.append(new_item)
    if skus:
        for idx, sku in enumerate(skus, start=line_number + 1):
            product = get_product_by_sku(sku)
            old_quantity = 0
            quantity = random.randint(1, 5)
            item = {
                "id": f"ITM-1111-1111-1111-{idx:04d}",
                "name": product["name"],
                "quantity": quantity,
                "oldQuantity": old_quantity,
                "lineNumber": idx,
                "productItemId": sku,
            }
            items.append(item)

    order = {
        "id": order_id,
        "type": "Change",
        "status": "Processing",
        "agreement": get_reference(agreement, DEFAULT_FIELDS + ["product"]),
        "items": items,
        "subscriptions": subscriptions,
        "audit": gen_audit(fake),
        "parameters": agreement["parameters"],
    }
    agreement["status"] = "Updating"
    save_agreement(agreement)
    save_order(order)
    return order


@click.group()
def cli():
    pass


@cli.command()
@click.argument("skus", metavar="[SKU ...]", nargs=-1, required=True)
@click.option(
    "--customer-id",
    default=None,
    help=(
        "Preset the Adobe CustomerId fullfilment param to simulate "
        "that the customer has already been created."
    ),
)
@click.option(
    "--order-id",
    default=None,
    help=(
        "Preset the Adobe OrderId (vendor external id of the order) "
        "to simulate that the order has already been created."
    ),
)
@click.option("--locale", default="en_US")
def purchase(customer_id, order_id, locale, skus):
    """
    Generate a purchase order for the provided Adobe (partial) SKUs.
    """
    fake = Faker(locale)
    order = gen_purchase_order(
        fake,
        skus,
        customer_id,
        order_id,
    )
    print(f"Order {order['id']} generated!")


@cli.command()
@click.argument(
    "agreement_id",
    metavar="[AGREEMENT_ID]",
    nargs=1,
    required=True,
)
@click.argument(
    "skus",
    metavar="[SKU ...]",
    nargs=-1,
    required=False,
)
@click.option("--locale", default="en_US")
@click.option(
    "--upsize-only",
    cls=MutuallyExclusiveOption,
    mutually_exclusive=["downsize-only"],
    is_flag=True,
)
@click.option(
    "--downsize-only",
    cls=MutuallyExclusiveOption,
    mutually_exclusive=["upsize-only"],
    is_flag=True,
)
def change(locale, agreement_id, skus, upsize_only, downsize_only):
    """
    Generate a change order for the provided Agreement.
    You can also pass additional (partial) SKUs to buy.
    """
    fake = Faker(locale)
    change_type = "both"
    if upsize_only:
        change_type = "upsize"
    if downsize_only:
        change_type = "downsize"
    order = gen_change_order(fake, agreement_id, skus, change_type)
    click.secho(
        "New 'Change' order has been " f"generated for agreement {agreement_id}: {order['id']}",
        fg="green",
    )


@cli.command()
def cleanup():
    cleanup_data_folder()


def main():
    try:
        cli(standalone_mode=False)
    except Exception as e:
        click.secho(str(e), fg="red")


if __name__ == "__main__":
    main()
