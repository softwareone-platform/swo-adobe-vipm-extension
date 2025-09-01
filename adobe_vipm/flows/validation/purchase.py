import logging

from adobe_vipm.flows.context import Context
from adobe_vipm.flows.pipeline import Pipeline
from adobe_vipm.flows.steps.context import SetupContext
from adobe_vipm.flows.steps.customer import PrepareCustomerData
from adobe_vipm.flows.steps.order import GetPreviewOrder
from adobe_vipm.flows.steps.price import UpdatePrices
from adobe_vipm.flows.steps.validation import (
    CheckPurchaseValidationEnabled,
    Validate3YCCommitment,
    ValidateCustomerData,
    ValidateDuplicateLines,
)

logger = logging.getLogger(__name__)


def validate_purchase_order(client, order):
    """Validate purchase order pipeline."""
    pipeline = Pipeline(
        SetupContext(),
        PrepareCustomerData(),
        CheckPurchaseValidationEnabled(),
        ValidateCustomerData(),
        ValidateDuplicateLines(),
        Validate3YCCommitment(is_validation=True),
        GetPreviewOrder(),
        UpdatePrices(),
    )
    context = Context(order=order)
    pipeline.run(client, context)
    return not context.validation_succeeded, context.order
