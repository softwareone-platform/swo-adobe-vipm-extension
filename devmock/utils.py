import functools
import json
import os
import random
from textwrap import wrap

from devmock.exceptions import NotFoundException
from devmock.settings import (
    BUYERS_FOLDER,
    ORDERS_FOLDER,
    SELLERS_FOLDER,
    SUBSCRIPTIONS_FOLDER,
)


def get_object_or_404(folder, obj_id):
    obj_file = os.path.join(folder, f"{obj_id}.json")
    if not os.path.exists(obj_file):
        raise NotFoundException(obj_id)
    return json.load(open(obj_file, "r"))


get_order_or_404 = functools.partial(get_object_or_404, ORDERS_FOLDER)
get_buyer_or_404 = functools.partial(get_object_or_404, BUYERS_FOLDER)
get_seller_or_404 = functools.partial(get_object_or_404, SELLERS_FOLDER)


def save_order(order):
    order_id = order["id"]
    order_file = os.path.join(ORDERS_FOLDER, f"{order_id}.json")
    json.dump(order, open(order_file, "w"), indent=2)


def save_subscription(subscription):
    subscription_id = subscription["id"]
    subscription_file = os.path.join(SUBSCRIPTIONS_FOLDER, f"{subscription_id}.json")
    json.dump(subscription, open(subscription_file, "w"), indent=2)


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
