from collections.abc import Awaitable, Callable
from functools import wraps
from typing import Concatenate

from mpt_extension_sdk.pipeline.context import OrderContext
from mpt_extension_sdk.pipeline.step import BaseStep


def refresh_order[StepT: BaseStep, CtxT: OrderContext, **ParamT](
    func: Callable[Concatenate[StepT, CtxT, ParamT], Awaitable[None]],
) -> Callable[Concatenate[StepT, CtxT, ParamT], Awaitable[None]]:
    """Refresh the order context after a successful step method."""

    @wraps(func)
    async def wrapper(self: StepT, ctx: CtxT, *args: ParamT.args, **kwargs: ParamT.kwargs) -> None:
        await func(self, ctx, *args, **kwargs)
        await ctx.refresh_order()

    return wrapper
