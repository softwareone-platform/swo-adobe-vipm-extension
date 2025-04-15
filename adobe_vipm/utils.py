def find_first(func, iterable, default=None):
    return next(filter(func, iterable), default)


def get_partial_sku(full_sku):
    return full_sku[:10]


def map_by(key, items_list):
    return {item[key]: item for item in items_list}
