"""
This module contains the logic to implement the termination fulfillment flow.

It exposes a single function that is the entrypoint for termination order
processing.
"""

import logging

from adobe_vipm.flows.constants import (
    TEMPLATE_NAME_TERMINATION,
)
from adobe_vipm.flows.context import Context
from adobe_vipm.flows.pipeline import Pipeline
from adobe_vipm.flows.steps.agreement import SyncAgreement
from adobe_vipm.flows.steps.context import SetupContext
from adobe_vipm.flows.steps.coterm_date import SetOrUpdateCotermDate
from adobe_vipm.flows.steps.due_date import SetupDueDate
from adobe_vipm.flows.steps.order import (
    CompleteOrder,
    GetReturnableOrdersForTermination,
    GetReturnOrders,
    StartOrderProcessing,
    SubmitReturnOrders,
)
from adobe_vipm.flows.steps.validation import Validate3YCCommitment, ValidateRenewalWindow

logger = logging.getLogger(__name__)


def fulfill_termination_order(client, order):
    """
    Fulfills a termination order with Adobe.

    Adobe allow to terminate a subscription with a cancellation window
    (X days from the first order).
    For subscriptions that are outside such window the auto renewal
    will be switched off.

    Args:
        client (MPTClient):  an instance of the Marketplace platform client.
        order (dict): The MPT termination order.
    """
    pipeline = Pipeline(
        SetupContext(),
        StartOrderProcessing(TEMPLATE_NAME_TERMINATION),
        SetupDueDate(),
        SetOrUpdateCotermDate(),
        ValidateRenewalWindow(),
        GetReturnOrders(),
        GetReturnableOrdersForTermination(),
        Validate3YCCommitment(),
        SubmitReturnOrders(),
        CompleteOrder(TEMPLATE_NAME_TERMINATION),
        SyncAgreement(),
    )
    context = Context(order=order)
    pipeline.run(client, context)
