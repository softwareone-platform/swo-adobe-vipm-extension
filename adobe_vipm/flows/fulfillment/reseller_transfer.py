import logging

from mpt_extension_sdk.mpt_http.mpt import (
    update_agreement,
    update_order,
)

from adobe_vipm.adobe.client import get_adobe_client
from adobe_vipm.adobe.constants import AdobeStatus, ResellerChangeAction
from adobe_vipm.adobe.errors import AdobeAPIError
from adobe_vipm.airtable.models import get_transfer_by_authorization_membership_or_customer
from adobe_vipm.flows.constants import ERR_ADOBE_RESSELLER_CHANGE_PREVIEW, TEMPLATE_NAME_TRANSFER
from adobe_vipm.flows.context import Context
from adobe_vipm.flows.fulfillment import transfer
from adobe_vipm.flows.fulfillment.shared import (
    SetupDueDate,
    StartOrderProcessing,
    SyncAgreement,
    switch_order_to_failed,
)
from adobe_vipm.flows.helpers import (
    FetchResellerChangeData,
    SetupContext,
    ValidateResellerChange,
)
from adobe_vipm.flows.pipeline import Pipeline, Step
from adobe_vipm.flows.utils.customer import set_adobe_customer_id
from adobe_vipm.flows.utils.order import get_adobe_order_id, set_adobe_order_id
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
        StartOrderProcessing(TEMPLATE_NAME_TRANSFER),
        SetupDueDate(),
        SetupResellerChangeContext(),
        FetchResellerChangeData(is_validation=False),
        ValidateResellerChange(is_validation=False),
        CommitResellerChange(),
        CheckAdobeResellerTransfer(),
        transfer.GetAdobeCustomer(),
        UpdateAutorenewalSubscriptions(),
        transfer.ValidateGCMainAgreement(),
        transfer.ValidateAgreementDeployments(),
        transfer.ProcessTransferOrder(),
        transfer.CreateTransferAssets(),
        transfer.CreateTransferSubscriptions(),
        transfer.SetCommitmentDates(),
        transfer.CompleteTransferOrder(),
        SyncAgreement(),
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
        adobe_client = get_adobe_client()
        authorization_id = context.order["authorization"]["id"]
        transfer_id = get_adobe_order_id(context.order)
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
            switch_order_to_failed(
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


class UpdateAutorenewalSubscriptions(Step):
    """Updates the auto renewal status of the subscriptions."""

    def __call__(self, mpt_client, context, next_step):
        """Updates the auto renewal status of the subscriptions."""
        adobe_client = get_adobe_client()
        subscriptions = adobe_client.get_subscriptions(
            context.authorization_id,
            context.customer_id,
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
                    context.customer_id,
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
