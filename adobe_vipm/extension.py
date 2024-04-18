import logging
from pprint import pformat
from typing import Any, Mapping

from django.conf import settings
from ninja import Body
from swo.mpt.client import MPTClient
from swo.mpt.extensions.core import Extension, JWTAuth
from swo.mpt.extensions.runtime.djapp.conf import get_for_product

from adobe_vipm.flows.fulfillment import fulfill_order
from adobe_vipm.flows.mpt import get_webhook
from adobe_vipm.flows.validation import validate_order
from adobe_vipm.models import Error

logger = logging.getLogger(__name__)

ext = Extension()


def jwt_secret_callback(client: MPTClient, claims: Mapping[str, Any]) -> str:
    webhook = get_webhook(client, claims["webhook_id"])
    criterias = {criteria["key"]: criteria["value"] for criteria in webhook["criteria"]}
    product_id = criterias["product.id"]
    return get_for_product(settings, "WEBHOOK_SECRET", product_id)


@ext.events.listener("orders")
def process_order_fulfillment(client, event):
    fulfill_order(client, event.data)


@ext.api.post(
    "/v1/orders/validate",
    response={
        200: dict,
        400: Error,
    },
    auth=JWTAuth(jwt_secret_callback),
)
def process_order_validation(request, order: dict = Body(None)):
    try:
        validated_order = validate_order(request.client, order)
        logger.debug(f"Validated order: {pformat(validated_order)}")
        return 200, validated_order
    except Exception as e:
        logger.exception("Unexpected error during validation")
        return 400, Error(
            id="VIPMG001",
            message=f"Unexpected error during validation: {str(e)}.",
        )
