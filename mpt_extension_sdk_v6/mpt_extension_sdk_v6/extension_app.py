import dataclasses
import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from functools import lru_cache
from inspect import isawaitable, signature
from typing import get_type_hints

from mpt_extension_sdk_v6.pipeline.context import ExecutionContext

TaskHandler = Callable[..., Awaitable[None] | None]
EventHandler = Callable[..., Awaitable[None] | None]


@dataclass(frozen=True)
class RouteDefinition:
    """Explicit route definition owned by an extension application.

    Attributes:
        name: Human-readable unique route name.
        path: Route path relative to the runtime prefix.
        task_based: Whether the route handles task-backed events.
        handler: Callable invoked when the route receives an event.
    """

    name: str
    path: str
    task_based: bool
    handler: Callable[..., Awaitable[None] | None]


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
        """Return the registered route definitions.

        Returns:
            A copy of the registered route definitions.
        """
        return list(self._routes)

    def prefixed_routes(self, prefix: str) -> list[RouteDefinition]:
        """Return route definitions with the given prefix applied to each path."""
        return [
            dataclasses.replace(route, path=self._join_paths(prefix, route.path))
            for route in self._routes
        ]

    def route(self, path: str, name: str) -> Callable[[EventHandler], EventHandler]:
        """Register a non-task event handler on the router.

        Args:
            path: Route path relative to the router prefix.
            name: Unique human-readable route name.

        Returns:
            A decorator that registers the provided handler.
        """

        def decorator(handler: EventHandler) -> EventHandler:
            self._register_route(name=name, path=path, task_based=False, handler=handler)
            return handler

        return decorator

    def task_route(self, path: str, name: str) -> Callable[[TaskHandler], TaskHandler]:
        """Register a task-based event handler on the router.

        Args:
            path: Route path relative to the router prefix.
            name: Unique human-readable route name.

        Returns:
            A decorator that registers the provided handler.
        """

        def decorator(handler: TaskHandler) -> TaskHandler:
            self._register_route(name=name, path=path, task_based=True, handler=handler)
            return handler

        return decorator

    def _register_route(
        self,
        *,
        name: str,
        path: str,
        task_based: bool,
        handler: Callable[..., Awaitable[None] | None],
    ) -> None:
        """Register a route definition on the router.

        Args:
            name: Unique human-readable route name.
            path: Route path relative to the router prefix.
            task_based: Whether the route handles task-backed events.
            handler: Callable associated with the route.

        Raises:
            ValueError: If the name or path is empty or already registered.
        """
        normalized_path = self._join_paths(self.prefix, path)
        if any(route.name == name for route in self._routes):
            raise ValueError(f"Route name '{name}' is already registered")
        if any(route.path == normalized_path for route in self._routes):
            raise ValueError(f"Route path '{normalized_path}' is already registered")

        self._routes.append(
            RouteDefinition(name=name, path=normalized_path, task_based=task_based, handler=handler)
        )

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


@dataclass
class ExtensionApp:
    """Explicit SDK integration object for an extension.

    This object owns route registration and context adaptation for a single
    extension package.

    Attributes:
        prefix: Prefix applied to every route included in the extension app.
    """

    prefix: str = ""
    _routes: list[RouteDefinition] = field(default_factory=list, init=False, repr=False)

    @property
    def routes(self) -> list[RouteDefinition]:
        """Return the registered route definitions.

        Returns:
            A copy of the registered route definitions.
        """
        return list(self._routes)

    def include_router(self, router: ExtensionRouter) -> None:
        """Include a router in the extension app.

        Args:
            router: Router containing routes to include.

        Raises:
            ValueError: If any included route duplicates an existing name or path.
        """
        for route in router.prefixed_routes(self.prefix):
            if any(registered.name == route.name for registered in self._routes):
                raise ValueError(f"Route name '{route.name}' is already registered")
            if any(registered.path == route.path for registered in self._routes):
                raise ValueError(f"Route path '{route.path}' is already registered")
            self._routes.append(route)

    async def build_context(
        self, handler: Callable[..., Awaitable[None] | None], context: ExecutionContext
    ) -> ExecutionContext:
        """Adapt the SDK base context to the context expected by the handler.

        Args:
            handler: Handler callable that will receive the context.
            context: SDK context built by the runtime.

        Returns:
            The original context when the handler expects the base context, or
            an adapted extension-specific context otherwise.
        """
        target_context_type = get_handler_context_type(handler)
        if target_context_type is None or isinstance(context, target_context_type):
            return context

        builder = self._get_context_builder(target_context_type, type(context))
        built_context = builder(context)
        if isawaitable(built_context):
            built_context = await built_context
        return built_context

    def _get_context_builder(
        self, target_context_type: type[ExecutionContext], base_context_type: type[ExecutionContext]
    ) -> Callable[[ExecutionContext], ExecutionContext | Awaitable[ExecutionContext]]:
        """Resolve the builder used to adapt a base context to the target type.

        Args:
            target_context_type: Context type declared by the handler.
            base_context_type: Concrete base context built by the SDK.

        Returns:
            A callable that converts the base context into the target context.

        Raises:
            ValueError: If no suitable builder method exists on the target type.
        """
        builder_name = f"from_{self._to_snake_case(base_context_type.__name__)}"
        builder = getattr(target_context_type, builder_name, None)
        if callable(builder):
            return builder

        fallback_builder = getattr(target_context_type, "from_context", None)
        if callable(fallback_builder):
            return fallback_builder

        raise ValueError(
            f"Context type '{target_context_type.__name__}' must define "
            f"'{builder_name}' or 'from_context'"
        )

    def _to_snake_case(self, value: str) -> str:
        """Convert a CamelCase value to snake_case.

        Args:
            value: CamelCase input value.

        Returns:
            The normalized snake_case value.
        """
        return re.sub(r"(?<!^)(?=[A-Z])", "_", value).lower()


@lru_cache
def get_handler_context_type(
    handler: Callable[..., Awaitable[None] | None],
) -> type[ExecutionContext] | None:
    """Return the context type annotation declared by the handler.

    Args:
        handler: Handler callable declared by the extension.

    Returns:
        The annotated context type when available and valid, otherwise
        `None`.
    """
    parameters = list(signature(handler).parameters.values())
    if len(parameters) < 2:
        return None

    context_parameter = parameters[1]
    type_hints = get_type_hints(handler)
    context_type = type_hints.get(context_parameter.name)
    if not isinstance(context_type, type) or not issubclass(context_type, ExecutionContext):
        return None

    return context_type
