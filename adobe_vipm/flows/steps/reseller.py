import datetime as dt

from dateutil import parser
from mpt_extension_sdk.mpt_http.mpt import get_product_items_by_skus

from adobe_vipm.adobe.client import get_adobe_client
from adobe_vipm.adobe.errors import AdobeAPIError
from adobe_vipm.flows.constants import (
    ERR_ADOBE_CHANGE_RESELLER_CODE_EMPTY,
    ERR_ADOBE_RESSELLER_CHANGE_LINES,
    ERR_ADOBE_RESSELLER_CHANGE_PREVIEW,
    ERR_ADOBE_RESSELLER_CHANGE_PRODUCT_NOT_CONFIGURED,
    Param,
)
from adobe_vipm.flows.pipeline import Step
from adobe_vipm.flows.utils.order import get_ordering_parameter, set_order_error
from adobe_vipm.flows.utils.parameter import set_ordering_parameter_error


class FetchResellerChangeData(Step):
    """Fetch Adobe reseller change data."""

    def __call__(self, mpt_client, context, next_step):
        """Fetch Adobe reseller change data."""
        authorization_id = context.order["authorization"]["id"]
        seller_id = context.order["agreement"]["seller"]["id"]
        reseller_change_code = get_ordering_parameter(
            context.order, Param.CHANGE_RESELLER_CODE.value
        )
        admin_email = get_ordering_parameter(context.order, Param.ADOBE_CUSTOMER_ADMIN_EMAIL.value)

        adobe_client = get_adobe_client()

        try:
            context.adobe_transfer = adobe_client.preview_reseller_change(
                authorization_id,
                seller_id,
                reseller_change_code.get("value"),
                admin_email.get("value"),
            )
        except AdobeAPIError as e:
            context.order = set_ordering_parameter_error(
                context.order,
                Param.CHANGE_RESELLER_CODE.value,
                ERR_ADOBE_RESSELLER_CHANGE_PREVIEW.to_dict(
                    reseller_change_code=reseller_change_code["value"],
                    error=str(e),
                ),
            )
            context.validation_succeeded = False
            return

        next_step(mpt_client, context)


class ValidateResellerChange(Step):
    """Validates reseller change."""

    def __call__(self, mpt_client, context, next_step):
        """Validates reseller change."""
        expiry_date = context.adobe_transfer["approval"]["expiry"]
        reseller_change_code = get_ordering_parameter(
            context.order, Param.CHANGE_RESELLER_CODE.value
        )["value"]

        parsed_expiry_date = parser.parse(expiry_date)

        if parsed_expiry_date.date() < dt.datetime.now(tz=dt.UTC).date():
            context.order = set_ordering_parameter_error(
                context.order,
                Param.CHANGE_RESELLER_CODE.value,
                ERR_ADOBE_RESSELLER_CHANGE_PREVIEW.to_dict(
                    reseller_change_code=reseller_change_code,
                    error="Reseller change code has expired",
                ),
            )
            context.validation_succeeded = False
            return

        if not context.adobe_transfer["lineItems"]:
            context.order = set_ordering_parameter_error(
                context.order,
                Param.CHANGE_RESELLER_CODE.value,
                ERR_ADOBE_CHANGE_RESELLER_CODE_EMPTY.to_dict(),
            )

        next_step(mpt_client, context)


class AddResellerChangeLinesToOrder(Step):
    """Add lines from reseller change back to the MPT order."""

    def __call__(self, mpt_client, context, next_step):
        """Add lines from reseller change back to the MPT order."""
        reseller_change_item = get_product_items_by_skus(
            mpt_client, context.order["agreement"]["product"]["id"], ["adobe-reseller-transfer"]
        )

        if not reseller_change_item:
            context.order = set_order_error(
                context.order, ERR_ADOBE_RESSELLER_CHANGE_PRODUCT_NOT_CONFIGURED.to_dict()
            )
            context.validation_succeeded = False
            return

        reseller_change_item = reseller_change_item[0]
        context.validation_succeeded = True

        lines = context.order["lines"]
        if lines:
            if len(lines) == 1 and lines[0]["item"]["id"] == reseller_change_item["id"]:
                next_step(mpt_client, context)
                return
            context.order = set_order_error(
                context.order, ERR_ADOBE_RESSELLER_CHANGE_LINES.to_dict()
            )
            context.validation_succeeded = False
        new_line = [
            {
                "item": reseller_change_item,
                "quantity": 1,
                "oldQuantity": 0,
                "price": {"unitPP": 0},
            }
        ]
        context.order["lines"] = new_line
        next_step(mpt_client, context)
