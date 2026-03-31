import logging
from collections.abc import Awaitable, Callable
from importlib import import_module, metadata
from typing import Annotated

from fastapi import Depends, FastAPI, Request, Response

from mpt_extension_sdk_v6.api.router import create_non_task_route, create_task_route
from mpt_extension_sdk_v6.errors.runtime import ConfigError
from mpt_extension_sdk_v6.extension_app import ExtensionApp
from mpt_extension_sdk_v6.observability.bootstrap import ObservabilityBootstrap
from mpt_extension_sdk_v6.observability.config import ObservabilityConfig
from mpt_extension_sdk_v6.runtime.logging import correlation_id_ctx, setup_logging, task_id_ctx
from mpt_extension_sdk_v6.settings.runtime import RuntimeSettings, get_runtime_settings

logger = logging.getLogger(__name__)

_SDK_VERSION = metadata.version("mpt-extension-sdk-v6")


def load_extension_app(module_name: str) -> ExtensionApp:
    """Load the explicit extension app exported by the configured module.

    Args:
        module_name: Dotted Python module path that exports `ext_app`.

    Returns:
        The extension app exported by the module.

    Raises:
        ConfigError: If the module name is empty, the export is missing, or the
            exported object is not an `ExtensionApp`.
    """
    if not module_name:
        raise ConfigError("Extension app module cannot be empty")

    module = import_module(module_name)
    extension_app = getattr(module, "ext_app", None)
    if extension_app is None:
        raise ConfigError(f"Extension app module '{module_name}' must export 'ext_app'")
    if not isinstance(extension_app, ExtensionApp):
        raise ConfigError(f"Extension app module '{module_name}.ext_app' must be an ExtensionApp")
    return extension_app


def create_runtime_app(
    runtime_settings: Annotated[RuntimeSettings, Depends(get_runtime_settings)],
) -> FastAPI:
    """Create and configure the FastAPI application for the extension.

    Loads runtime settings, validates route consistency with `meta.yaml`, and
    registers all routes on the FastAPI instance.

    Returns:
        A fully configured `FastAPI` application.

    Raises:
        ConfigError: If a registered route is absent from `meta.yaml` or if
            the task flag does not match.
    """
    setup_logging(log_level=runtime_settings.log_level)
    observability_config = ObservabilityConfig.from_runtime_settings(runtime_settings)
    ObservabilityBootstrap.bootstrap(observability_config)
    extension_app = load_extension_app(runtime_settings.app_module)

    app = FastAPI(
        title="MPT Extension API",
        version=_SDK_VERSION,
        openapi_url="/bypass/openapi.json",
        docs_url="/bypass/docs",
        redoc_url="/bypass/redoc",
    )
    ObservabilityBootstrap.instrument_fastapi_app(app, observability_config)

    @app.middleware("http")
    async def correlation_id_middleware(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        correlation_id = request.headers.get("x-request-id", "")
        correlation_id_ctx.set(correlation_id)
        response = await call_next(request)
        response.headers["x-request-id"] = correlation_id
        return response

    @app.middleware("http")
    async def mpt_task_id_middleware(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        task_id = request.headers.get("mpt-task-Id", "")
        task_id_ctx.set(task_id)
        response = await call_next(request)
        response.headers["mpt-task-Id"] = task_id
        return response

    @app.get("/health", tags=["ops"])  # noqa: WPS430
    async def health() -> dict[str, str]:
        return {"status": "ok", "version": _SDK_VERSION}

    meta_event_map = {event.path: event.task for event in runtime_settings.meta_config.events}
    register_extension_routes(app, meta_event_map, extension_app)
    return app


def register_extension_routes(
    app: FastAPI,
    meta_event_map: dict[str, bool],
    extension_app: ExtensionApp,
) -> None:
    """Register all decorated handlers on the FastAPI app after validating meta.yaml.

    Args:
        app: The FastAPI application to register routes on.
        meta_event_map: Mapping of path to task flag from `meta.yaml`.
        extension_app: Extension app that owns the registered routes.

    Raises:
        ConfigError: If a handler path is absent from `meta.yaml` or the task
            flag mismatches.
    """
    for registered_route in extension_app.routes:
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
            router = create_task_route(
                registered_route.path,
                registered_route.handler,
                extension_app,
            )
        else:
            router = create_non_task_route(
                registered_route.path,
                registered_route.handler,
                extension_app,
            )
        app.include_router(router)
