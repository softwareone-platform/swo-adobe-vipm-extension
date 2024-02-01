from adobe_vipm.utils import find_first


def get_actual_sku(items, sku):
    item = find_first(lambda item: item["offerId"].startswith(sku), items, default={})
    return item.get("offerId")


def get_item_to_return(items, line_number):
    return find_first(
        lambda adb_item: adb_item["extLineItemNumber"] == line_number,
        items,
    )
