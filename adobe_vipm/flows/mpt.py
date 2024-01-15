from adobe_vipm.flows.errors import MPTError


def get_seller(client, seller_id):
    response = client.get(f"/sellers/{seller_id}")
    if response.status_code == 200:
        return response.json()
    raise MPTError(response.json())


def get_buyer(client, buyer_id):
    response = client.get(f"/buyers/{buyer_id}")
    if response.status_code == 200:
        return response.json()
    raise MPTError(response.json())


def update_order(client, order_id, payload):
    response = client.put(
        f"/commerce/orders/{order_id}",
        json=payload,
    )
    if response.status_code == 200:
        return response.json()
    raise MPTError(response.json())


def querying_order(client, order_id, payload):
    response = client.post(
        f"/commerce/orders/{order_id}/query",
        json=payload,
    )
    if response.status_code == 200:
        return response.json()
    raise MPTError(response.json())


def fail_order(client, order_id, reason):
    response = client.post(
        f"/commerce/orders/{order_id}/fail",
        json={"reason": reason},
    )
    if response.status_code == 200:
        return response.json()
    raise MPTError(response.json())


def complete_order(client, order_id, template_id):
    response = client.post(
        f"/commerce/orders/{order_id}/complete",
        json={"template": {"id": template_id}},
    )
    if response.status_code == 200:
        return response.json()
    raise MPTError(response.json())


def create_subscription(client, order_id, payload):
    response = client.post(
        f"/commerce/orders/{order_id}/subscriptions",
        json=payload,
    )
    if response.status_code == 201:
        return response.json()
    raise MPTError(response.json())
