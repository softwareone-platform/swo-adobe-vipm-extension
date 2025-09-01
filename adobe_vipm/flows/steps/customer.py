import logging

from mpt_extension_sdk.mpt_http.mpt import (
    update_agreement,
    update_order,
)

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
    ERR_ADOBE_MEMBERSHIP_ID,
    ERR_NO_SUBSCRIPTIONS_WITHOUT_DEPLOYMENT,
    ERR_VIPM_UNHANDLED_EXCEPTION,
    Param,
)
from adobe_vipm.flows.fulfillment.shared import (
    save_adobe_order_id_and_customer_data,
    switch_order_to_failed,
    switch_order_to_query,
)
from adobe_vipm.flows.pipeline import Step
from adobe_vipm.flows.utils import (
    get_ordering_parameter,
)
from adobe_vipm.flows.utils.customer import set_adobe_customer_id, set_customer_data
from adobe_vipm.flows.utils.order import set_order_error
from adobe_vipm.flows.utils.parameter import set_ordering_parameter_error
from adobe_vipm.flows.utils.three_yc import set_adobe_3yc_commitment_request_status

logger = logging.getLogger(__name__)


class PrepareCustomerData(Step):
    """Prepares customer data from order to Adobe format for futher processing."""

    def __call__(self, client, context, next_step):
        """Prepares customer data from order to Adobe format for futher processing."""
        licensee = context.order["agreement"]["licensee"]
        address = licensee["address"]
        contact = licensee.get("contact")

        customer_data_updated = False

        if not context.customer_data.get(Param.COMPANY_NAME.value):
            context.customer_data[Param.COMPANY_NAME.value] = licensee["name"]
            customer_data_updated = True

        if not context.customer_data.get(Param.ADDRESS.value):
            context.customer_data[Param.ADDRESS.value] = {
                "country": address["country"],
                "state": address["state"],
                "city": address["city"],
                "addressLine1": address["addressLine1"],
                "addressLine2": address.get("addressLine2"),
                "postCode": address["postCode"],
            }
            customer_data_updated = True

        if not context.customer_data.get(Param.CONTACT.value) and contact:
            context.customer_data[Param.CONTACT.value] = {
                "firstName": contact["firstName"],
                "lastName": contact["lastName"],
                "email": contact["email"],
                "phone": contact.get("phone"),
            }
            customer_data_updated = True

        if customer_data_updated:
            context.order = set_customer_data(context.order, context.customer_data)
            update_order(
                client,
                context.order_id,
                parameters=context.order["parameters"],
            )

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
                    lambda x: x.startswith("companyProfile.contacts[0]"),
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


class GetAdobeCustomer(Step):
    """Retrieves the Adobe customer information."""

    def __call__(self, client, context, next_step):
        """Get Adobe customer and saves it to the context."""
        adobe_client = get_adobe_client()
        context.customer_id = context.adobe_transfer_order["customerId"]
        context.adobe_customer = adobe_client.get_customer(
            context.authorization_id, context.customer_id
        )
        next_step(client, context)


class SaveCustomerData(Step):
    """Save customer data and order id to the MPT order."""

    def __call__(self, client, context, next_step):
        """Save customer data and order id to the MPT order."""
        context.order = save_adobe_order_id_and_customer_data(
            client,
            context.order,
            "",
            context.adobe_customer,
        )
        next_step(client, context)


class FetchCustomerAndValidateEmptySubscriptions(Step):
    """Validates transfer empty subscriptions for account revival."""

    def __call__(self, mpt_client, context, next_step):
        """Validates transfer empty subscriptions for account revival."""
        adobe_client = get_adobe_client()
        customer = adobe_client.get_customer(
            context.order["authorization"]["id"], context.transfer.customer_id
        )
        context.adobe_customer = customer

        if len(context.subscriptions["items"]) == 0:
            if customer.get("globalSalesEnabled", False):
                logger.error(ERR_NO_SUBSCRIPTIONS_WITHOUT_DEPLOYMENT)
                param = get_ordering_parameter(context.order, Param.MEMBERSHIP_ID.value)
                context.order = set_ordering_parameter_error(
                    context.order,
                    Param.MEMBERSHIP_ID.value,
                    ERR_ADOBE_MEMBERSHIP_ID.to_dict(
                        title=param["name"], details=ERR_NO_SUBSCRIPTIONS_WITHOUT_DEPLOYMENT
                    ),
                )
                context.validation_succeeded = False
                return
            context.validation_succeeded = True
            return

        next_step(mpt_client, context)
