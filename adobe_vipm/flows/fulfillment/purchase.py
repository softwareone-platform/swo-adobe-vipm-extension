"""
This module contains the logic to implement the purchase fulfillment flow.

It exposes a single function that is the entrypoint for purchase order
processing.
"""

import logging

from adobe_vipm.flows.constants import (
    TEMPLATE_NAME_PURCHASE,
)
from adobe_vipm.flows.context import Context
from adobe_vipm.flows.pipeline import Pipeline
from adobe_vipm.flows.steps.agreement import SyncAgreement
from adobe_vipm.flows.steps.context import SetupContext
from adobe_vipm.flows.steps.coterm_date import SetOrUpdateCotermDate
from adobe_vipm.flows.steps.customer import CreateCustomer, PrepareCustomerData, RefreshCustomer
from adobe_vipm.flows.steps.due_date import SetupDueDate
from adobe_vipm.flows.steps.order import (
    CompleteOrder,
    GetPreviewOrder,
    StartOrderProcessing,
    SubmitNewOrder,
)
from adobe_vipm.flows.steps.price import UpdatePrices
from adobe_vipm.flows.steps.subscription import CreateOrUpdateSubscriptions
from adobe_vipm.flows.steps.validation import (
    Validate3YCCommitment,
    ValidateDuplicateLinesForOrder,
    ValidateMarketSegmentEligibility,
)

logger = logging.getLogger(__name__)


def fulfill_purchase_order(client, order):
    """
    Purchase order pipeline.

    Args:
        client (MPTClient): MPT API client.
        order (dict): MPT order to process.
    """
    pipeline = Pipeline(
        SetupContext(),
        StartOrderProcessing(TEMPLATE_NAME_PURCHASE),
        SetupDueDate(),
        ValidateDuplicateLinesForOrder(),
        ValidateMarketSegmentEligibility(),
        PrepareCustomerData(),
        CreateCustomer(),
        Validate3YCCommitment(),
        GetPreviewOrder(),
        SubmitNewOrder(),
        CreateOrUpdateSubscriptions(),
        RefreshCustomer(),
        SetOrUpdateCotermDate(),
        UpdatePrices(),
        CompleteOrder(TEMPLATE_NAME_PURCHASE),
        SyncAgreement(),
    )

    context = Context(order=order)
    pipeline.run(client, context)
