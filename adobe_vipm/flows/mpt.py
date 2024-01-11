from adobe_vipm.flows.errors import wrap_http_error


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


@wrap_http_error
def update_order(mpt_client, order_id, payload):
    response = mpt_client.put(
        f"/commerce/orders/{order_id}",
        json=payload,
    )
    response.raise_for_status()
    return response.json()


@wrap_http_error
def query_order(mpt_client, order_id, payload):
    response = mpt_client.post(
        f"/commerce/orders/{order_id}/query",
        json=payload,
    )
    response.raise_for_status()
    return response.json()


@wrap_http_error
def fail_order(mpt_client, order_id, reason):
    response = mpt_client.post(
        f"/commerce/orders/{order_id}/fail",
        json={"reason": reason},
    )
    response.raise_for_status()
    return response.json()


@wrap_http_error
def complete_order(mpt_client, order_id, template_id):
    response = mpt_client.post(
        f"/commerce/orders/{order_id}/complete",
        json={"template": {"id": template_id}},
    )
    response.raise_for_status()
    return response.json()


@wrap_http_error
def create_subscription(mpt_client, order_id, payload):
    response = mpt_client.post(
        f"/commerce/orders/{order_id}/subscriptions",
        json=payload,
    )
    response.raise_for_status()
    return response.json()


@wrap_http_error
def update_subscription(mpt_client, order_id, subscription_id, payload):
    response = mpt_client.put(
        f"/commerce/orders/{order_id}/subscriptions/{subscription_id}",
        json=payload,
    )
    response.raise_for_status()
    return response.json()
