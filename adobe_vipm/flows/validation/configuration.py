import logging

from adobe_vipm.flows.context import Context
from adobe_vipm.flows.helpers import SetupContext
from adobe_vipm.flows.pipeline import Pipeline
from adobe_vipm.flows.validation.shared import (
    ValidateNoEarlyRenewal,
    ValidateNoStagedRenewal,
)

logger = logging.getLogger(__name__)


def validate_configuration_order(client, order):
    """Validate configuration order pipeline."""
    pipeline = Pipeline(
        SetupContext(),
        ValidateNoEarlyRenewal(),
        ValidateNoStagedRenewal(),
    )
    context = Context(order=order)
    pipeline.run(client, context)

    return not context.validation_succeeded, context.order
