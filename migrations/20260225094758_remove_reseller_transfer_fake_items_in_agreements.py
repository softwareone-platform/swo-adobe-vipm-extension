import logging
import os

from mpt_api_client import RQLQuery
from mpt_api_client.resources.commerce.agreements import Agreement
from mpt_tool.migration import DataBaseMigration
from mpt_tool.migration.mixins import MPTAPIClientMixin

logger = logging.getLogger(__name__)


class Migration(DataBaseMigration, MPTAPIClientMixin):
    """Migration to remove fake items from Agreements."""

    def run(self):
        """Migration to remove fake items from Agreements."""
        fake_agreement_lines = self.mpt_client.commerce.agreements.filter(
            RQLQuery().n("item.externalIds.vendor").eq("adobe-reseller-transfer").any("lines")
            & RQLQuery(product__id__in=os.environ["MPT_PRODUCTS_IDS"].replace(" ", "").split(","))
        ).select("lines")
        for idx, agreement in enumerate(fake_agreement_lines.iterate(), 1):
            logger.info("%s - processing agreement %s", idx, agreement.id)
            fake_asset_ids = self._get_fake_asset_ids(agreement, idx)
            if not fake_asset_ids:
                logger.info("%s - no fake assets found for agreement %s", idx, agreement.id)
                continue
            logger.info("%s - terminating fake assets for agreement %s", idx, agreement.id)
            for fake_asset_id in fake_asset_ids:
                logger.info("%s - terminating asset %s", idx, fake_asset_id)
                try:
                    self.mpt_client.commerce.assets.terminate(fake_asset_id)
                except Exception:
                    logger.exception("%s - error terminating asset %s", idx, fake_asset_id)

    @staticmethod
    def _get_fake_asset_ids(agreement: Agreement, idx: int) -> set:
        try:
            return {
                line["asset"]["id"]
                for line in agreement.to_dict()["lines"]
                if line["item"]["externalIds"]["vendor"] == "adobe-reseller-transfer"
            }
        except (KeyError, TypeError):
            logger.exception("%s - error getting fake assets from agreement %s", idx, agreement.id)
            return set()
