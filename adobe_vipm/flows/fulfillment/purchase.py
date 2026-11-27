"""
This module contains the logic to implement the purchase fulfillment flow.

It exposes a single function that is the entrypoint for purchase order
processing.
"""

import logging

from mpt_extension_sdk.mpt_http.base import MPTClient
from mpt_extension_sdk.mpt_http.mpt import (
    update_agreement,
    update_order,
)

from adobe_vipm.adobe.client import get_adobe_client
from adobe_vipm.adobe.constants import AdobeCustomerStatus, AdobeErrorCode
from adobe_vipm.adobe.errors import AdobeError
from adobe_vipm.adobe.utils import get_3yc_commitment_request
from adobe_vipm.flows.constants import (
    ERR_3YC_NO_MINIMUMS,
    ERR_3YC_QUANTITY_CONSUMABLES,
    ERR_3YC_QUANTITY_LICENSES,
    ERR_ADOBE_ACCOUNT_COMPLIANCE_BLOCK,
    ERR_ADOBE_ADDRESS,
    ERR_ADOBE_AGENCY_TYPE,
    ERR_ADOBE_COMPANY_NAME,
    ERR_ADOBE_CONTACT,
    ERR_VIPM_UNHANDLED_EXCEPTION,
    MARKET_SEGMENT_EDUCATION,
    MARKET_SEGMENTS,
    TEMPLATE_EDUCATION_QUERY_SUBSEGMENT,
    TEMPLATE_NAME_PURCHASE,
    TEMPLATE_NAME_SCREENING,
    VALID_GOVERNMENT_AGENCY_TYPES,
    Param,
)
from adobe_vipm.flows.context import Context
from adobe_vipm.flows.fulfillment.renewal import RecordDiscountRedemptions
from adobe_vipm.flows.fulfillment.shared import (
    MPT_REQUEST_ERRORS,
    CompleteOrder,
    CreateOrUpdateAssets,
    CreateOrUpdateSubscriptions,
    DiscardCarriedOverFlexDiscounts,
    GetPreviewOrder,
    NullifyFlexDiscountParam,
    SelectFlexDiscounts,
    SetOrUpdateCotermDate,
    SetupDueDate,
    StartOrderProcessing,
    SubmitNewOrder,
    SyncAgreement,
    UpdateAgreementParamsVisibility,
    ValidateDuplicateLines,
    apply_processing_template,
    get_named_processing_template,
    get_order_template_id,
    get_processing_template,
    mark_order_as_failed,
    switch_order_to_failed,
    switch_order_to_query,
)
from adobe_vipm.flows.helpers import (
    PrepareCustomerData,
    SetupContext,
    UpdatePrices,
    Validate3YCCommitment,
)
from adobe_vipm.flows.pipeline import NextStep, Pipeline, Step
from adobe_vipm.flows.utils import (
    get_due_date,
    get_ordering_parameter,
    roll_due_date,
    set_adobe_3yc_commitment_request_status,
    set_adobe_customer_id,
    set_order_error,
    set_ordering_parameter_error,
)
from adobe_vipm.flows.utils.flex_discounts import get_order_redeemed_codes
from adobe_vipm.flows.utils.market_segment import is_large_government_agency_type
from adobe_vipm.notifications import FactsSection, send_error

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

    def handle_error(self, client, context, error):  # ruff:ignore[complex-structure]
        """
        Process error from Adobe API.

        Args:
            client (MPTClient): MPT API client.
            context (Context): step context.
            error (Error): API Error.
        """
        if error.code not in {
            AdobeErrorCode.INVALID_ADDRESS,
            AdobeErrorCode.INVALID_FIELDS,
            AdobeErrorCode.INVALID_MINIMUM_QUANTITY,
        }:
            switch_order_to_failed(
                client,
                context.order,
                ERR_VIPM_UNHANDLED_EXCEPTION.to_dict(error=str(error)),
            )
            return
        if error.code in {AdobeErrorCode.INVALID_ADDRESS, AdobeErrorCode.INVALID_FIELDS}:
            param = get_ordering_parameter(context.order, Param.ADDRESS.value)
            context.order = set_ordering_parameter_error(
                context.order,
                Param.ADDRESS.value,
                ERR_ADOBE_ADDRESS.to_dict(title=param["name"], details=str(error)),
            )
        elif error.code == AdobeErrorCode.INVALID_MINIMUM_QUANTITY:
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
                    ERR_ADOBE_CONTACT.to_dict(
                        title=param.get("name", "Contact"), details="it is mandatory."
                    ),
                )

                switch_order_to_query(client, context.order)
                return

            if is_large_government_agency_type(context.product_id):
                customer = adobe_client.create_customer_account_lga(
                    context.authorization_id,
                    context.seller_id,
                    context.agreement_id,
                    MARKET_SEGMENTS[context.market_segment],
                    context.customer_data,
                )
            else:
                customer = adobe_client.create_customer_account(
                    context.authorization_id,
                    context.seller_id,
                    context.agreement_id,
                    MARKET_SEGMENTS[context.market_segment],
                    context.customer_data,
                )
            context.adobe_customer_id = customer["customerId"]
            context.adobe_customer = customer

            self.save_data(client, context)
            next_step(client, context)
        except AdobeError as error:
            logger.exception("Create Customer failed")
            self.handle_error(client, context, error)


class RollScreeningDueDate(Step):
    """
    Move the due date forward while the Adobe customer account is in screening.

    Screening has no time limit. The step runs before the due date check, so an order that
    waits on Adobe's screening is not failed for a due date that has been reached.
    """

    def __call__(self, client: MPTClient, context: Context, next_step: NextStep) -> None:
        """
        Set the due date to today + DUE_DATE_DAYS when the account is in screening.

        The order is updated only when the due date changes.

        Args:
            client: MPT API client.
            context: Step context.
            next_step: Next pipeline step.
        """
        adobe_customer = context.adobe_customer or {}
        if adobe_customer.get("status") == AdobeCustomerStatus.SCREENING:
            rolled_order = roll_due_date(context.order)
            due_date = get_due_date(rolled_order)
            if due_date != get_due_date(context.order):
                update_order(client, context.order_id, parameters=rolled_order["parameters"])
                context.order = rolled_order
                logger.info("%s: due date is rolled to %s", context, due_date.strftime("%Y-%m-%d"))
        next_step(client, context)


class CheckAccountStatus(Step):
    """
    Act on the status of the Adobe customer account before any order is sent to Adobe.

    No order is sent to Adobe for a pending account or an account in screening: the run stops
    and the account status is evaluated again on the next run. The order shows the Screening
    template while the account is in screening and the Purchase template otherwise. A
    compliance block fails the order and alerts operations.
    """

    def __call__(self, client: MPTClient, context: Context, next_step: NextStep) -> None:
        """
        Continue with the next step unless the account is pending, in screening or blocked.

        Args:
            client: MPT API client.
            context: Step context.
            next_step: Next pipeline step.
        """
        status = context.adobe_customer.get("status")
        if status == AdobeCustomerStatus.PENDING:
            logger.info(
                "%s: Adobe customer %s is pending, waiting for the account to be active",
                context,
                context.adobe_customer_id,
            )
            return
        if status == AdobeCustomerStatus.COMPLIANCE_BLOCK:
            self._fail_blocked_account(client, context)
            return
        if status == AdobeCustomerStatus.SCREENING:
            try:
                self._set_screening_template(client, context)
            except MPT_REQUEST_ERRORS:
                logger.exception(
                    "%s: failed to set the %s template, the current template is kept",
                    context,
                    TEMPLATE_NAME_SCREENING,
                )
            logger.info(
                "%s: Adobe customer %s is in screening, waiting for the account to be active",
                context,
                context.adobe_customer_id,
            )
            return
        try:
            self._restore_purchase_template(client, context)
        except MPT_REQUEST_ERRORS:
            logger.exception(
                "%s: failed to restore the %s template, the current template is kept",
                context,
                TEMPLATE_NAME_PURCHASE,
            )
        next_step(client, context)

    def _set_screening_template(self, client: MPTClient, context: Context) -> None:
        screening_template = get_named_processing_template(client, context, TEMPLATE_NAME_SCREENING)
        if not screening_template:
            logger.warning(
                "%s: template %s not found for product %s, the current template is kept",
                context,
                TEMPLATE_NAME_SCREENING,
                context.order["agreement"]["product"]["id"],
            )
            return
        apply_processing_template(client, context, screening_template)

    def _restore_purchase_template(self, client: MPTClient, context: Context) -> None:
        screening_template = get_named_processing_template(client, context, TEMPLATE_NAME_SCREENING)
        if not screening_template:
            return
        if screening_template["id"] != get_order_template_id(context.order):
            return
        purchase_template = get_processing_template(client, context, TEMPLATE_NAME_PURCHASE)
        product_id = context.order["agreement"]["product"]["id"]
        if not purchase_template:
            logger.warning(
                "%s: no processing template found for product %s, the %s template is kept",
                context,
                product_id,
                TEMPLATE_NAME_SCREENING,
            )
            return
        if purchase_template.get("name") != TEMPLATE_NAME_PURCHASE:
            logger.warning(
                "%s: template %s not found for product %s, the default template is used",
                context,
                TEMPLATE_NAME_PURCHASE,
                product_id,
            )
        apply_processing_template(client, context, purchase_template)

    def _fail_blocked_account(self, client: MPTClient, context: Context) -> None:
        mark_order_as_failed(client, context.order, ERR_ADOBE_ACCOUNT_COMPLIANCE_BLOCK.to_dict())
        logger.error(
            "%s: Adobe customer %s is in compliance block, order %s of agreement %s failed",
            context,
            context.adobe_customer_id,
            context.order_id,
            context.agreement_id,
        )
        send_error(
            "Adobe account compliance block",
            f"The order **{context.order_id}** has been failed because Adobe blocked the new "
            f"customer account **{context.adobe_customer_id}** during its trade compliance "
            "screening.",
            facts=FactsSection(
                "Blocked account",
                {
                    "Order": context.order_id,
                    "Agreement": context.agreement_id,
                    "Adobe customer": context.adobe_customer_id,
                },
            ),
        )


def fulfill_purchase_order(client, order):
    """
    Purchase order pipeline.

    Args:
        client (MPTClient): MPT API client.
        order (dict): MPT order to process.
    """
    pipeline = Pipeline(
        SetupContext(),
        DiscardCarriedOverFlexDiscounts(),
        StartOrderProcessing(TEMPLATE_NAME_PURCHASE, template_to_keep=TEMPLATE_NAME_SCREENING),
        RollScreeningDueDate(),
        SetupDueDate(),
        ValidateDuplicateLines(),
        ValidateGovernmentLGA(),
        PrepareCustomerData(is_validation=False),
        CreateCustomer(),
        CheckAccountStatus(),
        ValidateEducationSubSegments(),
        Validate3YCCommitment(),
        SelectFlexDiscounts(),
        GetPreviewOrder(),
        UpdatePrices(is_validation=False),
        SubmitNewOrder(),
        CreateOrUpdateAssets(),
        CreateOrUpdateSubscriptions(),
        RefreshCustomer(),
        SetOrUpdateCotermDate(),
        UpdateAgreementParamsVisibility(),
        CompleteOrder(TEMPLATE_NAME_PURCHASE),
        RecordDiscountRedemptions(get_order_redeemed_codes),
        NullifyFlexDiscountParam(),
        SyncAgreement(),
    )

    context = Context(order=order)
    pipeline.run(client, context)
