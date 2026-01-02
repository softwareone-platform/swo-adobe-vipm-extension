from mpt_extension_sdk.mpt_http import mpt

from adobe_vipm.airtable import models
from adobe_vipm.flows import utils as flows_utils
from adobe_vipm.utils import get_commitment_start_date


class PriceManager:
    """
    PriceManager class to manage the prices to update the agreement or subscription.

    Attributes:
        mpt_client: The MPT client.
        adobe_customer: The Adobe customer.
        agreement: The agreement data.
        agreement_lines: The agreement lines.
    """

    def __init__(self, mpt_client, adobe_customer, lines, agreement_id, pricelist_id):
        self._mpt_client = mpt_client
        self._adobe_customer = adobe_customer
        self._lines = lines
        self._agreement_id = agreement_id
        self._pricelist_id = pricelist_id

    def get_sku_prices_for_agreement_lines(self, skus, product_id, currency):
        """Get the prices for the given SKUs.

        Args:
            skus: The SKUs to get the prices for.
            product_id: The product ID.
            currency: The currency.

        Returns:
            A dictionary with the list of SKUs and the prices.
        """
        prices = models.get_sku_price(self._adobe_customer, skus, product_id, currency)
        missing_prices_skus = []
        for line, actual_sku in self._lines:
            if actual_sku not in prices:
                missing_prices_skus.append(actual_sku)
                mpt_price = mpt.get_item_prices_by_pricelist_id(
                    self._mpt_client,
                    self._pricelist_id,
                    line["item"]["id"],
                )
                if mpt_price:
                    prices[actual_sku] = mpt_price[0]["unitPP"]

        self._notify_missing_prices(missing_prices_skus, product_id, currency)
        return prices

    def _notify_missing_prices(self, missing_prices_skus, product_id, currency):
        if missing_prices_skus:
            flows_utils.notify_missing_prices(
                self._agreement_id,
                missing_prices_skus,
                product_id,
                currency,
                get_commitment_start_date(self._adobe_customer),
            )
