"""
This module contains the logic to implement the configuration fulfillment flow.

It exposes a single function that is the entrypoint for configuration order
processing.
"""

import logging

from adobe_vipm.flows.context import Context
from adobe_vipm.flows.fulfillment.shared import (
    get_configuration_template_name,
)
from adobe_vipm.flows.pipeline import Pipeline
from adobe_vipm.flows.steps.agreement import SyncAgreement
from adobe_vipm.flows.steps.context import SetupContext
from adobe_vipm.flows.steps.coterm_date import SetOrUpdateCotermDate
from adobe_vipm.flows.steps.due_date import SetupDueDate
from adobe_vipm.flows.steps.order import CompleteOrder, StartOrderProcessing
from adobe_vipm.flows.steps.renewal import SubscriptionUpdateAutoRenewal
from adobe_vipm.flows.steps.validation import ValidateRenewalWindow

logger = logging.getLogger(__name__)


def fulfill_configuration_order(client, order):
    """
    Fulfills a configuration order.

    Args:
        client (MPTClient): MPT API client.
        order (dict): MPT Order.
    """
    logger.info("Start processing %s order %s", order["type"], order["id"])

    template_name = get_configuration_template_name(order)

    pipeline = Pipeline(
        SetupContext(),
        StartOrderProcessing(template_name),
        SetupDueDate(),
        SetOrUpdateCotermDate(),
        ValidateRenewalWindow(),
        SubscriptionUpdateAutoRenewal(),
        CompleteOrder(template_name),
        SyncAgreement(),
    )

    context = Context(order=order)
    pipeline.run(client, context)
