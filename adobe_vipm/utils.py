def find_first(func, iterable, default=None):
    return next(filter(func, iterable), default)


def get_partial_sku(full_sku):
    return full_sku[:10]
