def find_first(func, iterable, default=None):
    return next(filter(func, iterable), default)
