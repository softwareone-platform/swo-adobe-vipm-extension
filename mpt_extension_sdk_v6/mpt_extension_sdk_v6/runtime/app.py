import logging
from collections.abc import Awaitable, Callable
from importlib import import_module, metadata

from fastapi import FastAPI, Request, Response

from mpt_extension_sdk_v6.api.router import create_non_task_route, create_task_route
from mpt_extension_sdk_v6.errors.runtime import ConfigError
from mpt_extension_sdk_v6.extension_app import ExtensionApp
from mpt_extension_sdk_v6.observability.bootstrap import ObservabilityBootstrap
from mpt_extension_sdk_v6.observability.config import ObservabilityConfig
from mpt_extension_sdk_v6.runtime.logging import correlation_id_ctx, setup_logging, task_id_ctx
from mpt_extension_sdk_v6.settings.runtime import RuntimeSettings

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


def create_runtime_app(runtime_settings: RuntimeSettings) -> FastAPI:
    """Create and configure the FastAPI application for the extension.

    Loads runtime settings, derives metadata from the extension app, and
    registers all routes on the FastAPI instance.

    Returns:
        A fully configured `FastAPI` application.

    """
    setup_logging(runtime_settings.log_level, runtime_settings.extension_package)
    observability_config = ObservabilityConfig.from_runtime_settings(runtime_settings)
    ObservabilityBootstrap.bootstrap(observability_config)
    extension_app = load_extension_app(runtime_settings.app_module)

    app = _create_fastapi_app()
    _configure_observability(app, observability_config)
    _configure_middlewares(app)
    _register_builtin_routes(app)
    register_extension_routes(app, extension_app)
    return app


def _create_fastapi_app() -> FastAPI:
    """Create the base FastAPI application for the extension runtime."""
    return FastAPI(
        title="MPT Extension API",
        description="MPT Extension API",
        version=_SDK_VERSION,
        openapi_url="/bypass/openapi.json",
        docs_url="/bypass/docs",
        redoc_url="/bypass/redoc",
    )


def _configure_observability(app: FastAPI, observability_config: ObservabilityConfig) -> None:
    """Attach runtime observability integrations to the FastAPI app."""
    ObservabilityBootstrap.instrument_fastapi_app(app, observability_config)


def _configure_middlewares(app: FastAPI) -> None:
    """Register request middlewares used by the extension runtime."""

    @app.middleware("http")
    async def correlation_id_middleware(  # noqa: WPS430
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        correlation_id = request.headers.get("x-request-id", "")
        correlation_id_ctx.set(correlation_id)
        response = await call_next(request)
        response.headers["x-request-id"] = correlation_id
        return response

    @app.middleware("http")
    async def mpt_task_id_middleware(  # noqa: WPS430
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        task_id = request.headers.get("mpt-task-id", "")
        task_id_ctx.set(task_id)
        response = await call_next(request)
        response.headers["mpt-task-id"] = task_id
        return response


def _register_builtin_routes(app: FastAPI) -> None:
    """Register built-in operational routes exposed by the runtime."""

    @app.get("/health", tags=["ops"])
    async def health() -> dict[str, str]:  # noqa: WPS430
        return {"status": "ok", "version": _SDK_VERSION}


def register_extension_routes(app: FastAPI, extension_app: ExtensionApp) -> None:
    """Register all decorated handlers on the FastAPI app.

    Args:
        app: The FastAPI application to register routes on.
        extension_app: Extension app that owns the registered routes.
    """
    for registered_route in extension_app.routes:
        if registered_route.task_based:
            router = create_task_route(
                registered_route.path, registered_route.callback, extension_app
            )
        else:
            router = create_non_task_route(
                registered_route.path, registered_route.callback, extension_app
            )
        app.include_router(router)
