from abc import ABC, abstractmethod
from collections.abc import Callable

from mpt_extension_sdk.mpt_http.base import MPTClient

from adobe_vipm.flows.context import Context

NextStep = Callable[[MPTClient, Context], None]


# TODO: why it is still here and not in SDK???
class Step(ABC):
    @abstractmethod
    def __call__(
        self,
        client: MPTClient,
        context: Context,
        next_step: NextStep,
    ) -> None:
        raise NotImplementedError()  # pragma: no cover


def _default_error_handler(error: Exception, context: Context, next_step: NextStep):
    raise error


# Attribute used to record which step an error came from. Set on the exception instead of
# wrapping it, so the exception type the flows and error handlers match on stays unchanged.
FAILED_STEP_ATTRIBUTE = "mpt_failed_step"


def get_failed_step(error: Exception) -> str | None:
    """
    Return the name of the pipeline step that raised the error.

    Args:
        error: An exception raised while a pipeline was running.

    Returns:
        The step class name, or None when the error did not come from a pipeline step.
    """
    return getattr(error, FAILED_STEP_ATTRIBUTE, None)


class Cursor:
    def __init__(self, steps, error_handler):
        self.queue = steps
        self.error_handler = error_handler

    def __call__(self, client: MPTClient, context: Context):
        if not self.queue:
            return
        current_step = self.queue[0]
        next_step = Cursor(self.queue[1:], self.error_handler)

        try:
            current_step(client, context, next_step)
        except Exception as error:
            # The innermost cursor annotates first, so the step that actually raised wins
            # over the outer steps the error propagates through.
            if not get_failed_step(error):
                setattr(error, FAILED_STEP_ATTRIBUTE, type(current_step).__name__)
            self.error_handler(error, context, next_step)


class Pipeline:
    def __init__(self, *steps):
        self.queue = steps

    def run(self, client: MPTClient, context: Context, error_handler=None):
        execute = Cursor(self.queue, error_handler or _default_error_handler)
        return execute(client, context)

    def __len__(self):
        return len(self.queue)
