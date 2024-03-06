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
    BUYERS_FOLDER,
    ITEMS_FOLDER,
    LICENSEES_FOLDER,
    ORDERS_FOLDER,
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


load_order = functools.partial(load_object, ORDERS_FOLDER, "order")
load_buyer = functools.partial(load_object, BUYERS_FOLDER, "buyer")
load_seller = functools.partial(load_object, SELLERS_FOLDER, "seller")
load_subscription = functools.partial(load_object, SUBSCRIPTIONS_FOLDER, "subscription")
load_agreement = functools.partial(load_object, AGREEMENTS_FOLDER, "agreement")
load_items = functools.partial(load_object, ITEMS_FOLDER, "items")


def save_object(folder, obj, obj_id=None):
    obj_id = obj_id or obj["id"]
    obj_file = os.path.join(folder, f"{obj_id}.json")
    json.dump(obj, open(obj_file, "w"), indent=2)


save_order = functools.partial(save_object, ORDERS_FOLDER)
save_subscription = functools.partial(save_object, SUBSCRIPTIONS_FOLDER)
save_buyer = functools.partial(save_object, BUYERS_FOLDER)
save_seller = functools.partial(save_object, SELLERS_FOLDER)
save_agreement = functools.partial(save_object, AGREEMENTS_FOLDER)
save_account = functools.partial(save_object, ACCOUNTS_FOLDER)
save_licensee = functools.partial(save_object, LICENSEES_FOLDER)
save_items = functools.partial(save_object, ITEMS_FOLDER)


def generate_random_id(
    prefix,
    length,
    sep_frequency,
):
    number = str(
        random.randint(
            1 * 10 ** (length - 1),
            1 * 10**length - 1,
        ),
    )

    return f'{prefix}-{"-".join(wrap(number, sep_frequency))}'


def base_id_from(mpt_obj_id):
    return mpt_obj_id.split("-", 1)[1]


def cleanup_data_folder():
    for folder in [
        ACCOUNTS_FOLDER,
        AGREEMENTS_FOLDER,
        BUYERS_FOLDER,
        LICENSEES_FOLDER,
        ORDERS_FOLDER,
        SELLERS_FOLDER,
        SUBSCRIPTIONS_FOLDER,
        ITEMS_FOLDER,
    ]:
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
            "aud": "adobe-vipm.ext.test.s1.com",
            "nbf": nbf,
            "exp": exp,
            "wid": WEBHOOK_ID,
        },
        WEBHOOK_JWT_SECRET,
        algorithm="HS256",
    )
