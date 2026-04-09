import logging

from mpt_extension_sdk_v6.api.models.events import Event
from mpt_extension_sdk_v6.pipeline.context import (
    AgreementContext,
    ExecutionContext,
    ExecutionMetadata,
    OrderContext,
)
from mpt_extension_sdk_v6.runtime.logging import correlation_id_ctx, task_id_ctx
from mpt_extension_sdk_v6.services.mpt_api_service import MPTAPIService
from mpt_extension_sdk_v6.settings.extension import get_extension_settings
from mpt_extension_sdk_v6.settings.runtime import get_runtime_settings


async def build_context(
    event: Event,
    handler_logger: logging.Logger,
    mpt_api_service_type: type[MPTAPIService] = MPTAPIService,
) -> ExecutionContext:
    """Build the fully hydrated execution context for an incoming event."""
    runtime_settings = get_runtime_settings()
    api_service = mpt_api_service_type.from_config(
        base_url=runtime_settings.mpt_api_base_url,
        api_token=runtime_settings.mpt_api_token,
    )
    return await _build_context_with_model(event, handler_logger, api_service)


def _build_execution_metadata(event: Event) -> ExecutionMetadata:
    """Build immutable execution metadata from the incoming event."""
    return ExecutionMetadata(
        event_id=event.id,
        object_id=event.object.id,
        object_type=event.object.object_type,
        correlation_id=correlation_id_ctx.get(),
        task_id=task_id_ctx.get(),
    )


async def _build_context_with_model(
    event: Event, handler_logger: logging.Logger, api_service: MPTAPIService
) -> ExecutionContext:
    """Build a fully hydrated execution context for the current event object."""
    runtime_settings = get_runtime_settings()
    object_type = event.object.object_type
    common_kwargs = {
        "logger": handler_logger,
        "meta": _build_execution_metadata(event),
        "mpt_api_service": api_service,
        "account_settings": None,
        "ext_settings": get_extension_settings(),
        "runtime_settings": runtime_settings,
    }

    if object_type == "Order":
        order = await api_service.orders.get_by_id(event.object.id)
        return OrderContext(order=order, **common_kwargs)

    if object_type == "Agreement":
        agreement = await api_service.agreements.get_by_id(event.object.id)
        return AgreementContext(agreement=agreement, **common_kwargs)
    raise RuntimeError(f"Unsupported context type: {object_type}")
