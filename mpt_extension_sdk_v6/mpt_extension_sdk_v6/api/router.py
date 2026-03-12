import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from inspect import isawaitable
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Request, status
from mpt_extension_sdk_v6.api.schemas.events import Event, EventResponse, TaskEvent
from mpt_extension_sdk_v6.errors.mapping import map_exception_to_event_response
from mpt_extension_sdk_v6.errors.pipeline import CancelError, DeferError, FailError
from mpt_extension_sdk_v6.pipeline.context import ExecutionContext
from mpt_extension_sdk_v6.pipeline.factory import build_context
from mpt_extension_sdk_v6.runtime.logging import object_ctx, task_id_ctx
from mpt_extension_sdk_v6.services.mpt_api_service import MPTAPIService, TasksService
from mpt_extension_sdk_v6.settings.runtime import RuntimeSettings, get_runtime_settings

TaskHandler = Callable[[TaskEvent, ExecutionContext], Awaitable[None] | None]
EventHandler = Callable[[Event, ExecutionContext], Awaitable[None] | None]


@dataclass(frozen=True)
class RegisteredRoute:
    """Metadata for a route registered via a decorator."""

    name: str
    path: str
    task_based: bool
    handler: Callable[..., Awaitable[None] | None]


_ROUTE_PREFIX: list[str] = [""]
_REGISTERED_ROUTES: list[RegisteredRoute] = []


def set_route_prefix(prefix: str) -> None:
    """Set the URL prefix prepended to all registered route paths.

    Args:
        prefix: The prefix string (e.g. ``"/api/v2"``).
    """
    cleaned = prefix.strip()
    if not cleaned:
        _ROUTE_PREFIX[0] = ""
        return
    normalized = cleaned if cleaned.startswith("/") else f"/{cleaned}"
    _ROUTE_PREFIX[0] = normalized.rstrip("/")


def reset_routes() -> None:
    """Clear all registered routes.

    Primarily used by the runtime before reloading handler modules.
    """
    _REGISTERED_ROUTES.clear()


def get_registered_routes() -> list[RegisteredRoute]:
    """Return a snapshot of all currently registered routes.

    Returns:
        A copy of the registered route list.
    """
    return list(_REGISTERED_ROUTES)


def task_route(path: str, name: str) -> Callable[[TaskHandler], TaskHandler]:
    """Decorator that registers a handler for a task-based event.

    Args:
        path: Route path relative to the SDK prefix (e.g. ``"/events/orders/purchase"``).
        name: Unique human-readable route name used for logging and validation.

    Returns:
        A decorator that registers the handler and returns it unchanged.
    """

    def decorator(handler: TaskHandler) -> TaskHandler:
        _register_route(name=name, path=path, task_based=True, handler=handler)
        return handler

    return decorator


def route(path: str, name: str) -> Callable[[EventHandler], EventHandler]:
    """Decorator that registers a handler for a non-task event.

    Args:
        path: Route path relative to the SDK prefix.
        name: Unique human-readable route name.

    Returns:
        A decorator that registers the handler and returns it unchanged.
    """

    def decorator(handler: EventHandler) -> EventHandler:
        _register_route(name=name, path=path, task_based=False, handler=handler)
        return handler

    return decorator


def _register_route(
    *,
    name: str,
    path: str,
    task_based: bool,
    handler: Callable[..., Awaitable[None] | None],
) -> None:
    """Append a route to the internal registry after normalising the path.

    Args:
        name: Unique route name.
        path: Raw route path (will be normalised with the current prefix).
        task_based: Whether this is a task-based event route.
        handler: The handler callable to associate with this route.

    Raises:
        ValueError: If the name or normalised path is already registered.
    """
    normalized_path = _normalize_path(path)
    if any(registered.name == name for registered in _REGISTERED_ROUTES):
        raise ValueError(f"Route name '{name}' is already registered")
    if any(registered.path == normalized_path for registered in _REGISTERED_ROUTES):
        raise ValueError(f"Route path '{normalized_path}' is already registered")

    _REGISTERED_ROUTES.append(
        RegisteredRoute(
            name=name,
            path=normalized_path,
            task_based=task_based,
            handler=handler,
        )
    )


def _normalize_path(path: str) -> str:
    """Prepend the current route prefix and normalize leading slashes.

    Args:
        path: The raw route path.

    Returns:
        The normalized absolute path string.

    Raises:
        ValueError: If ``path`` is empty.
    """
    base = path.strip()
    if not base:
        raise ValueError("Route path cannot be empty")
    suffix = base if base.startswith("/") else f"/{base}"
    prefix = _ROUTE_PREFIX[0]
    if not prefix:
        return suffix
    return f"{prefix}{suffix}" if suffix != "/" else prefix


async def _run_handler(
    event_handler: Callable[..., Awaitable[None] | None],
    event: Any,
    context: ExecutionContext,
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
    """FastAPI dependency that provides a :class:`TasksService` authenticated with the runtime key.

    Returns:
        A :class:`TasksService` instance using ``SDK_EXTENSION_API_KEY``.
    """
    return MPTAPIService.from_config(
        base_url=runtime_settings.mpt_api_base_url, api_token=runtime_settings.ext_api_key
    ).tasks


def create_task_route(path: str, handler: TaskHandler) -> APIRouter:
    """Create a router for a task-based event handler.

    The router manages the full task lifecycle (start → complete / reschedule)
    using the runtime API key, and maps handler exceptions to
    :class:`EventResponse` via :func:`map_exception_to_event_response`.

    Args:
        path: The absolute URL path for this route.
        handler: The task event handler function.

    Returns:
        A configured :class:`APIRouter` instance.
    """
    router = APIRouter()
    handler_logger = logging.getLogger(handler.__module__)

    @router.post(path, status_code=status.HTTP_200_OK, response_model=EventResponse)
    async def handle_task_event(
        event: TaskEvent,
        request: Request,
        task_service: Annotated[TasksService, Depends(_get_tasks_service)],
    ) -> EventResponse:
        task_id_ctx.set(request.headers.get("MPT-Task-Id", ""))
        object_ctx.set((event.object.object_type, event.object.id))
        context = await build_context(event, handler_logger)
        handler_logger.info("Starting task %s", event.task.id)
        # REVIEW: handle task exceptions
        await task_service.start(event.task.id)
        try:
            await _run_handler(handler, event, context)
        except CancelError as error:
            handler_logger.exception("Task %s cancelled", event.task.id, exc_info=error)
            await task_service.fail(event.task.id)
            return map_exception_to_event_response(error)
        except DeferError as error:
            handler_logger.exception("Task %s rescheduled", event.task.id, exc_info=error)
            await task_service.reschedule(event.task.id)
            return map_exception_to_event_response(error)
        except FailError as error:
            handler_logger.exception("Task %s failed", event.task.id, exc_info=error)
            await task_service.fail(event.task.id)
            return map_exception_to_event_response(error)
        except Exception as error:
            handler_logger.exception("Task %s failed", event.task.id, exc_info=error)
            await task_service.fail(event.task.id)  # REVIEW: should it be failed or rescheduled?
            return map_exception_to_event_response(error)

        handler_logger.info("Task %s completed successfully", event.task.id)
        await task_service.complete(event.task.id)
        return EventResponse.ok()

    return router


def create_non_task_route(path: str, handler: EventHandler) -> APIRouter:
    """Create a FastAPI router for a non-task event handler.

    Unhandled exceptions are logged and re-raised, resulting in an HTTP 500
    response from FastAPI.

    Args:
        path: The absolute URL path for this route.
        handler: The event handler function.

    Returns:
        A configured :class:`APIRouter` instance.
    """
    router = APIRouter()
    handler_logger = logging.getLogger(handler.__module__)

    @router.post(path, status_code=status.HTTP_200_OK, response_model=EventResponse)
    async def handle_event(event: Event) -> EventResponse:
        context = await build_context(event, handler_logger)
        try:
            await _run_handler(handler, event, context)
        except (CancelError, DeferError, FailError) as error:
            handler_logger.exception("Event (%s) failed", event.id, exc_info=error)
            return map_exception_to_event_response(error)
        except Exception as error:
            handler_logger.exception("Unhandled error %s failed", exc_info=error)
            return map_exception_to_event_response(error)

        return EventResponse.ok()

    return router
