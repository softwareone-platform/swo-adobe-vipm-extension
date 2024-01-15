from py_rql.constants import FilterTypes
from py_rql.filter_cls import FilterClass as _FilterClass
from py_rql.helpers import extract_value
from starlette.datastructures import QueryParams


class FilterClass(_FilterClass):
    def apply_ordering(self, order, data):
        for ordering_field in order:
            reverse = False
            if ordering_field.startswith("-"):
                reverse = True
                ordering_field = ordering_field[1:]
            elif ordering_field.startswith("+"):
                ordering_field = ordering_field[1:]
            flt = self._filters.get(ordering_field)
            if not flt:
                continue
            data = sorted(
                data,
                key=lambda obj: flt["cast_func"](extract_value(obj, ordering_field)),
                reverse=reverse,
            )
        return data

    def apply(self, query, data):
        rql, order, limit, offset = self._parse_qs(query)
        filtered = list(self.filter(rql, data))
        ordered = self.apply_ordering(order, filtered)
        return ordered[offset : limit + offset], len(ordered), limit, offset

    def _parse_qs(self, query):
        limit = 10
        offset = 0
        order = []
        rql = ""
        params = QueryParams(query)
        for k, v in params.items():
            if k == "limit":
                limit = int(v)
            elif k == "offset":
                offset = int(v)
            elif k == "order":
                order.extend(v.split(","))
            elif v == "":
                rql = k
        return rql, order, limit, offset


class OrdersFilter(FilterClass):
    FILTERS = [
        {
            "filter": "status",
        },
        {
            "filter": "agreement.product.id",
        },
        {
            "filter": "audit.created.at",
            "type": FilterTypes.DATETIME,
        },
    ]
