from fastapi import APIRouter, FastAPI

from adobe_vipm.mrok.api.v2.orders import router as orders_router
from adobe_vipm.mrok.config import RuntimeSettings, load_runtime_settings
from adobe_vipm.mrok.logging import setup_logging


def load_settings() -> RuntimeSettings:
    """Load FastAPI runtime settings.

    Returns:
        Runtime settings object.
    """
    return load_runtime_settings()


def create_app() -> FastAPI:
    """Create FastAPI application instance.

    Returns:
        Configured FastAPI application.
    """
    app = FastAPI(
        title="SWO Adobe VIPM Extension API",
        version="6.0.0",
        openapi_url="/public/v2/openapi.json",
        docs_url="/public/v2/docs",
        redoc_url="/public/v2/redoc",
    )

    api_v2 = APIRouter(prefix="/public/v2")
    api_v2.include_router(orders_router)
    app.include_router(api_v2)

    return app


def start_up() -> FastAPI:
    """Initialize runtime settings and FastAPI app.

    Returns:
        FastAPI application.
    """
    setup_logging()
    load_settings()
    return create_app()


app = start_up()
