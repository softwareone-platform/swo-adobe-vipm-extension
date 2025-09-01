import logging

from adobe_vipm.flows.context import Context
from adobe_vipm.flows.pipeline import Pipeline
from adobe_vipm.flows.steps.context import SetupContext
from adobe_vipm.flows.steps.coterm_date import SetOrUpdateCotermDate
from adobe_vipm.flows.steps.order import GetPreviewOrder
from adobe_vipm.flows.steps.price import UpdatePrices
from adobe_vipm.flows.steps.validation import (
    Validate3YCCommitment,
    ValidateDownsizes,
    ValidateDuplicateLines,
    ValidateRenewalWindow,
)

logger = logging.getLogger(__name__)


def validate_change_order(client, order):
    """Validate change order pipeline."""
    pipeline = Pipeline(
        SetupContext(),
        ValidateDuplicateLines(),
        SetOrUpdateCotermDate(),
        ValidateRenewalWindow(is_validation=True),
        ValidateDownsizes(),
        Validate3YCCommitment(is_validation=True),
        GetPreviewOrder(),
        UpdatePrices(),
    )
    context = Context(order=order)
    pipeline.run(client, context)

    return not context.validation_succeeded, context.order
