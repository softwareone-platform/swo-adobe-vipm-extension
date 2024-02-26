import os

ACCOUNTS_FOLDER = os.path.join(
    os.path.dirname(__file__),
    "data",
    "accounts",
)


AGREEMENTS_FOLDER = os.path.join(
    os.path.dirname(__file__),
    "data",
    "agreements",
)


LICENSEES_FOLDER = os.path.join(
    os.path.dirname(__file__),
    "data",
    "licensees",
)


ORDERS_FOLDER = os.path.join(
    os.path.dirname(__file__),
    "data",
    "orders",
)

SUBSCRIPTIONS_FOLDER = os.path.join(
    os.path.dirname(__file__),
    "data",
    "subscriptions",
)


BUYERS_FOLDER = os.path.join(
    os.path.dirname(__file__),
    "data",
    "buyers",
)


SELLERS_FOLDER = os.path.join(
    os.path.dirname(__file__),
    "data",
    "sellers",
)


WEBHOOK_ENDPOINT = "http://localhost:8080/v1/orders/validate"
WEBHOOK_JWT_SECRET = "change-me"
WEBHOOK_ID = "WBH-1234-5678"
