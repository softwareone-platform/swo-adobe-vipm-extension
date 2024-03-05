from typing import Any, Mapping

from django.conf import settings
from ninja import Body
from swo.mpt.extensions.core import Extension, JWTAuth

from adobe_vipm.flows.fulfillment import fulfill_order
from adobe_vipm.flows.validation import validate_order
from adobe_vipm.models import Error

ext = Extension()


def jwt_secret_callback(claims: Mapping[str, Any]) -> str:
    secret = settings.EXTENSION_CONFIG["WEBHOOK_SECRET"]
    return secret


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
        return 200, validate_order(request.client, order)
    except Exception as e:
        return 400, Error(
            id="VIPMG001",
            message=f"Unexpected error during validation: {str(e)}.",
        )
