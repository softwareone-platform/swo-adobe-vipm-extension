from collections import Counter

from adobe_vipm.flows.constants import ERR_DUPLICATED_ITEMS, ERR_EXISTING_ITEMS
from adobe_vipm.flows.utils import set_order_error


def validate_duplicate_or_existing_lines(order):
    items = [line["item"]["id"] for line in order["lines"]]
    duplicates = [item for item, count in Counter(items).items() if count > 1]
    if duplicates:
        order = set_order_error(
            order,
            ERR_DUPLICATED_ITEMS.to_dict(duplicates=",".join(duplicates))
        )
        return True, order

    items = []
    for subscription in order["agreement"]["subscriptions"]:
        for line in subscription["lines"]:
            items.append(line["item"]["id"])

    items.extend([line["item"]["id"] for line in order["lines"] if line["oldQuantity"] == 0])
    duplicates = [item for item, count in Counter(items).items() if count > 1]
    if duplicates:
        order = set_order_error(
            order,
            ERR_EXISTING_ITEMS.to_dict(duplicates=",".join(duplicates))
        )
        return True, order
    return False, order
