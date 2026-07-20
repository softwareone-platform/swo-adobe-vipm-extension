"""
This module contains the logic to implement the switch fulfillment flow.

It exposes a single function that is the entrypoint for change orders
that carry a mid-term upgrade (SWITCH) payload computed from an Adobe
recommendation.
"""

import logging

from mpt_extension_sdk.mpt_http.mpt import update_order

from adobe_vipm.adobe.client import get_adobe_client
from adobe_vipm.adobe.constants import (
    ORDER_STATUS_DESCRIPTION,
    UNRECOVERABLE_ORDER_STATUSES,
    AdobeOrderStatus,
)
from adobe_vipm.adobe.errors import AdobeError
from adobe_vipm.flows.constants import (
    ERR_UNEXPECTED_ADOBE_ERROR_STATUS,
    ERR_UNRECOVERABLE_ADOBE_ORDER_STATUS,
    ERR_VIPM_UNHANDLED_EXCEPTION,
    TEMPLATE_NAME_CHANGE,
)
from adobe_vipm.flows.context import Context
from adobe_vipm.flows.fulfillment.shared import (
    CompleteOrder,
    CreateOrUpdateSubscriptions,
    SetOrUpdateCotermDate,
    SetSubscriptionTemplate,
    SetupDueDate,
    StartOrderProcessing,
    SyncAgreement,
    UpdateAgreementParamsVisibility,
    ValidateDuplicateLines,
    ValidateRenewalWindow,
    switch_order_to_failed,
)
from adobe_vipm.flows.helpers import SetupContext, UpdatePrices, ValidateSkuAvailability
from adobe_vipm.flows.pipeline import Pipeline, Step
from adobe_vipm.flows.utils import get_switch_payload, set_adobe_order_id
from adobe_vipm.flows.utils.parameter import set_adobe_order_ids_created_parameter

logger = logging.getLogger(__name__)


class GetSwitchPreviewOrder(Step):
    """
    Retrieve a PREVIEW_SWITCH order for the switch payload of the order.

    It validates with Adobe that the switch can be processed and retrieves
    the pricing of the new line items. If Adobe rejects the preview the order
    will be failed and the processing pipeline will stop.
    In case the switch order has already been submitted by a previous attempt,
    this step will be skipped and the order processing pipeline will continue.
    """

    def __call__(self, mpt_client, context, next_step):
        """Retrieve a PREVIEW_SWITCH order for the switch payload of the order."""
        if context.adobe_new_order_id:
            logger.info(
                "%s: skip switch preview, Adobe order %s has already been created",
                context,
                context.adobe_new_order_id,
            )
            next_step(mpt_client, context)
            return

        adobe_client = get_adobe_client()
        try:
            context.adobe_preview_order = adobe_client.create_switch_preview_order(
                context.authorization_id,
                context.adobe_customer_id,
                context.order_id,
                get_switch_payload(context.order),
            )
        except AdobeError as error:
            switch_order_to_failed(
                mpt_client,
                context.order,
                ERR_VIPM_UNHANDLED_EXCEPTION.to_dict(error=str(error)),
            )
            logger.warning("%s: switch preview failed: %s", context, error)
            return

        logger.info("%s: switch preview validated successfully", context)
        next_step(mpt_client, context)


class SubmitSwitchOrder(Step):
    """
    Submit the Adobe SWITCH order for the switch payload of the order.

    Wait for the order to be processed by Adobe before moving to the next step.
    The step is idempotent: if the Adobe order has already been created by a
    previous attempt it is retrieved instead of being created again.
    """

    def __call__(self, client, context, next_step):
        """Submit the Adobe SWITCH order for the switch payload of the order."""
        adobe_client = get_adobe_client()
        if context.adobe_new_order_id:
            adobe_order = adobe_client.get_order(
                context.authorization_id,
                context.adobe_customer_id,
                context.adobe_new_order_id,
            )
        else:
            adobe_order = adobe_client.create_switch_order(
                context.authorization_id,
                context.adobe_customer_id,
                context.order_id,
                get_switch_payload(context.order),
            )
            logger.info("%s: new adobe switch order created: %s", context, adobe_order["orderId"])
            context.order = set_adobe_order_id(context.order, adobe_order["orderId"])
            context.order = set_adobe_order_ids_created_parameter(context, [adobe_order["orderId"]])
            update_order(
                client,
                context.order_id,
                externalIds=context.order["externalIds"],
                parameters=context.order["parameters"],
            )
        context.adobe_new_order = adobe_order
        context.adobe_new_order_id = adobe_order["orderId"]
        adobe_order_status = adobe_order["status"]

        if adobe_order_status == AdobeOrderStatus.OPEN:
            logger.info(
                "%s: adobe switch order %s is still pending.", context, context.adobe_new_order_id
            )
            return

        if adobe_order_status in UNRECOVERABLE_ORDER_STATUSES:
            error = ERR_UNRECOVERABLE_ADOBE_ORDER_STATUS.to_dict(
                description=ORDER_STATUS_DESCRIPTION[adobe_order_status],
            )
            switch_order_to_failed(client, context.order, error)
            logger.warning("%s: the switch order has been failed %s.", context, error["message"])
            return

        if adobe_order_status != AdobeOrderStatus.COMPLETE:
            error = ERR_UNEXPECTED_ADOBE_ERROR_STATUS.to_dict(status=adobe_order_status)
            switch_order_to_failed(client, context.order, error)
            logger.warning(
                "%s: the switch order has been failed due to %s.", context, error["message"]
            )
            return

        next_step(client, context)


def fulfill_switch_order(client, order):
    """
    Fulfills a change order that carries a mid-term upgrade (SWITCH) payload.

    It validates the switch through a PREVIEW_SWITCH order, submits the actual
    SWITCH order and creates or updates the agreement subscriptions with the
    new Adobe subscriptions. The quantities of the subscriptions being switched
    from are cancelled by Adobe (cancellingItems) and synchronized back to the
    agreement at the end of the pipeline.

    Args:
        client (MPTClient): An instance of the MPT client used for communication
        with the MPT system.
        order (dict): The MPT order representing the switch order to be fulfilled.

    Returns:
        None
    """
    pipeline = Pipeline(
        SetupContext(),
        StartOrderProcessing(TEMPLATE_NAME_CHANGE),
        SetupDueDate(),
        ValidateDuplicateLines(),
        SetOrUpdateCotermDate(),
        UpdateAgreementParamsVisibility(),
        ValidateRenewalWindow(),
        ValidateSkuAvailability(is_validation=False),
        GetSwitchPreviewOrder(),
        UpdatePrices(is_validation=False),
        SubmitSwitchOrder(),
        CreateOrUpdateSubscriptions(),
        CompleteOrder(TEMPLATE_NAME_CHANGE),
        SetSubscriptionTemplate(),
        SyncAgreement(),
    )
    context = Context(order=order)
    pipeline.run(client, context)
