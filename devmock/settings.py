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

AUTHORIZATIONS_FOLDER = os.path.join(
    os.path.dirname(__file__),
    "data",
    "authorizations",
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


PRODUCTS_FOLDER = os.path.join(
    os.path.dirname(__file__),
    "data",
    "products",
)


ITEMS_FOLDER = os.path.join(
    os.path.dirname(__file__),
    "data",
    "items",
)

PRICELISTS_FOLDER = os.path.join(
    os.path.dirname(__file__),
    "data",
    "pricelists",
)

PRICELIST_ITEMS_FOLDER = os.path.join(
    os.path.dirname(__file__),
    "data",
    "pricelist_items",
)


LISTINGS_FOLDER = os.path.join(
    os.path.dirname(__file__),
    "data",
    "listings",
)


WEBHOOK_ENDPOINT = "http://localhost:8080/api/v1/orders/validate"
WEBHOOK_JWT_SECRET = os.environ.get("EXT_WEBHOOK_SECRET_1111_1111_1111", "change-me")
WEBHOOK_ID = "WBH-1234-5678"
