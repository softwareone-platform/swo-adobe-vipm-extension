from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import StrEnum
from logging import Logger
from typing import Any, Self

from mpt_extension_sdk.api.models.events import Event
from mpt_extension_sdk.errors.runtime import ConfigError
from mpt_extension_sdk.models import Agreement, Order
from mpt_extension_sdk.services.mpt_api_service import MPTAPIService
from mpt_extension_sdk.settings.account import AccountSettings
from mpt_extension_sdk.settings.extension import BaseExtensionSettings
from mpt_extension_sdk.settings.runtime import RuntimeSettings


@dataclass(frozen=True)
class ExecutionMetadata:
    """Immutable event execution metadata."""

    event_id: str
    object_id: str
    object_type: str
    task_id: str

    correlation_id: str | None = None
    installation_id: str | None = None


class AgreementStatusActionType(StrEnum):
    """Supported agreement transitions requested by business logic."""

    FAIL = "Failed"


class OrderStatusActionType(StrEnum):
    """Supported order transitions requested by business logic."""

    FAIL = "Failed"
    QUERY = "Querying"


@dataclass(frozen=True)
class AgreementStatusAction:
    """Structured agreement transition intent declared by business logic."""

    target_status: AgreementStatusActionType
    message: str
    status_notes: dict[str, Any] | None = None
    parameters: dict[str, Any] | None = None  # noqa: WPS110


@dataclass
class AgreementState:
    """Mutable agreement state transition data shared across pipeline steps."""

    action: AgreementStatusAction | None = None
    handled: bool = False


@dataclass(frozen=True)
class OrderStatusAction:
    """Structured order transition intent declared by business logic."""

    target_status: OrderStatusActionType
    message: str
    status_notes: dict[str, Any] = field(default_factory=dict)
    parameters: dict[str, Any] = field(default_factory=dict)  # noqa: WPS110


@dataclass
class OrderState:
    """Mutable order state transition data shared across pipeline steps."""

    action: OrderStatusAction | None = None
    handled: bool = False


@dataclass
class ExecutionContext:
    """Mutable context passed through pipeline steps."""

    logger: Logger
    meta: ExecutionMetadata
    mpt_api_service: MPTAPIService

    account_settings: AccountSettings | None
    ext_settings: BaseExtensionSettings
    runtime_settings: RuntimeSettings

    state: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_event(  # noqa: WPS211
        cls,
        event: Event,
        logger: Logger,
        mpt_api_service: MPTAPIService,
        ext_settings: BaseExtensionSettings,
        runtime_settings: RuntimeSettings,
        account_settings: AccountSettings | None = None,
        *,
        correlation_id: str = "",
        task_id: str = "",
    ) -> Self:
        """Create a context from an incoming event.

        Args:
            event: The incoming platform event.
            logger: Logger bound to the handler module.
            mpt_api_service: Pre-built MPT API service facade.
            ext_settings: Extension settings for the active extension.
            runtime_settings: Runtime settings for the current process.
            account_settings: Optional account-scoped settings for the current request.
            correlation_id: Request correlation ID for log tracing.
            task_id: Platform task ID from the `MPT-Task-Id` request header.

        Returns:
            A new `ExecutionContext`
        """
        return cls(
            logger=logger,
            meta=ExecutionMetadata(
                event_id=event.id,
                object_id=event.object.id,
                object_type=event.object.object_type,
                correlation_id=correlation_id,
                task_id=task_id,
            ),
            mpt_api_service=mpt_api_service,
            account_settings=account_settings,
            ext_settings=ext_settings,
            runtime_settings=runtime_settings,
        )


@dataclass(kw_only=True)
class AgreementContext[MPTAPIServiceT: MPTAPIService](ExecutionContext):
    """Execution context specialized for agreement events."""

    agreement: Agreement
    agreement_state: AgreementState = field(default_factory=AgreementState)

    @property
    def agreement_id(self) -> str:
        """Agreement ID."""
        return self.agreement.id

    async def refresh_agreement(self) -> None:
        """Reload the current agreement from Marketplace."""
        self.agreement = await self.mpt_api_service.agreements.get_by_id(self.agreement_id)


@dataclass(kw_only=True)
class OrderContext(ExecutionContext):
    """Execution context specialized for order events."""

    order: Order
    order_state: OrderState = field(default_factory=OrderState)

    @property
    def order_id(self) -> str:
        """Order ID."""
        return self.order.id

    async def refresh_order(self) -> None:
        """Reload the current order from Marketplace."""
        self.order = await self.mpt_api_service.orders.get_by_id(self.order_id)


class ContextAdapter(ABC):
    """Interface for explicit context adapters."""

    @classmethod
    @abstractmethod
    def from_context(cls, ctx: ExecutionContext) -> Self:
        """Build the custom context from the SDK base context."""


def get_context_by_type(model_type: str) -> type[OrderContext | AgreementContext]:
    """Return the context subclass matching the marketplace object type."""
    context_map = {
        "Agreement": AgreementContext,
        "Order": OrderContext,
    }
    try:
        return context_map[model_type]
    except KeyError as error:
        raise ConfigError(f"Unsupported object type: {model_type}") from error
