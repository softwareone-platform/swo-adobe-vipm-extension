import copy
import json
from functools import wraps

from adobe_vipm.flows.constants import STRUCTURED_PARAMETERS
from adobe_vipm.flows.errors import wrap_http_error


def unpack_structured_parameters(parameters):
    """
    Temporary solution that unpacks structured values of complex parameters (Address, Contact)
    from json string to usual dictionary
    """

    def _unpack(parameter):
        if parameter["type"] in STRUCTURED_PARAMETERS:
            parameter = copy.deepcopy(parameter)
            parameter["value"] = json.loads(parameter["value"]) if parameter["value"] else None
        return parameter

    if "fulfillment" in parameters:
        parameters["fulfillment"] = [_unpack(p) for p in (parameters["fulfillment"] or [])]
    if "ordering" in parameters:
        parameters["ordering"] = [_unpack(p) for p in (parameters["ordering"] or [])]

    return parameters


def pack_structured_parameters(parameters):
    """
    Temporary solution that packs structured values of complex parameters (Address, Contact)
    from dictionary to json string
    """

    def _pack(parameter):
        if parameter["type"] in STRUCTURED_PARAMETERS:
            parameter = copy.deepcopy(parameter)
            parameter["value"] = json.dumps(parameter["value"]) if parameter["value"] else None
        return parameter

    if "fulfillment" in parameters:
        parameters["fulfillment"] = [_pack(p) for p in (parameters["fulfillment"] or [])]
    if "ordering" in parameters:
        parameters["ordering"] = [_pack(p) for p in (parameters["ordering"] or [])]

    return parameters


def pack_decorator(parameters_kwarg_name):
    def _decorator(f):
        @wraps(f)
        def _wrapper(*args, **kwargs):
            if parameters_kwarg_name in kwargs:
                kwargs[parameters_kwarg_name] = pack_structured_parameters(
                    kwargs[parameters_kwarg_name]
                )
            return f(*args, **kwargs)

        return _wrapper

    return _decorator


def unpack_decorator(return_entity_property_name):
    def _decorator(f):
        @wraps(f)
        def _wrapper(*args, **kwargs):
            entity = f(*args, **kwargs)
            entity[return_entity_property_name] = unpack_structured_parameters(
                entity[return_entity_property_name],
            )

            return entity

        return _wrapper

    return _decorator


@unpack_decorator("parameters")
@wrap_http_error
def get_agreement(mpt_client, agreement_id):
    response = mpt_client.get(f"/commerce/agreements/{agreement_id}?select=seller,buyer")
    response.raise_for_status()
    return response.json()


@wrap_http_error
def get_seller(mpt_client, seller_id):
    response = mpt_client.get(f"/accounts/sellers/{seller_id}")
    response.raise_for_status()
    return response.json()


@wrap_http_error
def get_buyer(mpt_client, buyer_id):
    response = mpt_client.get(f"/accounts/buyers/{buyer_id}")
    response.raise_for_status()
    return response.json()


@pack_decorator("parameters")
@unpack_decorator("parameters")
@wrap_http_error
def update_order(mpt_client, order_id, **kwargs):
    response = mpt_client.put(
        f"/commerce/orders/{order_id}",
        json=kwargs,
    )
    response.raise_for_status()
    return response.json()


@pack_decorator("parameters")
@unpack_decorator("parameters")
@wrap_http_error
def query_order(mpt_client, order_id, **kwargs):
    response = mpt_client.post(
        f"/commerce/orders/{order_id}/query",
        json=kwargs,
    )
    response.raise_for_status()
    return response.json()


@unpack_decorator("parameters")
@wrap_http_error
def fail_order(mpt_client, order_id, reason):
    response = mpt_client.post(
        f"/commerce/orders/{order_id}/fail",
        json={"reason": reason},
    )
    response.raise_for_status()
    return response.json()


@unpack_decorator("parameters")
@wrap_http_error
def complete_order(mpt_client, order_id, template_id):
    response = mpt_client.post(
        f"/commerce/orders/{order_id}/complete",
        json={"template": {"id": template_id}},
    )
    response.raise_for_status()
    return response.json()


@unpack_decorator("parameters")
@wrap_http_error
def create_subscription(mpt_client, order_id, subscription):
    if "parameters" in subscription:
        subscription["parameters"] = pack_structured_parameters(subscription["parameters"])

    response = mpt_client.post(
        f"/commerce/orders/{order_id}/subscriptions",
        json=subscription,
    )
    response.raise_for_status()
    return response.json()


@wrap_http_error
def get_product_items(mpt_client, product_id, item_ids):
    item_filter = f"product.id={product_id}&in(externalIds.vendor,({','.join(item_ids)}))"

    response = mpt_client.get(f"/product-items?{item_filter}")
    response.raise_for_status()
    data = response.json()

    return data["data"]
