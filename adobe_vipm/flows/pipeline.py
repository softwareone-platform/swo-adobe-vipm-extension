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
            self.error_handler(error, context, next_step)


class Pipeline:
    def __init__(self, *steps):
        self.queue = steps

    def run(self, client: MPTClient, context: Context, error_handler=None):
        execute = Cursor(self.queue, error_handler or _default_error_handler)
        return execute(client, context)

    def __len__(self):
        return len(self.queue)
