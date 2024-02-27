from ninja import Body
from swo.mpt.extensions.core import Extension

from adobe_vipm.flows.fulfillment import fulfill_order
from adobe_vipm.flows.validation import validate_order
from adobe_vipm.models import Error

ext = Extension()


@ext.events.listener("orders")
def process_order_fulfillment(client, event):
    fulfill_order(client, event.data)


@ext.api.post(
    "/v1/orders/validate",
    response={
        200: dict,
        400: Error,
    },
)
def process_order_validation(request, order: dict = Body(None)):
    try:
        return 200, validate_order(request.client, order)
    except Exception as e:
        return 400, Error(
            id="VIPMG001",
            message=f"Unexpected error during validation: {str(e)}.",
        )
