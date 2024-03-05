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
        "title": name,
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
        "phone": {
            "prefix": fake.country_calling_code(),
            "number": fake.msisdn(),
        },
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
    save_agreement(agreement)
    console.print(f"[green]✓[/green] Agreement {agr_id} - {agreement['name']} generated")
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
        quantity = random.randint(2, 5)
        item = {
            "id": f"ITM-1111-1111-1111-{idx:04d}",
            "name": product["name"],
            "quantity": quantity,
            "oldQuantity": old_quantity,
            "lineNumber": idx,
            "productItemId": sku,
        }
        items.append(item)
        console.print(
            f"[green]✓[/green] Item {idx} - {product['name']} generated: quantity = {quantity}",
        )

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
    if agreement["status"] != "Active":
        raise ClickException("Agreement must be Active in order to generate a Change order.")
    items = []
    subscriptions = []
    if change_type == "both" and len(agreement.get("subscriptions", [])) < 2:
        raise ClickException(
            "You need at least two subscriptions within the provided "
            "agreement to have both upsizing and downsizing items."
        )

    for line_number, subscription in enumerate(agreement["subscriptions"], start=1):
        sub_data = load_subscription(subscription["id"])
        sub_data["status"] = "Updating"
        save_subscription(sub_data)
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
        try:
            new_item["quantity"] = random.randint(*rand_prm)
            console.print(
                f"[green]✓[/green] Item {line_number} - {new_item['name']} updated: "
                f"quantity = {new_item['oldQuantity']} -> {new_item['quantity']}",
            )
        except ValueError:
            console.print(
                f"[orange]✓[/orange] Item {line_number} - {new_item['name']} unchanged: "
                f"quantity = {new_item['oldQuantity']} -> {new_item['quantity']}",
            )
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
            console.print(
                f"[green]✓[/green] Item {idx} - {product['name']} added: quantity = {quantity}",
            )
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


def gen_termination_order(fake, agreement_id, subscriptions_ids):
    agreement = load_agreement(agreement_id)
    if agreement["status"] != "Active":
        raise ClickException("Agreement must be Active in order to generate a Termination order.")
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
    items = []
    for sub_id in subscriptions_ids:
        sub_data = load_subscription(sub_id)
        sub_data["status"] = "Terminating"
        save_subscription(sub_data)
        item = sub_data["items"][0]
        new_item = copy.copy(item)
        new_item["oldQuantity"] = item["quantity"]
        new_item["quantity"] = 0
        items.append(new_item)
        subscriptions.append(get_reference(sub_data))

    order = {
        "id": order_id,
        "type": "Termination",
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
    with console.status(
        "[magenta]Generating purchase order...",
        spinner="bouncingBall",
        spinner_style="yellow",
    ):
        order = gen_purchase_order(
            fake,
            skus,
            customer_id,
            order_id,
        )
    console.print(
        "[bold green]New 'Purchase' order has been "
        f"generated for skus {', '.join(skus)}: {order['id']}",
    )


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


@cli.command()
def cleanup():
    """
    Remove all the content of the data folder.
    """
    cleanup_data_folder()


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
        table.add_row(item["vendor_external_id"], item["name"], item["type"])

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
