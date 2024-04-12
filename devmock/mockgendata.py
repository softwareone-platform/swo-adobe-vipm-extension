import copy
import json
import os
import random
from datetime import UTC, datetime
from functools import partial

import click
from click import Abort, ClickException, Option, UsageError
from faker import Faker
from rich import box
from rich.console import Console
from rich.highlighter import ReprHighlighter as _ReprHighlighter
from rich.table import Table
from rich.theme import Theme

from devmock.exceptions import NotFoundException
from devmock.utils import (
    base_id_from,
    cleanup_data_folder,
    generate_random_id,
    get_reference,
    load_account,
    load_authorization,
    load_agreement,
    load_item,
    load_listing,
    load_pricelist_item,
    load_product,
    load_seller,
    load_subscription,
    save_account,
    save_agreement,
    save_authorization,
    save_buyer,
    save_item,
    save_licensee,
    save_listing,
    save_order,
    save_pricelist,
    save_pricelist_item,
    save_product,
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


class ReprHighlighter(_ReprHighlighter):
    accounts_prefixes = ("ACC", "BUY", "LCE", "MOD", "SEL", "USR", "AUSR", "UGR")
    catalog_prefixes = (
        "PRD",
        "ITM",
        "IGR",
        "PGR",
        "MED",
        "DOC",
        "TCS",
        "TPL",
        "WHO",
        "PRC",
        "LST",
        "AUT",
        "UNT",
    )
    commerce_prefixes = ("AGR", "ORD", "SUB", "REQ")
    aux_prefixes = ("FIL", "MSG")
    all_prefixes = (*accounts_prefixes, *catalog_prefixes, *commerce_prefixes, *aux_prefixes)
    highlights = _ReprHighlighter.highlights + [
        rf"(?P<mpt_id>(?:{'|'.join(all_prefixes)})(?:-\d{{4}})*)"
    ]


console = Console(
    highlighter=ReprHighlighter(),
    theme=Theme({"repr.mpt_id": "bold light_salmon3"}),
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
        return next(filter(lambda x: x["vendor_external_id"] == sku, ADOBE_CONFIG["skus_mapping"]))
    except StopIteration:
        raise ClickException(f"Invalid SKU provided: {sku}")


def gen_param(
    name,
    external_id,
    value=None,
    constraints=None,
):
    par_id = generate_random_id("PRM", 16, 4)
    param = {
        "id": par_id,
        "name": name,
        "externalId": external_id,
        "constraints": constraints,
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
        "phone": {
            "prefix": fake.country_calling_code(),
            "number": fake.msisdn(),
        },
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


def gen_seller(fake, product):
    seller_id = f"SEL-{base_id_from(product['id'])}"
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
    console.print(f"[green]✓[/green] Seller {seller_id} - {seller['name']} generated")
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
    console.print(f"[green]✓[/green] Licensee {lic_id} - {licensee['name']} generated")
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
    console.print(f"[green]✓[/green] Account {acc_id} - {account['name']} generated")
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
    console.print(f"[green]✓[/green] Buyer {buyer_id} - {buyer['name']} generated")
    return buyer


def gen_authorization(fake, product, vendor, seller, currency="USD"):
    auth_id = f"AUT-{base_id_from(product['id'])}"
    authorization = {
        "id": auth_id,
        "href": f"/v1/authorizations/{auth_id}",
        "currency": currency,
        "name": f"Authorization for {product['name']}",
        "product": product,
        "vendor": get_reference(vendor),
        "owner": get_reference(seller),
    }
    save_authorization(authorization)
    console.print(f"[green]✓[/green] Authorization {auth_id} - {authorization['name']} generated")
    return authorization

def gen_pricelist(fake, product, vendor, currency="USD"):
    pl_id = generate_random_id("PRC", 12, 4)
    pricelist = {
        "id": pl_id,
        "href": f"/v1/price-lists/{pl_id}",
        "currency": currency,
        "precision": 3,
        "defaultMarkup": float(fake.pydecimal(left_digits=0, right_digits=3, positive=True, min_value=0.001, max_value=0.45)),
        "product": product,
        "vendor": get_reference(vendor),
    }
    save_pricelist(pricelist)
    console.print(f"[green]✓[/green] Price List {pl_id} generated")
    return pricelist


def gen_listing(fake, product):
    seller = gen_seller(fake, product)
    vendor = gen_account(fake, "Vendor")
    authorization = gen_authorization(fake, product, vendor, seller)
    price_list = gen_pricelist(fake, product, vendor)
    gen_pricelist_items(fake, product, price_list)
    lst_id = f"LST-{base_id_from(product['id'])}"
    listing = {
        "id": lst_id,
        "href": f"/listing/{lst_id}",
        "product": product,
        "authorization": get_reference(authorization),
        "seller": get_reference(seller),
        "priceList": get_reference(price_list),
        "primary": True,
        "audit": gen_audit(fake),
    }
    save_listing(listing)
    console.print(f"[green]✓[/green] Listing {lst_id} generated")
    return listing

def gen_pricelist_items(fake, product, pricelist):
    product_id = product["id"]
    pl_id = pricelist["id"]
    pl_base_id = base_id_from(pricelist["id"])
    idx = 1
    for adobe_item in ADOBE_CONFIG["skus_mapping"]:
        item = load_item(f"{product_id}_{adobe_item['vendor_external_id']}")
        pl_item_id = f"PRI-{pl_base_id}-{idx:04d}"
        unit_pp = float(fake.pydecimal(left_digits=4, right_digits=3, positive=True))
        unit_sp = unit_pp * (1 + pricelist["defaultMarkup"])

        pricelist_item = {
            "id": pl_item_id,
            "href": f"/price-lists/{pl_id}/price-list-items/{pl_item_id}",
            "forSale": True,
            "unitPP": unit_pp,
            "unitSP": unit_sp,
            "unitLP": unit_sp,
            "PPxM": unit_pp,
            "PPxY": 12 * unit_pp,
            "SPxM": unit_sp,
            "SPxY": 12 * unit_sp,
            "markup": pricelist["defaultMarkup"],
            "margin": pricelist["defaultMarkup"] / (1 + pricelist["defaultMarkup"]),
            "priceList": get_reference(pricelist),
            "item": get_reference(item),
        }
        save_pricelist_item(pricelist_item)
        console.print(
            f"[green]✓[/green] Pricelist item {pl_item_id} - {adobe_item['name']} ({adobe_item['vendor_external_id']}) generated",
        )
        idx += 1
        for discount_level, discount_rate in (
            ("01", 0),
            ("02", 0.1),
            ("03", 0.12),
            ("04", 0.15),
            ("12", 0.2),
            ("13", 0.22),
            ("14", 0.25),
        ):
            full_sku = f"{adobe_item['vendor_external_id']}{discount_level}A12"
            pl_item_id = f"PRI-{pl_base_id}-{idx:04d}"
            item = load_item(f"{product_id}_{full_sku}")
            pricelist_item = {
                "id": pl_item_id,
                "href": f"/price-lists/{pl_id}/price-list-items/{pl_item_id}",
                "forSale": True,
                "unitPP": unit_pp * (1 - discount_rate),
                "unitSP": unit_sp * (1 - discount_rate),
                "unitLP": unit_sp * (1 - discount_rate),
                "PPxM": unit_pp * (1 - discount_rate),
                "PPxY": 12 * unit_pp * (1 - discount_rate),
                "SPxM": unit_sp * (1 - discount_rate),
                "SPxY": 12 * unit_sp * (1 - discount_rate),
                "markup": pricelist["defaultMarkup"],
                "margin": pricelist["defaultMarkup"] / (1 + pricelist["defaultMarkup"]),
                "priceList": get_reference(pricelist),
                "item": get_reference(item),
            }
            save_pricelist_item(pricelist_item)
            console.print(
                f"[green]✓[/green] Pricelist item {pl_item_id} - {adobe_item['name']} ({full_sku}) generated",
            )
            idx += 1

def gen_agreement(fake, product, listing, authorization, seller_id=None):
    seller = load_seller(seller_id or authorization["owner"]["id"])
    agr_id = generate_random_id("AGR", 12, 4)
    client = gen_account(fake)
    buyer = gen_buyer(fake, client)
    vendor = load_account(authorization["vendor"]["id"])
    licensee = gen_licensee(fake, buyer, seller)


    agreement = {
        "id": agr_id,
        "href": f"/v1/commerce/agreements/{agr_id}",
        "status": "Provisioning",
        "name": f"Adobe VIP MP for {buyer['name']}",
        "vendor": get_reference(vendor),
        "client": get_reference(client),
        "licensee": get_reference(licensee),
        "buyer": buyer,
        "seller": seller,
        "product": product,
        "price": {
            "PPxY": 150,
            "PPxM": 12.50,
            "SPxY": 165,
            "SPxM": 13.75,
            "markup": 0.10,
            "margin": 0.11,
            "currency": "USD",
        },
        "authorization": authorization,
        "listing": listing,
        "audit": gen_audit(fake),
    }
    save_agreement(agreement)
    console.print(f"[green]✓[/green] Agreement {agr_id} - {agreement['name']} generated")
    return agreement


def gen_purchase_order(
    fake,
    listing_id,
    skus,
    customer_id,
    adobe_order_id,
    draft,
):
    order_id = generate_random_id("ORD", 16, 4)
    listing = load_listing(listing_id)
    product_id = listing["product"]["id"]
    product = load_product(product_id)
    authorization = load_authorization(listing["authorization"]["id"])
    agreement = gen_agreement(fake, product, listing, authorization)
    lines = []
    subscriptions = []
    for idx, sku in enumerate(skus, start=1):
        old_quantity = 0
        quantity = random.randint(2, 5)
        item = load_item(f"{product_id}_{sku}")
        item_id = item["id"]
        pricelist_id = agreement["listing"]["priceList"]["id"]
        pricelist_item_id = f"PRI-{base_id_from(pricelist_id)}-{item_id[-4:]}"
        pricelist_item = load_pricelist_item(pricelist_item_id)
        lines.append(
            {
                "id": f"ALI-{base_id_from(agreement['id'])}-{idx:04d}",
                "item": get_reference(item, ["id", "name", "externalIds"]),
                "quantity": quantity,
                "oldQuantity": old_quantity,
                "price": {
                    "unitPP": pricelist_item["unitPP"],
                },
            }
        )
        console.print(
            f"[green]✓[/green] Item {idx} - {item['name']} generated: quantity = {quantity}",
        )

    order = {
        "id": order_id,
        "type": "purchase",
        "status": "draft" if draft else "processing",
        "agreement": get_reference(agreement, DEFAULT_FIELDS + ["product"]),
        "authorization": authorization,
        "listing": agreement["listing"],
        "subscriptions": [get_reference(sub) for sub in subscriptions],
        "lines": lines,
        "audit": gen_audit(fake),
        "parameters": {
            "ordering": [
                gen_param("CompanyName", "companyName"),
                gen_param("PreferredLanguage", "preferredLanguage"),
                gen_param("Address", "address"),
                gen_param("Contact", "contact"),
                gen_param("AgreementType", "agreementType", value="New"),
            ],
            "fulfillment": [
                gen_param(
                    "RetryCount",
                    "retryCount",
                    "0",
                    constraints={"hidden": True},
                ),
                gen_param("CustomerId", "customerId", value=customer_id),
            ],
        },
    }
    if adobe_order_id:
        order["externalIds"] = {
            "vendor": adobe_order_id,
        }
    save_order(order)
    return order


def gen_change_order(fake, agreement_id, skus, change_type):
    order_id = generate_random_id("ORD", 16, 4)
    agreement = load_agreement(agreement_id)
    listing = load_listing(agreement["listing"]["id"])
    authorization = load_authorization(listing["authorization"]["id"])
    product_id = agreement["product"]["id"]
    if agreement["status"] != "active":
        raise ClickException("Agreement must be 'active' in order to generate a Change order.")
    lines = []
    subscriptions = []
    if change_type == "both" and len(agreement.get("subscriptions", [])) < 2:
        raise ClickException(
            "You need at least two subscriptions within the provided "
            "agreement to have both upsizing and downsizing items."
        )

    for line_number, subscription in enumerate(agreement["subscriptions"], start=1):
        sub_data = load_subscription(subscription["id"])
        sub_data["status"] = "updating"
        save_subscription(sub_data)
        subscriptions.append(get_reference(sub_data))
        line = sub_data["lines"][0]
        new_line = copy.copy(line)
        new_line["oldQuantity"] = line["quantity"]
        if change_type == "upsize":
            rand_prm = (new_line["oldQuantity"] + 1, 9)
        elif change_type == "downsize":
            rand_prm = (1, new_line["oldQuantity"] - 1)
        elif line_number == 1:
            rand_prm = (new_line["oldQuantity"] + 1, 9)
        elif line_number == 2:
            rand_prm = (1, new_line["oldQuantity"] - 1)
        else:
            rand_prm = random.choice(
                [
                    (new_line["oldQuantity"] + 1, 9),
                    (1, new_line["oldQuantity"] - 1),
                ],
            )
        try:
            new_line["quantity"] = random.randint(*rand_prm)
            console.print(
                f"[green]✓[/green] Item {line_number} - {new_line['item']['name']} updated: "
                f"quantity = {new_line['oldQuantity']} -> {new_line['quantity']}",
            )
        except ValueError:
            console.print(
                f"[orange]✓[/orange] Item {line_number} - {new_line['item']['name']} unchanged: "
                f"quantity = {new_line['oldQuantity']} -> {new_line['quantity']}",
            )
        lines.append(new_line)

    if skus:
        for idx, sku in enumerate(skus, start=line_number + 1):
            item = load_item(f"{product_id}_{sku}")
            old_quantity = 0
            quantity = random.randint(1, 5)

            lines.append(
                {
                    "id": f"ALI-{base_id_from(agreement['id'])}-{idx:04d}",
                    "item": get_reference(item, ["id", "name", "externalIds"]),
                    "quantity": quantity,
                    "oldQuantity": old_quantity,
                }
            )
            console.print(
                f"[green]✓[/green] Item {idx} - {item['name']} added: quantity = {quantity}",
            )

    order = {
        "id": order_id,
        "type": "change",
        "status": "processing",
        "agreement": get_reference(agreement, DEFAULT_FIELDS + ["product"]),
        "listing": listing,
        "authorization": authorization,
        "lines": lines,
        "subscriptions": subscriptions,
        "audit": gen_audit(fake),
        "parameters": agreement["parameters"],
    }
    agreement["status"] = "updating"
    save_agreement(agreement)
    save_order(order)

    return order


def gen_termination_order(fake, agreement_id, subscriptions_ids):
    agreement = load_agreement(agreement_id)
    if agreement["status"] != "active":
        raise ClickException("Agreement must be 'active' in order to generate a Termination order.")
    agreement_sub_ids = [sub["id"] for sub in agreement["subscriptions"]]
    subscriptions_ids = subscriptions_ids or agreement_sub_ids
    invalid_sub_ids = list(set(subscriptions_ids) - set(agreement_sub_ids))
    if invalid_sub_ids:
        raise ClickException(
            f"The subscriptions {','.join(invalid_sub_ids)} are not part of the "
            f"agreement {agreement_id}."
        )

    order_id = generate_random_id("ORD", 16, 4)
    subscriptions = []
    lines = []
    for sub_id in subscriptions_ids:
        sub_data = load_subscription(sub_id)
        sub_data["status"] = "terminating"
        save_subscription(sub_data)
        line = sub_data["lines"][0]
        new_line = copy.copy(line)
        new_line["oldQuantity"] = line["quantity"]
        new_line["quantity"] = 0
        lines.append(new_line)
        subscriptions.append(get_reference(sub_data))

    order = {
        "id": order_id,
        "type": "termination",
        "status": "processing",
        "agreement": get_reference(agreement, DEFAULT_FIELDS + ["product"]),
        "lines": lines,
        "subscriptions": subscriptions,
        "audit": gen_audit(fake),
        "parameters": agreement["parameters"],
    }
    agreement["status"] = "updating"
    save_agreement(agreement)
    save_order(order)
    return order


def gen_transfer_order(
    fake,
    listing_id,
    membership_id,
    skus,
):
    order_id = generate_random_id("ORD", 16, 4)
    listing = load_listing(listing_id)
    product_id = listing["product"]["id"]
    product = load_product(product_id)
    authorization = load_authorization(listing["authorization"]["id"])
    agreement = gen_agreement(fake, product, listing, authorization)
    lines = []
    for idx, line in enumerate(skus, start=1):
        sku, quantity = line
        product = get_product_by_sku(sku)
        old_quantity = 0
        lines.append(
            {
                "id": f"ALI-{base_id_from(agreement['id'])}-{idx:04d}",
                "item": {
                    "id": f"ITM-{base_id_from(product_id)}-{idx:04d}",
                    "name": product["name"],
                    "externalIds": {
                        "vendor": sku,
                    },
                },
                "quantity": quantity,
                "oldQuantity": old_quantity,
            }
        )
        console.print(
            f"[green]✓[/green] Item {idx} - {product['name']} generated: quantity = {quantity}",
        )

    order = {
        "id": order_id,
        "type": "purchase",
        "status": "processing" if skus else "draft",
        "agreement": get_reference(agreement, DEFAULT_FIELDS + ["product"]),
        "authorization": authorization,
        "listing": listing,
        "subscriptions": [],
        "lines": lines,
        "audit": gen_audit(fake),
        "parameters": {
            "ordering": [
                gen_param("AgreementType", "agreementType", value="Migrate"),
                gen_param("Membership Id", "membershipId", value=membership_id),
            ],
            "fulfillment": [
                gen_param(
                    "RetryCount",
                    "retryCount",
                    "0",
                    constraints={"hidden": True},
                ),
                gen_param("CustomerId", "customerId"),
            ],
        },
    }
    save_order(order)
    return order


def gen_items(fake, product):
    product_id = product["id"]
    item_base_id = base_id_from(product_id)
    idx = 1
    for item in ADOBE_CONFIG["skus_mapping"]:
        item_id = f"ITM-{item_base_id}-{idx:04d}"
        prod_item = {
            "id": item_id,
            "href": f"/product-items/{item_id}",
            "name": item["name"],
            "description": item["name"],
            "externalIds": {
                "vendor": item["vendor_external_id"],
            },
            "status": "published",
            "product": product,
            "audit": gen_audit(fake)
        }
        save_item(prod_item, f"{product_id}_{item['vendor_external_id']}")
        console.print(
            f"[green]✓[/green] Item {item_id} - {item['name']} ({item['vendor_external_id']}) generated",
        )
        idx += 1
        for discount_level in ("01", "02", "03", "04", "12", "13", "14"):
            full_sku = f"{item['vendor_external_id']}{discount_level}A12"
            item_id = f"ITM-{item_base_id}-{idx:04d}"
            prod_item = {
                "id": item_id,
                "href": f"/product-items/{item_id}",
                "name": item["name"],
                "description": item["name"],
                "externalIds": {
                    "vendor": full_sku,
                },
                "status": "draft",
                "product": {
                    "id": product_id,
                    "name": "Adobe VIP Marketplace for Commercial",
                },
                "audit": gen_audit(fake)
            }
            save_item(prod_item, f"{product_id}_{full_sku}")
            console.print(
                f"[green]✓[/green] Item {item_id} - {item['name']} ({full_sku}) generated",
            )
            idx += 1


@click.group()
def cli():
    pass


@cli.command()
@click.argument("listing_id", metavar="[LISTING ID]", nargs=1, required=True)
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
@click.option(
    "--draft",
    default=False,
    is_flag=True,
    help=(
        "Set the status of the order to draft."
    ),
)
@click.option("--locale", default="en_US")
def purchase(listing_id, customer_id, order_id, locale, skus, draft):
    """
    Generate a purchase order for the provided Adobe (partial) SKUs.
    """
    fake = Faker(locale)
    with console.status(
        "[magenta]Generating purchase order...",
        spinner="bouncingBall",
        spinner_style="yellow",
    ):
        order = gen_purchase_order(
            fake,
            listing_id,
            skus,
            customer_id,
            order_id,
            draft,
        )
    console.print(
        "[bold green]New 'Purchase' order has been "
        f"generated for skus {', '.join(skus)}: {order['id']}",
    )


@cli.command()
@click.argument(
    "listing_id",
    metavar="[LISTING ID]",
    nargs=1,
)
@click.argument(
    "membership_id",
    metavar="[MEMBERSHIP ID]",
    nargs=1,
)
@click.option(
    "--line",
    "-l",
    "lines",
    type=(str, int),
    multiple=True,
)
@click.option("--locale", default="en_US")
def transfer(listing_id, membership_id, locale, lines):
    """
    Generate a transfer order optionally including the provided Adobe (partial) SKUs.
    """
    fake = Faker(locale)
    with console.status(
        "[magenta]Generating transfer order...",
        spinner="bouncingBall",
        spinner_style="yellow",
    ):
        skus = [line[0] for line in lines]
        order = gen_transfer_order(
            fake,
            listing_id,
            membership_id,
            lines,
        )
    msg = f"[bold green]New 'Transfer' order has been generated: {order['id']}"
    if skus:
        msg = f"{msg} ({', '.join(skus)})"
    console.print(f"{msg}.")


@cli.command()
@click.argument(
    "agreement_id",
    metavar="[AGREEMENT ID]",
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
    with console.status(
        "[magenta]Generating change order...",
        spinner="bouncingBall",
        spinner_style="yellow",
    ):
        order = gen_change_order(fake, agreement_id, skus, change_type)
    console.print(
        f"[bold green]New 'Change' order has been generated for agreement {agreement_id}: "
        f"{order['id']}",
    )


@cli.command()
@click.argument(
    "agreement_id",
    metavar="[AGREEMENT_ID]",
    nargs=1,
    required=True,
)
@click.argument(
    "subscriptions",
    metavar="[SUBSCRIPTION_ID ...]",
    nargs=-1,
    required=False,
)
@click.option("--locale", default="en_US")
def terminate(locale, agreement_id, subscriptions):
    """
    Generate a termination order for an Agreement or one or more
    Subscriptions within an Agreement.
    """
    fake = Faker(locale)
    with console.status(
        "[magenta]Generating change order...",
        spinner="bouncingBall",
        spinner_style="yellow",
    ):
        order = gen_termination_order(fake, agreement_id, subscriptions)
    if not subscriptions:
        console.print(
            "[bold green]New 'Termination' order has been generated "
            f"for agreement {agreement_id}: {order['id']}",
        )
    else:
        console.print(
            "[bold green]New 'Termination' order has been "
            f"generated for subscriptions {', '.join(subscriptions)} "
            f"({agreement_id}): {order['id']}",
        )


def gen_products(fake):
    products = [
        ("PRD-1111-1111", "Adobe VIP Marketplace for Commercial"),
        ("PRD-2222-2222", "Adobe VIP Marketplace for Government"),
        ("PRD-3333-3333", "Adobe VIP Marketplace for Education"),
    ]
    for product_id, product_name in products:
        product = {
            "id": product_id,
            "href": f"/v1/products/{product_id}",
            "name": product_name,
            "status": "Published",
        }
        save_product(product)
        gen_items(fake, product)
        gen_listing(fake, product)



@cli.command()
@click.option("--locale", default="en_US")
def setup(locale):
    with console.status(
        "[magenta]Setup mocked data generator...",
        spinner="bouncingBall",
        spinner_style="yellow",
    ):
        fake = Faker()
        gen_products(fake)


@cli.command()
@click.option(
    "--all",
    is_flag=True,
    default=False,
)
def cleanup(all):
    """
    Remove all the content of the data folder.
    """
    cleanup_data_folder(all)


@cli.command()
@click.argument(
    "search_terms",
    metavar="[SEARCH TERM ...]",
    nargs=-1,
    required=True,
)
def sku(search_terms):
    """
    Search a product by name in SKUs mapping given a search term.
    """
    table = Table(
        title="Adobe VIP MP Products",
        box=box.ROUNDED,
        border_style="blue",
        header_style="deep_sky_blue1",
        expand=False,
    )
    table.add_column("Vendor Ext. Id")
    table.add_column("SKU")
    table.add_column("Name", min_width=55)
    table.add_column("Type")

    conds = []

    def filter_fn(search_term, item):
        return search_term.lower() in item["name"].lower()

    for search_term in search_terms:
        conds.append(partial(filter_fn, search_term))

    for item in filter(
        lambda i: any([fn(i) for fn in conds]),
        ADOBE_CONFIG["skus_mapping"],
    ):
        table.add_row(item["vendor_external_id"], item["sku"], item["name"], item["type"])

    console.print()
    console.print(table)


def main():
    try:
        cli(standalone_mode=False)
    except (ClickException, NotFoundException) as e:
        console.print(f"[bold red]Error:[/bold red] {str(e)}")
    except Abort:
        pass
    except Exception:
        console.print_exception()


if __name__ == "__main__":
    main()
