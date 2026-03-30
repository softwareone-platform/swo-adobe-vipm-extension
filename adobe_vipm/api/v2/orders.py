import logging

from mpt_extension_sdk.api.models.events import Event, TaskEvent
from mpt_extension_sdk.errors.pipeline import CancelError
from mpt_extension_sdk.extension_app import ExtensionRouter

from adobe_vipm.flows.context import AdobeOrderContext
from adobe_vipm.flows.pipelines.fulfillment.purchase import PurchasePipeline

logger = logging.getLogger(__name__)
orders_router = ExtensionRouter(prefix="/events/orders")


@orders_router.task_route(
    "/purchase",
    name="orders-purchase",
    event="platform.commerce.order.created",
    condition="eq(product.id,PRD-5516-5707)",
)
async def handle_purchase_order(event: TaskEvent, context: AdobeOrderContext) -> None:
    """Handle a purchase order event."""
    logger.info("Processing purchase event id=%s", event.id)
    if context.order.type != "Purchase":
        raise CancelError("Unsupported event. Only purchase orders are supported")

    if context.order.status != "Processing":
        raise CancelError("Order status is not processing.")

    await PurchasePipeline().execute(context)


@orders_router.route(
    "/change",
    name="orders-change",
    event="platform.commerce.order.status_changed",
    condition="and(eq(status,Processing),eq(product.id,PRD-5516-5707))",
)
async def handle_change_order(event: Event, context: AdobeOrderContext) -> None:
    """Handle a change order event.

    Args:
        event: The incoming task event payload.
        context: The SDK-provided execution context.
    """
    logger.info("Processing change order id=%s object_id=%s", event.id, event.object.id)
    if context.order.status != "Processing":
        raise CancelError("Order status is not processing.")

    await PurchasePipeline().execute(context)
