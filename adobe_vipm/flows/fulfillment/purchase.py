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
    ERR_ADOBE_AGENCY_TYPE,
    ERR_ADOBE_COMPANY_NAME,
    ERR_ADOBE_CONTACT,
    ERR_VIPM_UNHANDLED_EXCEPTION,
    MARKET_SEGMENT_EDUCATION,
    TEMPLATE_EDUCATION_QUERY_SUBSEGMENT,
    TEMPLATE_NAME_PURCHASE,
    VALID_GOVERNMENT_AGENCY_TYPES,
    Param,
)
from adobe_vipm.flows.context import Context
from adobe_vipm.flows.fulfillment.shared import (
    CompleteOrder,
    CreateOrUpdateAssets,
    CreateOrUpdateSubscriptions,
    GetPreviewOrder,
    NullifyFlexDiscountParam,
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
    get_ordering_parameter,
    set_adobe_3yc_commitment_request_status,
    set_adobe_customer_id,
    set_order_error,
    set_ordering_parameter_error,
)
from adobe_vipm.flows.utils.market_segment import is_large_government_agency_type

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


class ValidateGovernmentLGA(Step):
    """
    Validate if the customer has selected the government agency type.

    The government agency type is determined by the customer account type.
    """

    def __call__(self, client, context, next_step):
        """Validate if the customer has selected the government agency type."""
        if is_large_government_agency_type(context.product_id):
            agency_type_param = get_ordering_parameter(context.order, Param.AGENCY_TYPE.value)
            if agency_type_param.get("value") not in VALID_GOVERNMENT_AGENCY_TYPES:
                logger.info(
                    "%s: agency type is not valid for segment %s",
                    context,
                    context.market_segment,
                )
                context.order = set_ordering_parameter_error(
                    context.order,
                    Param.AGENCY_TYPE.value,
                    ERR_ADOBE_AGENCY_TYPE.to_dict(
                        title=Param.AGENCY_TYPE.value,
                        details="This parameter is mandatory and must be: FEDERAL, STATE.",
                    ),
                )
                switch_order_to_query(client, context.order, template_name=TEMPLATE_NAME_PURCHASE)
                return
        next_step(client, context)


class ValidateEducationSubSegments(Step):
    """
    Validate if the customer has select the market subsegments.

    The market segment the order refers to is determined by the product (product per segment).
    """

    def __call__(self, client, context, next_step):
        """Validate if the customer is eligible to place orders for a given market segment."""
        if self._requires_education_subsegment_query(context):
            switch_order_to_query(
                client,
                context.order,
                template_name=TEMPLATE_EDUCATION_QUERY_SUBSEGMENT,
            )
            return
        next_step(client, context)

    def _requires_education_subsegment_query(self, context):
        """Check if education segment requires subsegment query."""
        if context.market_segment != MARKET_SEGMENT_EDUCATION:
            return False

        company_profile = context.adobe_customer.get("companyProfile", {})
        market_subsegments = company_profile.get("marketSubSegments")
        return not market_subsegments


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
            param = get_ordering_parameter(context.order, Param.ADDRESS.value)
            context.order = set_ordering_parameter_error(
                context.order,
                Param.ADDRESS.value,
                ERR_ADOBE_ADDRESS.to_dict(title=param["name"], details=str(error)),
            )
        elif error.code == AdobeStatus.INVALID_MINIMUM_QUANTITY:
            if "LICENSE" in str(error):
                param = get_ordering_parameter(context.order, Param.THREE_YC_LICENSES.value)
                context.order = set_ordering_parameter_error(
                    context.order,
                    Param.THREE_YC_LICENSES.value,
                    ERR_3YC_QUANTITY_LICENSES.to_dict(title=param["name"]),
                    required=False,
                )

            if "CONSUMABLES" in str(error):
                param = get_ordering_parameter(context.order, Param.THREE_YC_CONSUMABLES.value)
                context.order = set_ordering_parameter_error(
                    context.order,
                    Param.THREE_YC_CONSUMABLES.value,
                    ERR_3YC_QUANTITY_CONSUMABLES.to_dict(title=param["name"]),
                    required=False,
                )

            if not error.details:
                param_licenses = get_ordering_parameter(
                    context.order, Param.THREE_YC_LICENSES.value
                )
                param_consumables = get_ordering_parameter(
                    context.order, Param.THREE_YC_CONSUMABLES.value
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
                param = get_ordering_parameter(context.order, Param.COMPANY_NAME.value)
                context.order = set_ordering_parameter_error(
                    context.order,
                    Param.COMPANY_NAME.value,
                    ERR_ADOBE_COMPANY_NAME.to_dict(title=param["name"], details=str(error)),
                )
            if list(
                filter(
                    lambda err_detail: err_detail.startswith("companyProfile.contacts[0]"),
                    error.details,
                )
            ):
                param = get_ordering_parameter(context.order, Param.CONTACT.value)
                context.order = set_ordering_parameter_error(
                    context.order,
                    Param.CONTACT.value,
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
                param = get_ordering_parameter(context.order, Param.CONTACT.value)
                context.order = set_ordering_parameter_error(
                    context.order,
                    Param.CONTACT.value,
                    ERR_ADOBE_CONTACT.to_dict(title=param["name"], details="it is mandatory."),
                )

                switch_order_to_query(client, context.order)
                return

            if is_large_government_agency_type(context.product_id):
                customer = adobe_client.create_customer_account_lga(
                    context.authorization_id,
                    context.seller_id,
                    context.agreement_id,
                    context.market_segment,
                    context.customer_data,
                )
            else:
                customer = adobe_client.create_customer_account(
                    context.authorization_id,
                    context.seller_id,
                    context.agreement_id,
                    context.market_segment,
                    context.customer_data,
                )
            context.adobe_customer_id = customer["customerId"]
            context.adobe_customer = customer

            self.save_data(client, context)
            next_step(client, context)
        except AdobeError as error:
            logger.exception("Create Customer failed")
            self.handle_error(client, context, error)


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
        ValidateDuplicateLines(),
        ValidateGovernmentLGA(),
        PrepareCustomerData(),
        CreateCustomer(),
        ValidateEducationSubSegments(),
        Validate3YCCommitment(),
        GetPreviewOrder(),
        UpdatePrices(),
        SubmitNewOrder(),
        CreateOrUpdateAssets(),
        CreateOrUpdateSubscriptions(),
        RefreshCustomer(),
        SetOrUpdateCotermDate(),
        CompleteOrder(TEMPLATE_NAME_PURCHASE),
        NullifyFlexDiscountParam(),
        SyncAgreement(),
    )

    context = Context(order=order)
    pipeline.run(client, context)
