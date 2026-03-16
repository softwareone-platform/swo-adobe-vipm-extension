import logging

from mpt_extension_sdk.mpt_http.mpt import update_agreement, update_order

from adobe_vipm.adobe.client import get_adobe_client
from adobe_vipm.adobe.constants import AdobeStatus, ResellerChangeAction
from adobe_vipm.adobe.errors import AdobeAPIError
from adobe_vipm.airtable.models import get_transfer_by_authorization_membership_or_customer
from adobe_vipm.flows.constants import ERR_ADOBE_RESSELLER_CHANGE_PREVIEW, TEMPLATE_NAME_TRANSFER
from adobe_vipm.flows.context import Context
from adobe_vipm.flows.fulfillment import shared, transfer
from adobe_vipm.flows.helpers import (
    FetchResellerChangeData,
    SetupContext,
    UpdatePrices,
    ValidateResellerChange,
)
from adobe_vipm.flows.pipeline import Pipeline, Step
from adobe_vipm.flows.sync.agreement import sync_agreements_by_agreement_ids
from adobe_vipm.flows.utils import exclude_items_with_deployment_id
from adobe_vipm.flows.utils.customer import get_adobe_customer_id, set_adobe_customer_id
from adobe_vipm.flows.utils.order import set_adobe_order_id, split_downsizes_upsizes_new
from adobe_vipm.flows.utils.parameter import (
    get_change_reseller_admin_email,
    get_change_reseller_code,
)

logger = logging.getLogger(__name__)


def fulfill_reseller_change_order(mpt_client, order):
    """
    Fulfill reseller change order pipeline.

    Args:
        mpt_client (MPTClient): Marketplace API client
        order (dict): Marketplace order
    """
    pipeline = Pipeline(
        SetupContext(),
        shared.StartOrderProcessing(TEMPLATE_NAME_TRANSFER),
        shared.SetupDueDate(),
        SetupResellerChangeContext(),
        FetchResellerChangeData(is_validation=False),
        ValidateResellerChange(is_validation=False),
        CommitResellerChange(),
        CheckAdobeResellerTransfer(),
        GetAdobeCustomer(),
        transfer.ValidateGCMainAgreement(),
        transfer.ValidateAgreementDeployments(),
        ProcessResellerTransferOrder(),
        UpdateAutorenewalSubscriptions(),
        transfer.CreateTransferAssets(),
        transfer.CreateTransferSubscriptions(),
        shared.UpdateAgreementParamsVisibility(),
        transfer.SetCommitmentDates(),
        CompleteResellerTransferOrder(),
        shared.SyncAgreement(),
    )

    context = Context(order=order)
    pipeline.run(mpt_client, context)


class SetupResellerChangeContext(Step):
    """Sets up the initial context for reseller change order processing."""

    def __call__(self, client, context, next_step):
        """Sets up the initial context for reseller change order processing."""
        context.reseller_change_code = get_change_reseller_code(context.order)
        context.customer_deployments = None

        context.transfer = get_transfer_by_authorization_membership_or_customer(
            context.product_id,
            context.authorization_id,
            context.reseller_change_code,
        )

        context.gc_main_agreement = transfer.get_main_agreement(
            context.product_id,
            context.authorization_id,
            context.reseller_change_code,
        )

        context.existing_deployments = transfer.get_agreement_deployments(
            context.product_id, context.order.get("agreement", {}).get("id", "")
        )

        next_step(client, context)


class CheckAdobeResellerTransfer(Step):
    """Checks if the Adobe reseller transfer order exists and it is active."""

    def __call__(self, mpt_client, context, next_step):
        """Check if the Adobe reseller transfer order exists and it is active."""
        transfer_id = context.adobe_transfer_order.get("transferId")
        if not transfer_id:
            next_step(mpt_client, context)
            return
        adobe_client = get_adobe_client()
        authorization_id = context.order["authorization"]["id"]
        context.adobe_transfer_order = adobe_client.get_reseller_transfer(
            authorization_id, transfer_id
        )

        reseller_code = get_change_reseller_code(context.order)
        context.adobe_transfer_order["membershipId"] = reseller_code
        logger.info(
            "%s: Adobe transfer order with status %s",
            context,
            context.adobe_transfer_order.get("status"),
        )

        if context.adobe_transfer_order.get("status") == AdobeStatus.PENDING:
            return

        next_step(mpt_client, context)


class CommitResellerChange(Step):
    """Commits the reseller change order."""

    def __call__(self, mpt_client, context, next_step):
        """Commit the reseller change order."""
        if context.adobe_customer_id:
            next_step(mpt_client, context)
            return

        authorization_id = context.order["authorization"]["id"]
        seller_id = context.order["agreement"]["seller"]["id"]
        reseller_change_code = get_change_reseller_code(context.order)
        admin_email = get_change_reseller_admin_email(context.order)

        adobe_client = get_adobe_client()
        logger.info(
            "%s: Executing the commit reseller change with %s and %s",
            context,
            reseller_change_code,
            admin_email,
        )
        try:
            context.adobe_transfer_order = adobe_client.reseller_change_request(
                authorization_id,
                seller_id,
                reseller_change_code,
                admin_email,
                ResellerChangeAction.COMMIT,
            )
        except AdobeAPIError as ex:
            logger.exception("%s: Error committing reseller change", context)
            shared.switch_order_to_failed(
                mpt_client,
                context.order,
                ERR_ADOBE_RESSELLER_CHANGE_PREVIEW.to_dict(
                    reseller_change_code=reseller_change_code,
                    error=str(ex),
                ),
            )
            return

        context.order = set_adobe_order_id(
            context.order, context.adobe_transfer_order.get("transferId")
        )
        context.order = set_adobe_customer_id(
            context.order, context.adobe_transfer_order.get("customerId")
        )

        update_order(
            mpt_client,
            context.order_id,
            externalIds=context.order["externalIds"],
            parameters=context.order["parameters"],
        )
        update_agreement(
            mpt_client,
            context.agreement_id,
            externalIds={"vendor": context.adobe_customer_id},
        )
        next_step(mpt_client, context)


class UpdateAutorenewalSubscriptions(Step):
    """Updates the auto renewal status of the subscriptions."""

    def __call__(self, mpt_client, context, next_step):
        """Updates the auto renewal status of the subscriptions."""
        adobe_client = get_adobe_client()
        subscriptions = adobe_client.get_subscriptions(
            context.authorization_id,
            context.adobe_customer_id,
        ).get("items", [])

        disabled_subscriptions = [
            subscription
            for subscription in subscriptions
            if subscription.get("autoRenewal", {}).get("enabled") is False
        ]

        for subscription in disabled_subscriptions:
            subscription_id = subscription["subscriptionId"]
            try:
                adobe_client.update_subscription(
                    context.authorization_id,
                    context.adobe_customer_id,
                    subscription_id,
                    auto_renewal=True,
                )
            except AdobeAPIError:
                logger.warning(
                    "%s: Error updating the auto renewal status of the subscription %s",
                    context,
                    subscription_id,
                )
        next_step(mpt_client, context)


class ProcessResellerTransferOrder(Step):
    """Processes a reseller transfer order."""

    def __call__(self, mpt_client, context, next_step):
        """Updates order id and customer data to MPT order."""
        if not context.adobe_transfer_order.get("lineItems"):
            logger.info(
                "%s: Adobe reseller transfer order has no line items,"
                " falling back to purchase fulfillment",
                context,
            )
            if (
                context.adobe_new_order_id
                and context.adobe_new_order_id == context.adobe_transfer_order.get("transferId")
            ):
                # this is a workaround solution where Adobe order ID on the agreement is replaced
                # by new ID of the purchase order in case of Account Revival. It is not being lost
                # as it is saved in the audit log.
                # An example of a better solution would be to change the datatype of the property
                # storing the ID to a one allowing for storing more than one ID.
                logger.info("%s: Adobe order id is the same as transfer id, resetting", context)
                context.order = shared.save_adobe_order_id(mpt_client, context.order, "")
                context.adobe_new_order_id = ""

            downsize_lines, upsize_lines, new_lines = split_downsizes_upsizes_new(context.order)
            context.downsize_lines = downsize_lines
            context.upsize_lines = upsize_lines
            context.new_lines = new_lines
            fulfill_purchase_order(mpt_client, context)
            return

        context.adobe_transfer_order = exclude_items_with_deployment_id(
            context.adobe_transfer_order
        )
        context.order = shared.save_adobe_order_id_and_customer_data(
            mpt_client,
            context.order,
            context.adobe_new_order_id,
            context.adobe_customer,
        )
        next_step(mpt_client, context)


class GetAdobeCustomer(Step):
    """Retrieves the Adobe customer information."""

    def __call__(self, client, context, next_step):
        """Get Adobe customer and saves it to the context."""
        adobe_client = get_adobe_client()
        context.adobe_customer_id = context.adobe_transfer_order.get(
            "customerId"
        ) or get_adobe_customer_id(context.order)
        context.adobe_customer = adobe_client.get_customer(
            context.authorization_id, context.adobe_customer_id
        )

        context.order = shared.save_adobe_order_id_and_customer_data(
            client,
            context.order,
            context.adobe_new_order_id,
            context.adobe_customer,
        )

        next_step(client, context)


class CompleteResellerTransferOrder(Step):
    """Completes the reseller transfer order processing."""

    def __call__(self, mpt_client, context, next_step):
        """Completes transfer order with TEMPLATE_NAME_TRANSFER or default Transfer template."""
        shared.switch_order_to_completed(mpt_client, context.order, TEMPLATE_NAME_TRANSFER)
        adobe_client = get_adobe_client()
        sync_agreements_by_agreement_ids(
            mpt_client,
            adobe_client,
            [context.order["agreement"]["id"]],
            dry_run=False,
            sync_prices=False,
        )
        transfer.sync_airtable_main_agreement(
            context.gc_main_agreement,
            context.product_id,
            context.authorization_id,
            context.adobe_customer_id,
        )
        next_step(mpt_client, context)


def fulfill_purchase_order(client, context):
    """Purchase order pipeline."""
    pipeline = Pipeline(
        shared.GetPreviewOrder(),
        UpdatePrices(),
        shared.SubmitNewOrder(),
        shared.CreateOrUpdateAssets(),
        shared.CreateOrUpdateSubscriptions(),
        shared.SetOrUpdateCotermDate(),
        shared.UpdateAgreementParamsVisibility(),
        shared.CompleteOrder(TEMPLATE_NAME_TRANSFER),
        shared.NullifyFlexDiscountParam(),
        shared.SyncAgreement(),
    )

    pipeline.run(client, context)
