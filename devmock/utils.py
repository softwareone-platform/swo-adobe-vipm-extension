import functools
import glob
import json
import os
import random
from textwrap import wrap

from devmock.exceptions import NotFoundException
from devmock.settings import (
    ACCOUNTS_FOLDER,
    AGREEMENTS_FOLDER,
    BUYERS_FOLDER,
    LICENSEES_FOLDER,
    ORDERS_FOLDER,
    SELLERS_FOLDER,
    SUBSCRIPTIONS_FOLDER,
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


def save_object(folder, obj):
    obj_id = obj["id"]
    obj_file = os.path.join(folder, f"{obj_id}.json")
    json.dump(obj, open(obj_file, "w"), indent=2)


save_order = functools.partial(save_object, ORDERS_FOLDER)
save_subscription = functools.partial(save_object, SUBSCRIPTIONS_FOLDER)
save_buyer = functools.partial(save_object, BUYERS_FOLDER)
save_seller = functools.partial(save_object, SELLERS_FOLDER)
save_agreement = functools.partial(save_object, AGREEMENTS_FOLDER)
save_account = functools.partial(save_object, ACCOUNTS_FOLDER)
save_licensee = functools.partial(save_object, LICENSEES_FOLDER)


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


def cleanup_data_folder():
    for folder in [
        ACCOUNTS_FOLDER,
        AGREEMENTS_FOLDER,
        BUYERS_FOLDER,
        LICENSEES_FOLDER,
        ORDERS_FOLDER,
        SELLERS_FOLDER,
        SUBSCRIPTIONS_FOLDER,
    ]:
        for f in glob.glob(os.path.join(folder, "*.json")):
            os.remove(f)


def get_reference(obj, fields=None):
    return {k: v for k, v in obj.items() if k in (fields or DEFAULT_FIELDS)}


def get_item_for_subscription(item):
    return {k: v for k, v in item.items() if k != "oldQuantity"}
