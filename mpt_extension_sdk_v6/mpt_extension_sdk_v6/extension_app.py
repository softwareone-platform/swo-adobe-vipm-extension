from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field, replace

from mpt_extension_sdk_v6.extension_validator import ExtensionValidator
from mpt_extension_sdk_v6.pipeline import (
    AgreementContext,
    ContextAdapter,
    ExecutionContext,
    OrderContext,
)
from mpt_extension_sdk_v6.runtime.models import MetaConfig, MetaEvent
from mpt_extension_sdk_v6.services.mpt_api_service.api_service import MPTAPIService

TaskHandler = Callable[..., Awaitable[None] | None]
EventHandler = Callable[..., Awaitable[None] | None]


@dataclass(frozen=True)
class RouteDefinition:
    """Explicit route definition owned by an extension application.

    Attributes:
        name: Human-readable unique route name.
        path: Route path relative to the runtime prefix.
        event: Platform event subscribed by the route.
        condition: Optional event condition expression.
        task_based: Whether the route handles task-backed events.
        callback: Callable invoked when the route receives an event.
    """

    name: str
    path: str
    event: str
    condition: str | None
    task_based: bool
    callback: Callable[..., Awaitable[None] | None]


@dataclass
class ExtensionRouter:
    """Explicit router object for extension event handlers.

    This object mirrors the role of FastAPI's `APIRouter`: it groups related
    routes under a shared prefix before they are included in an extension app.
    """

    prefix: str = ""
    _routes: list[RouteDefinition] = field(default_factory=list, init=False, repr=False)

    @property
    def routes(self) -> list[RouteDefinition]:
        """Return the registered route definitions."""
        return list(self._routes)

    def prefixed_routes(self, prefix: str) -> list[RouteDefinition]:
        """Return route definitions with the given prefix applied to each path."""
        return [self._with_prefix(prefix, route) for route in self._routes]

    def route(
        self, path: str, name: str, event: str, condition: str | None = None
    ) -> Callable[[EventHandler], EventHandler]:
        """Register a non-task event handler on the router.

        Args:
            path: Route path relative to the router prefix.
            name: Unique human-readable route name.
            event: Platform event subscribed by the route.
            condition: Optional condition expression.

        Returns:
            A decorator that registers the provided handler.
        """

        def decorator(event_handler: EventHandler) -> EventHandler:
            self._register_route(
                name=name,
                path=path,
                event=event,
                condition=condition,
                task_based=False,
                callback=event_handler,
            )
            return event_handler

        return decorator

    def task_route(
        self, path: str, name: str, event: str, condition: str | None = None
    ) -> Callable[[TaskHandler], TaskHandler]:
        """Register a task-based event handler on the router.

        Args:
            path: Route path relative to the router prefix.
            name: Unique human-readable route name.
            event: Platform event subscribed by the route.
            condition: Optional condition expression.

        Returns:
            A decorator that registers the provided handler.
        """

        def decorator(task_handler: TaskHandler) -> TaskHandler:
            self._register_route(
                name=name,
                path=path,
                event=event,
                condition=condition,
                task_based=True,
                callback=task_handler,
            )
            return task_handler

        return decorator

    def _join_paths(self, prefix: str, path: str) -> str:
        """Join a router prefix and route path.

        Args:
            prefix: Router prefix.
            path: Route path relative to the router prefix.

        Returns:
            The normalized absolute route path.

        Raises:
            ValueError: If the provided path is empty.
        """
        base = path.strip()
        if not base:
            raise ValueError("Route path cannot be empty")

        suffix = base if base.startswith("/") else f"/{base}"
        cleaned_prefix = prefix.strip()
        if not cleaned_prefix:
            return suffix

        normalized_prefix = (
            cleaned_prefix if cleaned_prefix.startswith("/") else f"/{cleaned_prefix}"
        )
        normalized_prefix = normalized_prefix.rstrip("/")
        return normalized_prefix if suffix == "/" else f"{normalized_prefix}{suffix}"

    def _with_prefix(self, prefix: str, route: RouteDefinition) -> RouteDefinition:
        """Return a copy of the route with the provided prefix applied."""
        return replace(route, path=self._join_paths(prefix, route.path))

    def _register_route(
        self,
        *,
        name: str,
        path: str,
        event: str,
        condition: str | None,
        task_based: bool,
        callback: Callable[..., Awaitable[None] | None],
    ) -> None:
        """Register a route definition on the router.

        Args:
            name: Unique human-readable route name.
            path: Route path relative to the router prefix.
            event: Platform event subscribed by the route.
            condition: Optional condition expression.
            task_based: Whether the route handles task-backed events.
            callback: Callable associated with the route.

        Raises:
            ValueError: If the name or path is empty or already registered.
        """
        normalized_path = self._join_paths(self.prefix, path)
        route_definition = RouteDefinition(
            name=name,
            path=normalized_path,
            event=event,
            condition=condition,
            task_based=task_based,
            callback=callback,
        )
        ExtensionValidator.validate_route_uniqueness(
            route_name=route_definition.name,
            route_path=route_definition.path,
            route_event=route_definition.event,
            routes=self._routes,
        )
        self._routes.append(route_definition)


@dataclass
class ExtensionApp:
    """Explicit SDK integration object for an extension.

    This object owns route registration and context adaptation for a single
    extension package.

    Attributes:
        prefix: Prefix applied to every route included in the extension app.
        version: Extension metadata version.
        openapi: OpenAPI endpoint published by the runtime.
    """

    prefix: str = ""
    version: str = "1.0.0"
    openapi: str = "/bypass/openapi.json"
    mpt_api_service_type: type[MPTAPIService] = MPTAPIService
    order_context_type: type[ContextAdapter] | None = None
    agreement_context_type: type[ContextAdapter] | None = None
    _routes: list[RouteDefinition] = field(default_factory=list, init=False, repr=False)

    def __post_init__(self) -> None:
        """Validate extension app settings."""
        ExtensionValidator.validate_service_type(self.mpt_api_service_type)
        ExtensionValidator.validate_context_type(self.order_context_type, OrderContext)
        ExtensionValidator.validate_context_type(self.agreement_context_type, AgreementContext)

    @property
    def routes(self) -> list[RouteDefinition]:
        """Return the registered route definitions.

        Returns:
            A copy of the registered route definitions.
        """
        return list(self._routes)

    def build_context(self, context: ExecutionContext) -> ExecutionContext:
        """Adapt a base SDK context to the configured extension-specific context."""
        if isinstance(context, OrderContext) and self.order_context_type is not None:
            adapted_context = self.order_context_type.from_context(context)
            if not isinstance(adapted_context, ExecutionContext):
                raise TypeError("order_context_type.from_context must return an ExecutionContext")
            return adapted_context
        if isinstance(context, AgreementContext) and self.agreement_context_type is not None:
            adapted_context = self.agreement_context_type.from_context(context)
            if not isinstance(adapted_context, ExecutionContext):
                raise TypeError(
                    "agreement_context_type.from_context must return an ExecutionContext"
                )
            return adapted_context
        return context

    def include_router(self, router: ExtensionRouter) -> None:
        """Include a router in the extension app.

        Args:
            router: Router containing routes to include.

        Raises:
            ValueError: If any included route duplicates an existing name or path.
        """
        for route in router.prefixed_routes(self.prefix):
            ExtensionValidator.validate_route_uniqueness(
                route_name=route.name,
                route_path=route.path,
                route_event=route.event,
                routes=self._routes,
            )
            self._routes.append(route)

    def to_meta_config(self) -> MetaConfig:
        """Build extension metadata from the registered application routes."""
        return MetaConfig(
            version=self.version,
            openapi=self.openapi,
            events=[
                MetaEvent(
                    event=route.event,
                    condition=route.condition,
                    path=route.path,
                    task=route.task_based,
                )
                for route in self._routes
            ],
        )
