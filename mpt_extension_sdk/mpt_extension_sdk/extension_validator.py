from inspect import getattr_static

from mpt_extension_sdk.errors.runtime import ConfigError
from mpt_extension_sdk.pipeline import ContextAdapter, ExecutionContext
from mpt_extension_sdk.services.mpt_api_service.api_service import MPTAPIService


class ExtensionValidator:
    """Validation helpers for the `ExtensionApp` contract."""

    @classmethod
    def validate_service_type(cls, service_type: type[object]) -> None:
        """Validate that the configured API service type is supported."""
        if not issubclass(service_type, MPTAPIService):
            raise TypeError("mpt_api_service_type must inherit from MPTAPIService")

    @classmethod
    def validate_context_type(
        cls,
        context_type: type[object] | None,
        base_context_type: type[ExecutionContext],
    ) -> None:
        """Validate a configured custom context adapter type."""
        if context_type is None:
            return
        if not issubclass(context_type, base_context_type):
            raise TypeError(
                f"Configured context type '{context_type.__name__}' must inherit from "
                f"'{base_context_type.__name__}'"
            )
        if not issubclass(context_type, ContextAdapter):
            raise TypeError(
                f"Configured context type '{context_type.__name__}' must implement "
                f"'{ContextAdapter.__name__}'"
            )
        builder = getattr_static(context_type, "from_context", None)
        if not isinstance(builder, classmethod):
            raise ConfigError(
                f"Configured context type '{context_type.__name__}' must define classmethod "
                "'from_context'"
            )

    @classmethod
    def validate_route_uniqueness(
        cls,
        *,
        route_name: str,
        route_path: str,
        route_event: str,
        routes: list[object],
    ) -> None:
        """Validate that a route name and path are unique within a route list."""
        if any(getattr(route, "name", None) == route_name for route in routes):
            raise ValueError(f"Route name '{route_name}' is already registered")
        if any(getattr(route, "path", None) == route_path for route in routes):
            raise ValueError(f"Route path '{route_path}' is already registered")
        if any(getattr(route, "event", None) == route_event for route in routes):
            raise ValueError(f"Route event '{route_event}' is already registered")
