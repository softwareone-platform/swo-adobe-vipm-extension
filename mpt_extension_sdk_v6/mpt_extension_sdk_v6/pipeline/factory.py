import logging

from mpt_api_client.exceptions import MPTError

from mpt_extension_sdk_v6.api.schemas.events import Event
from mpt_extension_sdk_v6.pipeline.context import ExecutionContext, get_context_by_type
from mpt_extension_sdk_v6.runtime.logging import correlation_id_ctx, task_id_ctx
from mpt_extension_sdk_v6.services.mpt_api_service import MPTAPIService
from mpt_extension_sdk_v6.settings.extension import get_extension_settings
from mpt_extension_sdk_v6.settings.runtime import get_runtime_settings


async def build_context(event: Event, handler_logger: logging.Logger) -> ExecutionContext:
    """Build and hydrate the execution context for an incoming event."""
    runtime_settings = get_runtime_settings()
    extension_settings = get_extension_settings()
    api_service = MPTAPIService.from_config(
        base_url=runtime_settings.mpt_api_base_url, api_token=runtime_settings.mpt_api_token
    )
    context_class = get_context_by_type(event.object.object_type)
    context = context_class.from_event(
        event,
        ext_settings=extension_settings,
        runtime_settings=runtime_settings,
        logger=handler_logger,
        mpt_api_service=api_service,
        account_settings=None,
        correlation_id=correlation_id_ctx.get(),
        task_id=task_id_ctx.get(),
    )
    await hydrate_context_model(context)
    return context


async def hydrate_context_model(context: ExecutionContext) -> None:
    """Populate ``context.model`` for supported marketplace object types."""
    object_type = context.meta.object_type.lower()
    model_loaders = {
        "agreement": context.mpt_api_service.agreements.get_by_id,
        "order": context.mpt_api_service.orders.get_by_id,
    }
    model_loader = model_loaders.get(object_type)
    if not model_loader:
        raise RuntimeError(f"Unsupported object type: {object_type}")

    try:
        setattr(context, object_type, await model_loader(context.meta.object_id))
    except MPTError as error:
        context.logger.warning("Failed to load model: %s", error)
        raise RuntimeError(f"Failed to load model: {error}") from error
