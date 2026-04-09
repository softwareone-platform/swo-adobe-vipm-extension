import logging
from collections.abc import Awaitable, Callable
from inspect import isawaitable
from typing import Annotated, Any

from fastapi import APIRouter, Depends, status
from mpt_extension_sdk_v6.api.models.events import Event, EventResponse, TaskEvent
from mpt_extension_sdk_v6.errors.mapping import map_exception_to_event_response
from mpt_extension_sdk_v6.errors.pipeline import CancelError, DeferError, FailError
from mpt_extension_sdk_v6.extension_app import ExtensionApp
from mpt_extension_sdk_v6.observability.tracing import (
    get_business_attributes,
    record_exception,
    set_attributes,
    start_event_span,
)
from mpt_extension_sdk_v6.pipeline import ExecutionContext, build_context
from mpt_extension_sdk_v6.runtime.logging import set_event_context
from mpt_extension_sdk_v6.services.mpt_api_service.api_service import MPTAPIService
from mpt_extension_sdk_v6.services.mpt_api_service.task import TaskService
from mpt_extension_sdk_v6.settings.runtime import RuntimeSettings, get_runtime_settings

TaskHandler = Callable[[TaskEvent, ExecutionContext], Awaitable[None] | None]
EventHandler = Callable[[Event, ExecutionContext], Awaitable[None] | None]

logger = logging.getLogger(__name__)


def create_task_route(
    path: str, task_handler: TaskHandler, extension_app: ExtensionApp
) -> APIRouter:
    """Create a router for a task-based event handler.

    Args:
        path: The absolute URL path for this route.
        task_handler: The task event handler function.
        extension_app: The extension app.

    Returns:
        A configured `APIRouter` instance.
    """
    router = APIRouter()
    handler_logger = logging.getLogger(task_handler.__module__)

    @router.post(path, status_code=status.HTTP_200_OK, response_model=EventResponse)
    async def handle_task_event(
        event: TaskEvent,
        task_service: Annotated[TaskService, Depends(get_tasks_service)],
    ) -> EventResponse:
        handler_logger.info("Received event (%s): %s", event.id, event.to_dict())
        set_event_context(task_id=event.task.id)
        context = await build_context(
            event,
            handler_logger,
            mpt_api_service_type=extension_app.mpt_api_service_type,
        )
        context = extension_app.build_context(context)
        with start_event_span(path, task_based=True, event=event) as span:
            business_attributes = get_business_attributes(context)
            set_event_context(
                order_id=str(business_attributes.get("order.id", "")),
                agreement_id=str(business_attributes.get("agreement.id", "")),
            )
            set_attributes(span, business_attributes)
            handler_logger.info("Starting task %s", event.task.id)
            await task_service.start(event.task.id)
            try:
                await run_handler(task_handler, event, context)
            except CancelError as error:
                record_exception(span, error)
                handler_logger.info("Task %s cancelled", event.task.id)
                await task_service.fail(event.task.id)
                return map_exception_to_event_response(error)
            except DeferError as error:
                record_exception(span, error)
                handler_logger.info("Task %s rescheduled", event.task.id)
                await task_service.reschedule(event.task.id)
                return map_exception_to_event_response(error)
            except FailError as error:
                record_exception(span, error)
                handler_logger.exception("Task %s failed", event.task.id, exc_info=error)
                await task_service.fail(event.task.id)
                return map_exception_to_event_response(error)
            except Exception as error:
                record_exception(span, error)
                handler_logger.exception("Task %s failed", event.task.id, exc_info=error)
                # REVIEW: should it be failed or rescheduled?
                await task_service.fail(event.task.id)
                return map_exception_to_event_response(error)

            handler_logger.info("Task %s completed successfully", event.task.id)
            await task_service.complete(event.task.id)
            return EventResponse.ok()

    return router


def create_non_task_route(  # noqa: WPS213
    path: str,
    event_callback: Callable[[Event, ExecutionContext], Awaitable[None] | None],
    extension_app: ExtensionApp,
) -> APIRouter:  # noqa: WPS213
    """Create a FastAPI router for a non-task event handler.

    Args:
        path: The absolute URL path for this route.
        event_callback: The event handler function.
        extension_app: The extension app.

    Returns:
        A configured `APIRouter` instance.
    """
    router = APIRouter()
    handler_logger = logging.getLogger(event_callback.__module__)

    @router.post(path, status_code=status.HTTP_200_OK, response_model=EventResponse)
    async def handle_event(event: Event) -> EventResponse:  # noqa: WPS430,WPS213
        handler_logger.info("Received event (%s): %s", event.id, event.to_dict())
        set_event_context()
        context = await build_context(
            event,
            handler_logger,
            mpt_api_service_type=extension_app.mpt_api_service_type,
        )
        context = extension_app.build_context(context)
        with start_event_span(path, task_based=False, event=event) as span:
            business_attributes = get_business_attributes(context)
            set_event_context(
                order_id=str(business_attributes.get("order.id", "")),
                agreement_id=str(business_attributes.get("agreement.id", "")),
            )
            set_attributes(span, business_attributes)
            try:  # noqa: WPS225
                await run_handler(event_callback, event, context)
            except CancelError as error:
                record_exception(span, error)
                handler_logger.info("Event (%s) canceled", event.id)
                return map_exception_to_event_response(error)
            except DeferError as error:
                record_exception(span, error)
                handler_logger.info("Event (%s) rescheduled", event.id)
                return map_exception_to_event_response(error)
            except FailError as error:
                record_exception(span, error)
                handler_logger.exception("Event (%s) failed", event.id, exc_info=error)
                return map_exception_to_event_response(error)
            except Exception as error:
                record_exception(span, error)
                handler_logger.exception("Unhandled error", exc_info=error)
                return map_exception_to_event_response(error)

            return EventResponse.ok()

    return router


def get_tasks_service(
    runtime_settings: Annotated[RuntimeSettings, Depends(get_runtime_settings)],
) -> TaskService:
    """Return the task service authenticated with the extension token.

    Task lifecycle operations are part of the extension runtime contract with
    the platform, so they use the extension API key rather than the
    Marketplace API token used by business services.
    """
    return MPTAPIService.from_config(
        base_url=runtime_settings.mpt_api_base_url, api_token=runtime_settings.ext_api_key
    ).tasks


async def run_handler(
    event_handler: Callable[..., Awaitable[None] | None], event: Any, context: ExecutionContext
) -> None:
    """Invoke a handler and await the result if it is a coroutine.

    Args:
        event_handler: The handler function to invoke.
        event: The event payload.
        context: The execution context to pass to the handler.
    """
    handler_result = event_handler(event, context)
    if isawaitable(handler_result):
        await handler_result
