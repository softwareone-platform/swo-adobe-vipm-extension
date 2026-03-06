import logging
from typing import Annotated

from fastapi import APIRouter, Depends, Header
from requests import RequestException

from adobe_vipm.adobe.errors import AdobeError
from adobe_vipm.flows.constants import OrderType
from adobe_vipm.flows.fulfillment import fulfill_order
from adobe_vipm.mrok.api.schemas.events import Event, EventResponse
from adobe_vipm.mrok.clients import get_mpt_client
from adobe_vipm.mrok.config import RuntimeSettings, load_runtime_settings

logger = logging.getLogger(__name__)

router = APIRouter(tags=["orders"])

SettingsDependency = Annotated[RuntimeSettings, Depends(load_runtime_settings)]
HeaderTaskId = Header(default=None, alias="MPT-Task-Id")


@router.post("/orders", response_model=EventResponse)
def process_orders_events(
    event: Event,
    mpt_task_id: str | None = HeaderTaskId,
    settings: SettingsDependency = None,
):
    """Handle purchase order task-based events.

    Args:
        event: Event payload.
        settings: Runtime settings.
        mpt_task_id: Task identifier header.

    Returns:
        Event response payload.
    """
    logger.info("Processing event id: %s", event.id)

    if not mpt_task_id:
        return EventResponse(response="Cancel", cancel_reason="Missing MPT-Task-Id header")

    order = _fetch_order(event.object.id, settings)
    if order["type"] != OrderType.PURCHASE:
        return EventResponse(
            response="Cancel",
            cancel_reason="Unsupported event. Only purchase orders are supported",
        )

    try:
        fulfill_order(get_mpt_client(settings), order)
    except (RequestException, AdobeError):
        logger.exception("Transient error during event processing")
        return EventResponse(response="Defer", defer_delay="PT120M")
    except Exception:
        logger.exception("Unexpected error during event processing")
        return EventResponse(response="Cancel", cancel_reason="Server error")

    return EventResponse(response="OK")


def _fetch_order(order_id: str, settings: SettingsDependency) -> dict:
    """Fetch order object from MPT API.

    Args:
        settings: Runtime settings.
        order_id: Order identifier.

    Returns:
        Order payload.
    """
    response = get_mpt_client(settings).get(f"/commerce/orders/{order_id}")
    response.raise_for_status()
    return response.json()
