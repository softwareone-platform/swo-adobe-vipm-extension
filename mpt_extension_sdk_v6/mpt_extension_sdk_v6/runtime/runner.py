from pathlib import Path

import uvicorn
from fastapi import FastAPI
from mrok.agent import ziticorn

from mpt_extension_sdk_v6.runtime.app import create_runtime_app
from mpt_extension_sdk_v6.runtime.bootstrap.registration import register_instance
from mpt_extension_sdk_v6.runtime.logging import setup_logging
from mpt_extension_sdk_v6.settings.runtime import get_runtime_settings


def run_extension(*, local: bool) -> None:
    """Run the extension in local Uvicorn mode or production Ziticorn mode.

    Args:
        local: When `True`, run with Uvicorn for local development;
            otherwise run with Ziticorn for OpenZiti connectivity.
    """
    settings = get_runtime_settings()
    setup_logging(log_level=settings.log_level)
    app = create_runtime_app(settings)
    if local:
        run_fastapi(
            app,
            host=settings.local_host,
            port=settings.local_port,
            reload=settings.local_reload,
            workers=settings.local_workers,
        )
        return

    register_instance(settings=settings)
    run_ziti(
        app,
        settings.identity_file_path,
        reload=settings.ziti_reload,
        workers=settings.ziti_workers,
    )


def run_ziti(
    app: FastAPI,
    identity_file_path: Path | str,
    *,
    reload: bool,
    workers: int,
) -> None:
    """Start the extension with Ziticorn for OpenZiti network connectivity.

    Args:
        app: ASGI application instance.
        identity_file_path: Path to the persisted Ziti identity JSON file.
        reload: Enable auto-reload on code changes.
        workers: Number of worker processes.
    """
    ziticorn.run(
        app,
        str(identity_file_path),
        server_reload=reload,
        server_workers=workers,
        ziti_load_timeout_ms=10000,
    )


def run_fastapi(
    app: FastAPI,
    host: str,
    port: int,
    *,
    reload: bool,
    workers: int,
) -> None:
    """Start the extension with Uvicorn for local development.

    Args:
        app: ASGI application instance.
        host: Host address to bind to.
        port: TCP port to listen on.
        reload: Enable auto-reload on code changes.
        workers: Number of worker processes.
    """
    uvicorn.run(app, host=host, port=port, reload=reload, workers=workers)
