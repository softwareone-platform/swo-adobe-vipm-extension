import logging
import sys
import uuid
from collections.abc import Awaitable, Callable
from importlib import import_module, metadata

from fastapi import FastAPI, Request, Response

from mpt_extension_sdk_v6.api.router import (
    create_non_task_route,
    create_task_route,
    get_registered_routes,
    reset_routes,
    set_route_prefix,
)
from mpt_extension_sdk_v6.errors.runtime import ConfigError
from mpt_extension_sdk_v6.runtime.logging import correlation_id_ctx, setup_logging
from mpt_extension_sdk_v6.settings.runtime import get_runtime_settings

logger = logging.getLogger(__name__)

_SDK_VERSION = metadata.version("mpt-extension-sdk-v6")


def create_app_for_extension() -> FastAPI:
    """Create and configure the FastAPI application for the extension.

    Loads runtime settings, imports handler modules, validates route consistency
    with ``meta.yaml``, and registers all routes on the FastAPI instance.

    Returns:
        A fully configured :class:`FastAPI` application.

    Raises:
        ConfigError: If a registered route is absent from ``meta.yaml`` or if
            the task flag does not match.
    """
    runtime_settings = get_runtime_settings()
    setup_logging(log_level=runtime_settings.log_level)

    reset_routes()
    set_route_prefix(runtime_settings.route_prefix)
    _load_handlers(runtime_settings.handlers_modules)

    meta_event_map = {event.path: event.task for event in runtime_settings.meta_config.events}

    app = FastAPI(
        title="MPT Extension API",
        version=_SDK_VERSION,
        openapi_url="/bypass/openapi.json",
        docs_url="/bypass/docs",
        redoc_url="/bypass/redoc",
    )

    @app.middleware("http")
    async def correlation_id_middleware(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        correlation_id = request.headers.get("X-Request-ID", str(uuid.uuid4()))
        correlation_id_ctx.set(correlation_id)
        response = await call_next(request)
        response.headers["X-Request-ID"] = correlation_id
        return response

    @app.get("/health", tags=["ops"])  # noqa: WPS430
    async def health() -> dict[str, str]:
        return {"status": "ok", "version": _SDK_VERSION}

    _register_extension_routes(app, meta_event_map)
    return app


def _register_extension_routes(app: FastAPI, meta_event_map: dict[str, bool]) -> None:
    """Register all decorated handlers on the FastAPI app after validating meta.yaml.

    Args:
        app: The FastAPI application to register routes on.
        meta_event_map: Mapping of path to task flag from ``meta.yaml``.

    Raises:
        ConfigError: If a handler path is absent from ``meta.yaml`` or the task
            flag mismatches.
    """
    for registered_route in get_registered_routes():
        if registered_route.path not in meta_event_map:
            raise ConfigError(
                f"Route '{registered_route.name}' ({registered_route.path}) "
                f"is not declared in meta.yaml"
            )

        task_from_meta = meta_event_map[registered_route.path]
        if task_from_meta != registered_route.task_based:
            raise ConfigError(
                f"Route task flag mismatch for '{registered_route.name}': "
                f"meta.yaml task={task_from_meta}, "
                f"decorator task={registered_route.task_based}"
            )

        if task_from_meta:
            router = create_task_route(registered_route.path, registered_route.handler)
        else:
            router = create_non_task_route(registered_route.path, registered_route.handler)
        app.include_router(router)


def _load_handlers(handler_modules: list[str]) -> None:
    """Import handler modules, forcing re-execution of route decorators.

    Pops each module from ``sys.modules`` before importing so that decorator
    calls (``@task_route``, ``@route``) are always re-executed after
    ``reset_routes()``.

    Args:
        handler_modules: Dotted module names to import.
    """
    for module_name in handler_modules:
        sys.modules.pop(module_name, None)
        import_module(module_name)


app = create_app_for_extension()
