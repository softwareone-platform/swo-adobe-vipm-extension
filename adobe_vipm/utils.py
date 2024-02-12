def find_first(func, iterable, default=None):
    return next(filter(func, iterable), default)


def get_attempt_count(event):  # pragma: no cover
    from adobe_vipm.flows.utils import get_retry_count

    return get_retry_count(event.data)
