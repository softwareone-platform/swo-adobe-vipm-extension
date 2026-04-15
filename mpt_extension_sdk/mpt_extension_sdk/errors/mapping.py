from mpt_extension_sdk.api.models.events import EventResponse
from mpt_extension_sdk.errors.pipeline import CancelError, DeferError, FailError
from mpt_extension_sdk.errors.runtime import ExtRuntimeError


def map_exception_to_event_response(error: Exception) -> EventResponse:
    """Map SDK exceptions to a structured event response.

    Args:
        error: The exception raised by the handler or a pipeline step.

    Returns:
        An EventResponse.
    """
    if isinstance(error, CancelError):
        return EventResponse.cancel(reason=str(error) or "Cancelled")
    if isinstance(error, DeferError):
        return EventResponse.reschedule(seconds=error.delay_seconds)
    if isinstance(error, FailError):
        return EventResponse.cancel(reason=str(error) or "Failed to process the event")
    if isinstance(error, ExtRuntimeError):
        return EventResponse.cancel(reason="Runtime error")

    return EventResponse.cancel(reason="Unexpected error")
