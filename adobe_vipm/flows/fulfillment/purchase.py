"""
This module contains the logic to implement the purchase fulfillment flow.

It exposes a single function that is the entrypoint for purchase order
processing.
"""

import logging

from mpt_extension_sdk.mpt_http.mpt import update_agreement, update_order

from adobe_vipm.adobe.client import get_adobe_client
from adobe_vipm.adobe.constants import AdobeStatus
from adobe_vipm.adobe.errors import AdobeError
from adobe_vipm.adobe.utils import get_3yc_commitment_request
from adobe_vipm.flows.constants import (
    ERR_3YC_NO_MINIMUMS,
    ERR_3YC_QUANTITY_CONSUMABLES,
    ERR_3YC_QUANTITY_LICENSES,
    ERR_ADOBE_ADDRESS,
    ERR_ADOBE_COMPANY_NAME,
    ERR_ADOBE_CONTACT,
    ERR_MARKET_SEGMENT_NOT_ELIGIBLE,
    ERR_VIPM_UNHANDLED_EXCEPTION,
    MARKET_SEGMENT_COMMERCIAL,
    STATUS_MARKET_SEGMENT_NOT_ELIGIBLE,
    STATUS_MARKET_SEGMENT_PENDING,
    TEMPLATE_NAME_PURCHASE,
    Param,
)
from adobe_vipm.flows.context import Context
from adobe_vipm.flows.fulfillment.shared import (
    CompleteOrder,
    CreateOrUpdateSubscriptions,
    GetPreviewOrder,
    SetOrUpdateCotermDate,
    SetupDueDate,
    StartOrderProcessing,
    SubmitNewOrder,
    SyncAgreement,
    ValidateDuplicateLines,
    switch_order_to_failed,
    switch_order_to_query,
)
from adobe_vipm.flows.helpers import (
    PrepareCustomerData,
    SetupContext,
    UpdatePrices,
    Validate3YCCommitment,
)
from adobe_vipm.flows.pipeline import Pipeline, Step
from adobe_vipm.flows.utils import (
    get_market_segment_eligibility_status,
    get_ordering_parameter,
    set_adobe_3yc_commitment_request_status,
    set_adobe_customer_id,
    set_market_segment_eligibility_status_pending,
    set_order_error,
    set_ordering_parameter_error,
)

logger = logging.getLogger(__name__)


class RefreshCustomer(Step):
    """Refresh the processing context retrieving the Adobe customer object through the VIPM API."""

    def __call__(self, client, context, next_step):
        """Refresh the processing context retrieving the Adobe customer."""
        adobe_client = get_adobe_client()
        context.adobe_customer = adobe_client.get_customer(
            context.authorization_id,
            context.adobe_customer_id,
        )
        next_step(client, context)


class ValidateMarketSegmentEligibility(Step):
    """
    Validate if the customer is eligible to place orders for a given market segment.

    The market segment the order refers to is determined by the product (product per segment).
    """

    def __call__(self, client, context, next_step):
        """Validate if the customer is eligible to place orders for a given market segment."""
        if context.market_segment != MARKET_SEGMENT_COMMERCIAL:
            status = get_market_segment_eligibility_status(context.order)
            if not status:
                context.order = set_market_segment_eligibility_status_pending(context.order)
                switch_order_to_query(client, context.order, template_name=TEMPLATE_NAME_PURCHASE)
                logger.info(
                    "%s: customer is pending eligibility approval for segment %s",
                    context,
                    context.market_segment,
                )
                return
            if status == STATUS_MARKET_SEGMENT_NOT_ELIGIBLE:
                logger.info(
                    "%s: customer is not eligible for segment %s",
                    context,
                    context.market_segment,
                )
                switch_order_to_failed(
                    client,
                    context.order,
                    ERR_MARKET_SEGMENT_NOT_ELIGIBLE.to_dict(segment=context.market_segment),
                )
                return
            if status == STATUS_MARKET_SEGMENT_PENDING:
                return
            logger.info("%s: customer is eligible for segment %s", context, context.market_segment)
        next_step(client, context)


class CreateCustomer(Step):
    """
    Creates a customer account in Adobe for the new agreement.

    That belongs to the order currently being processed.
    """

    def save_data(self, client, context):
        """
        Saves customer date back to MPT Order and Agreement.

        Args:
            client (MPTClient): MPT API client.
            context (Context): step context.
        """
        request_3yc_status = get_3yc_commitment_request(
            context.adobe_customer,
            is_recommitment=False,
        ).get("status")
        context.order = set_adobe_customer_id(context.order, context.adobe_customer_id)
        if request_3yc_status:
            context.order = set_adobe_3yc_commitment_request_status(
                context.order, request_3yc_status
            )
        update_order(client, context.order_id, parameters=context.order["parameters"])
        update_agreement(
            client,
            context.agreement_id,
            externalIds={"vendor": context.adobe_customer_id},
        )

    def handle_error(self, client, context, error):  # noqa: C901
        """
        Process error from Adobe API.

        Args:
            client (MPTClient): MPT API client.
            context (Context): step context.
            error (Error): API Error.
        """
        if error.code not in {
            AdobeStatus.INVALID_ADDRESS,
            AdobeStatus.INVALID_FIELDS,
            AdobeStatus.INVALID_MINIMUM_QUANTITY,
        }:
            switch_order_to_failed(
                client,
                context.order,
                ERR_VIPM_UNHANDLED_EXCEPTION.to_dict(error=str(error)),
            )
            return
        if error.code == AdobeStatus.INVALID_ADDRESS:
            param = get_ordering_parameter(context.order, Param.ADDRESS)
            context.order = set_ordering_parameter_error(
                context.order,
                Param.ADDRESS,
                ERR_ADOBE_ADDRESS.to_dict(title=param["name"], details=str(error)),
            )
        elif error.code == AdobeStatus.INVALID_MINIMUM_QUANTITY:
            if "LICENSE" in str(error):
                param = get_ordering_parameter(context.order, Param.THREE_YC_LICENSES)
                context.order = set_ordering_parameter_error(
                    context.order,
                    Param.THREE_YC_LICENSES,
                    ERR_3YC_QUANTITY_LICENSES.to_dict(title=param["name"]),
                    required=False,
                )

            if "CONSUMABLES" in str(error):
                param = get_ordering_parameter(context.order, Param.THREE_YC_CONSUMABLES)
                context.order = set_ordering_parameter_error(
                    context.order,
                    Param.THREE_YC_CONSUMABLES,
                    ERR_3YC_QUANTITY_CONSUMABLES.to_dict(title=param["name"]),
                    required=False,
                )

            if not error.details:
                param_licenses = get_ordering_parameter(context.order, Param.THREE_YC_LICENSES)
                param_consumables = get_ordering_parameter(
                    context.order, Param.THREE_YC_CONSUMABLES
                )
                context.order = set_order_error(
                    context.order,
                    ERR_3YC_NO_MINIMUMS.to_dict(
                        title_min_licenses=param_licenses["name"],
                        title_min_consumables=param_consumables["name"],
                    ),
                )
        else:
            if "companyProfile.companyName" in error.details:
                param = get_ordering_parameter(context.order, Param.COMPANY_NAME)
                context.order = set_ordering_parameter_error(
                    context.order,
                    Param.COMPANY_NAME,
                    ERR_ADOBE_COMPANY_NAME.to_dict(title=param["name"], details=str(error)),
                )
            if list(
                filter(
                    lambda x: x.startswith("companyProfile.contacts[0]"),
                    error.details,
                )
            ):
                param = get_ordering_parameter(context.order, Param.CONTACT)
                context.order = set_ordering_parameter_error(
                    context.order,
                    Param.CONTACT,
                    ERR_ADOBE_CONTACT.to_dict(title=param["name"], details=str(error)),
                )

        switch_order_to_query(client, context.order)

    def __call__(self, client, context, next_step):
        """Creates a customer account in Adobe for the new agreement."""
        if context.adobe_customer_id:
            next_step(client, context)
            return

        adobe_client = get_adobe_client()
        try:
            if not context.customer_data.get("contact"):
                param = get_ordering_parameter(context.order, Param.CONTACT)
                context.order = set_ordering_parameter_error(
                    context.order,
                    Param.CONTACT,
                    ERR_ADOBE_CONTACT.to_dict(title=param["name"], details="it is mandatory."),
                )

                switch_order_to_query(client, context.order)
                return

            customer = adobe_client.create_customer_account(
                context.authorization_id,
                context.seller_id,
                context.agreement_id,
                context.market_segment,
                context.customer_data,
            )
            context.adobe_customer_id = customer["customerId"]
            context.adobe_customer = customer

            self.save_data(
                client,
                context,
            )
            next_step(client, context)
        except AdobeError as e:
            logger.exception("Create Customer failed")
            self.handle_error(client, context, e)


def fulfill_purchase_order(client, order):
    """
    Purchase order pipeline.

    Args:
        client (MPTClient): MPT API client.
        order (dict): MPT order to process.
    """
    pipeline = Pipeline(
        SetupContext(),
        SetupDueDate(),
        ValidateDuplicateLines(),
        ValidateMarketSegmentEligibility(),
        StartOrderProcessing(TEMPLATE_NAME_PURCHASE),
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
