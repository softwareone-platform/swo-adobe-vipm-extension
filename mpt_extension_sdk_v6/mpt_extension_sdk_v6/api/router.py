import logging
from collections.abc import Awaitable, Callable
from inspect import isawaitable
from typing import Annotated, Any

from fastapi import APIRouter, Depends, status
from mpt_extension_sdk_v6.api.schemas.events import Event, EventResponse, TaskEvent
from mpt_extension_sdk_v6.errors.mapping import map_exception_to_event_response
from mpt_extension_sdk_v6.errors.pipeline import CancelError, DeferError, FailError
from mpt_extension_sdk_v6.extension_app import ExtensionApp
from mpt_extension_sdk_v6.observability.tracing import (
    record_exception,
    start_event_span,
)
from mpt_extension_sdk_v6.pipeline.context import ExecutionContext
from mpt_extension_sdk_v6.pipeline.factory import build_context
from mpt_extension_sdk_v6.runtime.logging import object_ctx
from mpt_extension_sdk_v6.services.mpt_api_service import MPTAPIService, TasksService
from mpt_extension_sdk_v6.settings.runtime import RuntimeSettings, get_runtime_settings

TaskHandler = Callable[[TaskEvent, ExecutionContext], Awaitable[None] | None]
EventHandler = Callable[[Event, ExecutionContext], Awaitable[None] | None]

logger = logging.getLogger(__name__)


async def _run_handler(
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


def _get_tasks_service(
    runtime_settings: Annotated[RuntimeSettings, Depends(get_runtime_settings)],
) -> TasksService:
    return MPTAPIService.from_config(
        base_url=runtime_settings.mpt_api_base_url, api_token=runtime_settings.ext_api_key
    ).tasks


def create_task_route(
    path: str,
    handler: TaskHandler,
    extension_app: ExtensionApp,
) -> APIRouter:
    """Create a router for a task-based event handler.

    Args:
        path: The absolute URL path for this route.
        handler: The task event handler function.
        extension_app: The extension app.

    Returns:
        A configured `APIRouter` instance.
    """
    router = APIRouter()
    handler_logger = logging.getLogger(handler.__module__)

    @router.post(path, status_code=status.HTTP_200_OK, response_model=EventResponse)
    async def handle_task_event(
        event: TaskEvent,
        task_service: Annotated[TasksService, Depends(_get_tasks_service)],
    ) -> EventResponse:
        handler_logger.info("Received event (%s): %s", event.id, event.to_dict())
        object_ctx.set((event.object.object_type, event.object.id))
        with start_event_span(path, task_based=True, event=event) as span:
            handler_logger.info("Starting task %s", event.task.id)
            await task_service.start(event.task.id)
            try:
                context = await build_context(event, handler_logger)
                context = await extension_app.build_context(handler, context)
                await _run_handler(handler, event, context)
            except CancelError as error:
                record_exception(span, error)
                handler_logger.exception("Task %s cancelled", event.task.id, exc_info=error)
                await task_service.fail(event.task.id)
                return map_exception_to_event_response(error)
            except DeferError as error:
                record_exception(span, error)
                handler_logger.exception("Task %s rescheduled", event.task.id, exc_info=error)
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
                await task_service.fail(
                    event.task.id
                )  # REVIEW: should it be failed or rescheduled?
                return map_exception_to_event_response(error)

            handler_logger.info("Task %s completed successfully", event.task.id)
            await task_service.complete(event.task.id)
            return EventResponse.ok()

    return router


def create_non_task_route(
    path: str,
    handler: EventHandler,
    extension_app: ExtensionApp,
) -> APIRouter:
    """Create a FastAPI router for a non-task event handler.

    Unhandled exceptions are logged and re-raised, resulting in an HTTP 500
    response from FastAPI.

    Args:
        path: The absolute URL path for this route.
        handler: The event handler function.
        extension_app: The extension app.

    Returns:
        A configured `APIRouter` instance.
    """
    router = APIRouter()
    handler_logger = logging.getLogger(handler.__module__)

    @router.post(path, status_code=status.HTTP_200_OK, response_model=EventResponse)
    async def handle_event(event: Event) -> EventResponse:
        handler_logger.info("Received event (%s): %s", event.id, event.to_dict())
        object_ctx.set((event.object.object_type, event.object.id))
        with start_event_span(path, task_based=False, event=event) as span:
            try:
                context = await build_context(event, handler_logger)
                context = await extension_app.build_context(handler, context)
                await _run_handler(handler, event, context)
            except CancelError as error:
                record_exception(span, error)
                handler_logger.exception("Event (%s) failed", event.id, exc_info=error)
                return map_exception_to_event_response(error)
            except DeferError as error:
                record_exception(span, error)
                handler_logger.exception("Event (%s) failed", event.id, exc_info=error)
                return map_exception_to_event_response(error)
            except FailError as error:
                record_exception(span, error)
                handler_logger.exception("Event (%s) failed", event.id, exc_info=error)
                return map_exception_to_event_response(error)
            except Exception as error:
                record_exception(span, error)
                handler_logger.exception("Unhandled error %s", exc_info=error)
                return map_exception_to_event_response(error)

            return EventResponse.ok()

    return router
