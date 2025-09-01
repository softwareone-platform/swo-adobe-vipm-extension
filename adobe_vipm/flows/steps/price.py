import datetime as dt
import logging
from operator import itemgetter

from mpt_extension_sdk.mpt_http.mpt import update_order

from adobe_vipm.adobe.constants import ThreeYearCommitmentStatus
from adobe_vipm.adobe.utils import get_3yc_commitment_request
from adobe_vipm.airtable.models import get_prices_for_3yc_skus, get_prices_for_skus
from adobe_vipm.flows.pipeline import Step
from adobe_vipm.flows.utils.order import get_order_line_by_sku
from adobe_vipm.flows.utils.subscription import get_price_item_by_line_sku
from adobe_vipm.utils import get_3yc_commitment

logger = logging.getLogger(__name__)


class UpdatePrices(Step):
    """Update prices based on airtable and adobe discount level."""

    def __call__(self, client, context, next_step):
        """Update prices based on airtable and adobe discount level."""
        if not (context.adobe_new_order or context.adobe_preview_order):
            next_step(client, context)
            return

        actual_skus = self._get_actual_skus(context)
        prices = self._get_prices_for_skus(context, actual_skus)
        updated_lines = self._create_updated_lines(context, actual_skus, prices)
        self._update_order(client, context, updated_lines)

        next_step(client, context)

    def _get_actual_skus(self, context):
        """Extract SKUs from either new order or preview order."""
        order_data = context.adobe_new_order or context.adobe_preview_order
        return [item["offerId"] for item in order_data["lineItems"]]

    def _get_prices_for_skus(self, context, actual_skus):
        """Get prices for SKUs considering 3YC commitment if applicable."""
        commitment = (
            (
                get_3yc_commitment_request(context.adobe_customer, is_recommitment=False)
                or get_3yc_commitment(context.adobe_customer)
            )
            if context.adobe_customer
            else None
        )
        if self._is_valid_3yc_commitment(commitment):
            return get_prices_for_3yc_skus(
                context.product_id,
                context.currency,
                dt.date.fromisoformat(commitment["startDate"]),
                actual_skus,
            )
        return get_prices_for_skus(context.product_id, context.currency, actual_skus)

    def _is_valid_3yc_commitment(self, commitment):
        """Check if 3YC commitment is valid and active."""
        if not commitment:
            return False

        end_date = dt.date.fromisoformat(commitment["endDate"])

        return (
            commitment["status"]
            in {
                ThreeYearCommitmentStatus.COMMITTED,
                ThreeYearCommitmentStatus.ACTIVE,
                ThreeYearCommitmentStatus.ACCEPTED,
            }
            and end_date >= dt.datetime.now(tz=dt.UTC).date()
        )

    def _create_updated_lines(self, context, actual_skus, prices):
        """Create updated order lines with new prices."""
        updated_lines = []

        # Update lines for actual SKUs
        for sku in actual_skus:
            line = get_order_line_by_sku(context.order, sku)
            new_price_item = get_price_item_by_line_sku(
                prices, line["item"]["externalIds"]["vendor"]
            )
            updated_lines.append({
                "id": line["id"],
                "price": {"unitPP": new_price_item[1]},
            })

        # Add remaining lines with unchanged prices
        updated_lines_ids = {line["id"] for line in updated_lines}
        order_lines = [
            line for line in context.order["lines"] if line["id"] not in updated_lines_ids
        ]
        mapped_lines = [
            {
                "id": line["id"],
                "price": {"unitPP": line["price"]["unitPP"]},
            }
            for line in order_lines
        ]
        updated_lines.extend(mapped_lines)

        return sorted(updated_lines, key=itemgetter("id"))

    def _update_order(self, client, context, lines):
        """Update the order with new prices."""
        update_order(client, context.order_id, lines=lines)
        logger.info("%s: order lines prices updated successfully", context)
