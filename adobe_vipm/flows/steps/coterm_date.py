import datetime as dt
import logging

from mpt_extension_sdk.mpt_http.mpt import update_order

from adobe_vipm.adobe.utils import get_3yc_commitment_request
from adobe_vipm.flows.pipeline import Step
from adobe_vipm.flows.utils.customer import has_coterm_date
from adobe_vipm.flows.utils.parameter import get_coterm_date, set_coterm_date
from adobe_vipm.flows.utils.three_yc import (
    set_adobe_3yc,
    set_adobe_3yc_commitment_request_status,
    set_adobe_3yc_end_date,
    set_adobe_3yc_enroll_status,
    set_adobe_3yc_start_date,
)
from adobe_vipm.utils import get_3yc_commitment

logger = logging.getLogger(__name__)


class SetOrUpdateCotermDate(Step):
    """Set or update the fulfillment parameters `cotermDate` with Adobe customer coterm date."""

    def __call__(self, client, context, next_step):
        """Set or update the fulfillment parameters `cotermDate` with Adobe customer coterm date."""
        if has_coterm_date(context.adobe_customer):
            coterm_date = dt.datetime.fromisoformat(context.adobe_customer["cotermDate"]).date()

            needs_update = self.update_coterm_if_needed(context, coterm_date)
            needs_update |= self.commitment_update_if_needed(context)

            if needs_update:
                self.update_order_parameters(client, context, coterm_date)

        next_step(client, context)

    def update_coterm_if_needed(self, context, coterm_date):
        """
        Updates coterm date if coterm date differs in MPT and Adobe.

        Args:
            context (Context): step context
            coterm_date (date): coterm date from Adobe API

        Returns:
            bool: if it need to be updated or not
        """
        needs_update = False
        if coterm_date.isoformat() != get_coterm_date(context.order):
            context.order = set_coterm_date(context.order, coterm_date.isoformat())
            needs_update = True
        return needs_update

    def commitment_update_if_needed(self, context):
        """
        Updates commitment date if commitment exists on Adobe API.

        Args:
            context (Context): step context

        Returns:
            bool: was commitment date updated
        """
        if not context.adobe_customer:
            return False
        commitment = get_3yc_commitment_request(
            context.adobe_customer,
            is_recommitment=False,
        ) or get_3yc_commitment(context.adobe_customer)

        if not commitment:
            return False
        context.order = set_adobe_3yc_enroll_status(context.order, commitment["status"])
        context.order = set_adobe_3yc_commitment_request_status(context.order, None)
        context.order = set_adobe_3yc_start_date(context.order, commitment["startDate"])
        context.order = set_adobe_3yc_end_date(context.order, commitment["endDate"])
        context.order = set_adobe_3yc(context.order, None)
        return True

    def update_order_parameters(self, client, context, coterm_date):
        """
        Update 3YC parameters in MPT Order.

        Args:
            client (MPTClient): MPT API client
            context (Context): Step context
            coterm_date: Adobe coterm date
        """
        update_order(client, context.order_id, parameters=context.order["parameters"])
        updated_params = {"coterm_date": coterm_date.isoformat()}
        commitment = get_3yc_commitment_request(
            context.adobe_customer,
            is_recommitment=False,
        ) or get_3yc_commitment(context.adobe_customer)
        if commitment:
            updated_params.update({
                "3yc_enroll_status": commitment["status"],
                "3yc_commitment_request_status": None,
                "3yc_start_date": commitment["startDate"],
                "3yc_end_date": commitment["endDate"],
                "3yc": None,
            })
        params_str = ", ".join(f"{k}={v}" for k, v in updated_params.items())
        logger.info("%s: Updated parameters: %s", context, params_str)
