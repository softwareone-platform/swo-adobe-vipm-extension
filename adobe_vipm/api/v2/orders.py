import logging

from mpt_api_client.models import Model
from mpt_extension_sdk_v6.api.router import route, task_route
from mpt_extension_sdk_v6.api.schemas.events import Event, TaskEvent
from mpt_extension_sdk_v6.errors.pipeline import CancelError, DeferError, FailError
from mpt_extension_sdk_v6.pipeline.context import ExecutionContext
from requests import RequestException

from adobe_vipm.flows.pipelines.fulfillment.purchase import PurchasePipeline

logger = logging.getLogger(__name__)


@task_route("/events/orders/purchase", name="orders-purchase")
async def handle_purchase_order(event: TaskEvent, context: ExecutionContext[Model]) -> None:
    """Handle a purchase order event."""
    logger.info("Processing purchase event id=%s", event.id)
    logger.info("-" * 24)
    logger.info("event: %s", event)
    logger.info("extra: %s", event.__pydantic_extra__)
    logger.info("-" * 24)
    logger.info("context: %s", context)
    context.model = context.mpt_api_service.orders.get(event.object.id)
    if context.model.type != "Purchase":
        raise CancelError("Unsupported event. Only purchase orders are supported")

    try:
        await PurchasePipeline().execute(context)
    except RequestException as error:
        logger.exception("Transient error during purchase processing")
        raise DeferError("Transient error during event processing", delay_seconds=100) from error
    except Exception as error:
        logger.exception("Unexpected error during purchase processing")
        raise FailError("Server error") from error


@route("/events/orders/change", name="orders-change")
def handle_change_order(event: Event, context: ExecutionContext[Model]) -> None:
    """Handle a change order event.

    Args:
        event: The incoming task event payload.
        context: The SDK-provided execution context.
    """
    logger.info("Processing change order id=%s object_id=%s", event.id, event.object.id)
    logger.info("-" * 24)
    logger.info("event: %s", event)
    logger.info("-" * 24)
    logger.info("context: %s", context)
