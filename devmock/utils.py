import functools
import glob
import json
import os
import random
from datetime import datetime
from textwrap import wrap

import jwt

from devmock.exceptions import NotFoundException
from devmock.settings import (
    ACCOUNTS_FOLDER,
    AGREEMENTS_FOLDER,
    AUTHORIZATIONS_FOLDER,
    BUYERS_FOLDER,
    ITEMS_FOLDER,
    LICENSEES_FOLDER,
    LISTINGS_FOLDER,
    ORDERS_FOLDER,
    PRICELISTS_FOLDER,
    PRICELIST_ITEMS_FOLDER,
    SELLERS_FOLDER,
    SUBSCRIPTIONS_FOLDER,
    WEBHOOK_ID,
    WEBHOOK_JWT_SECRET,
)

DEFAULT_FIELDS = ["id", "href", "name", "icon"]


def load_object(folder, name, obj_id):
    obj_file = os.path.join(folder, f"{obj_id}.json")
    if not os.path.exists(obj_file):
        raise NotFoundException(f"{name.capitalize()} object with id {obj_id} not found")
    return json.load(open(obj_file, "r"))


def save_object(folder, obj, obj_id=None):
    if not os.path.exists(folder):
        os.makedirs(folder)
        with open(os.path.join(folder, ".gitkeep"), "w"):
            pass

    obj_id = obj_id or obj["id"]
    obj_file = os.path.join(folder, f"{obj_id}.json")
    json.dump(obj, open(obj_file, "w"), indent=2)


load_order = functools.partial(load_object, ORDERS_FOLDER, "order")
load_buyer = functools.partial(load_object, BUYERS_FOLDER, "buyer")
load_seller = functools.partial(load_object, SELLERS_FOLDER, "seller")
load_subscription = functools.partial(load_object, SUBSCRIPTIONS_FOLDER, "subscription")
load_agreement = functools.partial(load_object, AGREEMENTS_FOLDER, "agreement")
load_item = functools.partial(load_object, ITEMS_FOLDER, "item")
load_authorization = functools.partial(load_object, AUTHORIZATIONS_FOLDER, "authorization")
load_pricelist = functools.partial(load_object, PRICELISTS_FOLDER, "pricelist")
load_listing = functools.partial(load_object, LISTINGS_FOLDER, "listing")
load_pricelist_item = functools.partial(load_object, PRICELIST_ITEMS_FOLDER, "pricelist item")


save_order = functools.partial(save_object, ORDERS_FOLDER)
save_subscription = functools.partial(save_object, SUBSCRIPTIONS_FOLDER)
save_buyer = functools.partial(save_object, BUYERS_FOLDER)
save_seller = functools.partial(save_object, SELLERS_FOLDER)
save_agreement = functools.partial(save_object, AGREEMENTS_FOLDER)
save_account = functools.partial(save_object, ACCOUNTS_FOLDER)
save_licensee = functools.partial(save_object, LICENSEES_FOLDER)
save_item = functools.partial(save_object, ITEMS_FOLDER)
save_authorization = functools.partial(save_object, AUTHORIZATIONS_FOLDER)
save_pricelist = functools.partial(save_object, PRICELISTS_FOLDER)
save_listing = functools.partial(save_object, LISTINGS_FOLDER)
save_pricelist_item = functools.partial(save_object, PRICELIST_ITEMS_FOLDER)


def generate_random_id(
    prefix,
    length,
    sep_frequency,
):
    number = str(
        random.randint(
            1 * 10 ** (length - 1),
            1 * 10 ** length - 1,
        ),
    )

    return f'{prefix}-{"-".join(wrap(number, sep_frequency))}'


def base_id_from(mpt_obj_id):
    return mpt_obj_id.split("-", 1)[1]


def cleanup_data_folder(with_items):
    folders = [
        ACCOUNTS_FOLDER,
        AGREEMENTS_FOLDER,
        AUTHORIZATIONS_FOLDER,
        BUYERS_FOLDER,
        LICENSEES_FOLDER,
        LISTINGS_FOLDER,
        PRICELISTS_FOLDER,
        PRICELIST_ITEMS_FOLDER,
        ORDERS_FOLDER,
        SELLERS_FOLDER,
        SUBSCRIPTIONS_FOLDER,
    ]
    if with_items:
        folders.append(ITEMS_FOLDER)

    for folder in folders:
        for f in glob.glob(os.path.join(folder, "*.json")):
            os.remove(f)


def get_reference(obj, fields=None):
    return {k: v for k, v in obj.items() if k in (fields or DEFAULT_FIELDS)}


def get_line_for_subscription(line):
    return {k: v for k, v in line.items() if k != "oldQuantity"}


def gen_jwt_token():
    nbf = int(datetime.now().timestamp())
    exp = nbf + 300
    return jwt.encode(
        {
            "aud": "localhost:8080",
            "nbf": nbf,
            "exp": exp,
            "wid": WEBHOOK_ID,
        },
        WEBHOOK_JWT_SECRET,
        algorithm="HS256",
    )
