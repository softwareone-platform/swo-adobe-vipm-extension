import logging
from collections.abc import Mapping
from pprint import pformat
from typing import Annotated, Any

from django.conf import settings
from mpt_extension_sdk.core.extension import Extension
from mpt_extension_sdk.core.security import JWTAuth
from mpt_extension_sdk.mpt_http.base import MPTClient
from mpt_extension_sdk.mpt_http.mpt import get_webhook
from mpt_extension_sdk.runtime.djapp.conf import get_for_product
from ninja import Body

from adobe_vipm.flows.fulfillment import fulfill_order
from adobe_vipm.flows.validation import validate_order
from adobe_vipm.models import Error

logger = logging.getLogger(__name__)

ext = Extension()


def jwt_secret_callback(client: MPTClient, claims: Mapping[str, Any]) -> str:
    """
    Extracts JWT secret from the webhook.

    Args:
        client: MPT client.
        claims: JT claims to look for webhook id.

    Returns:
        JWT secret.
    """
    webhook = get_webhook(client, claims["webhook_id"])
    product_id = webhook["criteria"]["product.id"]
    return get_for_product(settings, "WEBHOOKS_SECRETS", product_id)


@ext.events.listener("orders")
def process_order_fulfillment(client: MPTClient, event) -> None:
    """Hook to process fulfillment order."""
    fulfill_order(client, event.data)


@ext.api.post(
    "/v1/orders/validate",
    response={
        200: dict,
        400: Error,
    },
    auth=JWTAuth(jwt_secret_callback),
)
def process_order_validation(request, order: Annotated[dict | None, Body()] = None):
    """API handler to process order validation http query."""
    try:
        validated_order = validate_order(request.client, order)
    except Exception as e:
        logger.exception("Unexpected error during validation")
        return 400, Error(
            id="VIPMG001",
            message=f"Unexpected error during validation: {e}.",
        )
    else:
        logger.debug("Validated order: %s", pformat(validated_order))
        return 200, validated_order
