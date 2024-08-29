"""
This module contains the logic to implement the purchase fulfillment flow.
It exposes a single function that is the entrypoint for purchase order
processing.
"""

import logging

from adobe_vipm.adobe.client import get_adobe_client
from adobe_vipm.adobe.constants import (
    STATUS_INVALID_ADDRESS,
    STATUS_INVALID_FIELDS,
    STATUS_INVALID_MINIMUM_QUANTITY,
)
from adobe_vipm.adobe.errors import AdobeError
from adobe_vipm.adobe.utils import get_3yc_commitment_request
from adobe_vipm.flows.constants import (
    ERR_3YC_NO_MINIMUMS,
    ERR_3YC_QUANTITY_CONSUMABLES,
    ERR_3YC_QUANTITY_LICENSES,
    ERR_ADOBE_ADDRESS,
    ERR_ADOBE_COMPANY_NAME,
    ERR_ADOBE_CONTACT,
    MARKET_SEGMENT_COMMERCIAL,
    PARAM_3YC_CONSUMABLES,
    PARAM_3YC_LICENSES,
    PARAM_ADDRESS,
    PARAM_COMPANY_NAME,
    PARAM_CONTACT,
    STATUS_MARKET_SEGMENT_NOT_ELIGIBLE,
    STATUS_MARKET_SEGMENT_PENDING,
    TEMPLATE_NAME_PURCHASE,
)
from adobe_vipm.flows.context import Context
from adobe_vipm.flows.fulfillment.shared import (
    CompleteOrder,
    CreateOrUpdateSubscriptions,
    IncrementAttemptsCounter,
    SetOrUpdateCotermNextSyncDates,
    StartOrderProcessing,
    SubmitNewOrder,
    UpdatePrices,
    ValidateDuplicateLines,
    switch_order_to_failed,
    switch_order_to_query,
)
from adobe_vipm.flows.helpers import SetupContext, prepare_customer_data
from adobe_vipm.flows.mpt import update_agreement, update_order
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
    """
    Refresh the processing context
    retrieving the Adobe customer object through the
    VIPM API.
    """

    def __call__(self, client, context, next_step):
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
        if context.market_segment != MARKET_SEGMENT_COMMERCIAL:
            status = get_market_segment_eligibility_status(context.order)
            if not status:
                context.order = set_market_segment_eligibility_status_pending(
                    context.order
                )
                switch_order_to_query(
                    client, context.order, template_name=TEMPLATE_NAME_PURCHASE
                )
                logger.info(
                    f"{context}: customer is pending eligibility "
                    f"approval for segment {context.market_segment}"
                )
                return
            if status == STATUS_MARKET_SEGMENT_NOT_ELIGIBLE:
                logger.info(
                    f"{context}: customer is not eligible for segment {context.market_segment}"
                )
                switch_order_to_failed(
                    client,
                    context.order,
                    f"The agreement is not eligible for market segment {context.market_segment}.",
                )
                return
            if status == STATUS_MARKET_SEGMENT_PENDING:
                return
            logger.info(
                f"{context}: customer is eligible for segment {context.market_segment}"
            )
        next_step(client, context)


class CreateCustomer(Step):
    """
    Creates a customer account in Adobe for the new agreement that belongs to the order
    currently being processed.
    """

    def save_data(self, client, context):
        request_3yc_status = get_3yc_commitment_request(context.adobe_customer).get(
            "status"
        )
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

    def handle_error(self, client, context, error):
        if error.code not in (
            STATUS_INVALID_ADDRESS,
            STATUS_INVALID_FIELDS,
            STATUS_INVALID_MINIMUM_QUANTITY,
        ):
            switch_order_to_failed(client, context.order, str(error))
            return
        if error.code == STATUS_INVALID_ADDRESS:
            param = get_ordering_parameter(context.order, PARAM_ADDRESS)
            context.order = set_ordering_parameter_error(
                context.order,
                PARAM_ADDRESS,
                ERR_ADOBE_ADDRESS.to_dict(title=param["name"], details=str(error)),
            )
        elif error.code == STATUS_INVALID_MINIMUM_QUANTITY:
            if "LICENSE" in str(error):
                param = get_ordering_parameter(context.order, PARAM_3YC_LICENSES)
                context.order = set_ordering_parameter_error(
                    context.order,
                    PARAM_3YC_LICENSES,
                    ERR_3YC_QUANTITY_LICENSES.to_dict(title=param["name"]),
                    required=False,
                )

            if "CONSUMABLES" in str(error):
                param = get_ordering_parameter(context.order, PARAM_3YC_CONSUMABLES)
                context.order = set_ordering_parameter_error(
                    context.order,
                    PARAM_3YC_CONSUMABLES,
                    ERR_3YC_QUANTITY_CONSUMABLES.to_dict(title=param["name"]),
                    required=False,
                )

            if not error.details:
                param_licenses = get_ordering_parameter(
                    context.order, PARAM_3YC_LICENSES
                )
                param_consumables = get_ordering_parameter(
                    context.order, PARAM_3YC_CONSUMABLES
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
                param = get_ordering_parameter(context.order, PARAM_COMPANY_NAME)
                context.order = set_ordering_parameter_error(
                    context.order,
                    PARAM_COMPANY_NAME,
                    ERR_ADOBE_COMPANY_NAME.to_dict(
                        title=param["name"], details=str(error)
                    ),
                )
            if len(
                list(
                    filter(
                        lambda x: x.startswith("companyProfile.contacts[0]"),
                        error.details,
                    )
                )
            ):
                param = get_ordering_parameter(context.order, PARAM_CONTACT)
                context.order = set_ordering_parameter_error(
                    context.order,
                    PARAM_CONTACT,
                    ERR_ADOBE_CONTACT.to_dict(title=param["name"], details=str(error)),
                )

        switch_order_to_query(client, context.order)

    def __call__(self, client, context, next_step):
        if context.adobe_customer_id:
            next_step(client, context)
            return

        adobe_client = get_adobe_client()
        try:
            context.order, customer_data = prepare_customer_data(client, context.order)
            if not customer_data.get("contact"):
                param = get_ordering_parameter(context.order, PARAM_CONTACT)
                context.order = set_ordering_parameter_error(
                    context.order,
                    PARAM_CONTACT,
                    ERR_ADOBE_CONTACT.to_dict(
                        title=param["name"], details="it is mandatory."
                    ),
                )

                switch_order_to_query(client, context.order)
                return

            customer = adobe_client.create_customer_account(
                context.authorization_id,
                context.seller_id,
                context.agreement_id,
                context.market_segment,
                customer_data,
            )
            context.adobe_customer_id = customer["customerId"]
            context.adobe_customer = customer

            self.save_data(
                client,
                context,
            )
            next_step(client, context)
        except AdobeError as e:
            logger.error(repr(e))
            self.handle_error(client, context, e)


def fulfill_purchase_order(client, order):
    pipeline = Pipeline(
        SetupContext(),
        IncrementAttemptsCounter(),
        ValidateDuplicateLines(),
        ValidateMarketSegmentEligibility(),
        StartOrderProcessing(TEMPLATE_NAME_PURCHASE),
        CreateCustomer(),
        SubmitNewOrder(),
        CreateOrUpdateSubscriptions(),
        RefreshCustomer(),
        SetOrUpdateCotermNextSyncDates(),
        UpdatePrices(),
        CompleteOrder(TEMPLATE_NAME_PURCHASE),
    )

    context = Context(order=order)
    pipeline.run(client, context)
