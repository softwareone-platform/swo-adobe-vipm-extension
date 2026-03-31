from dataclasses import dataclass, field
from logging import Logger
from typing import Any, Self

from mpt_extension_sdk_v6.api.schemas.events import Event
from mpt_extension_sdk_v6.errors.runtime import ConfigError
from mpt_extension_sdk_v6.models.agreement import Agreement
from mpt_extension_sdk_v6.models.order import Order
from mpt_extension_sdk_v6.services.mpt_api_service import MPTAPIService
from mpt_extension_sdk_v6.settings.account import AccountSettings
from mpt_extension_sdk_v6.settings.extension import BaseExtensionSettings
from mpt_extension_sdk_v6.settings.runtime import RuntimeSettings


@dataclass(frozen=True)
class ExecutionMetadata:
    """Immutable event execution metadata."""

    event_id: str
    object_id: str
    object_type: str
    task_id: str

    correlation_id: str | None = None  # TODO: For testing purpose. Remove it
    installation_id: str | None = None


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
    def from_event(
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
            ext_settings: Extension settings for the active extension.
            runtime_settings: Runtime settings for the current process.
            logger: Logger bound to the handler module.
            mpt_api_service: Pre-built MPT API service facade.
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


@dataclass
class AgreementContext(ExecutionContext):
    """Execution context specialized for agreement events."""

    agreement: Agreement = None

    @property
    def agreement_id(self) -> str:
        """Agreement ID."""
        return self.agreement.id


@dataclass
class OrderContext(ExecutionContext):
    """Execution context specialized for order events."""

    order: Order = None

    @property
    def order_id(self) -> str:
        """Order ID."""
        return self.order.id


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
