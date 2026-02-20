import logging

from mpt_api_client import RQLQuery
from mpt_tool.migration import DataBaseMigration
from mpt_tool.migration.mixins import MPTAPIClientMixin

logger = logging.getLogger(__name__)


class Migration(DataBaseMigration, MPTAPIClientMixin):
    """Migration to remove fake items."""

    def run(self):
        """Run the migration."""
        fake_items = self.mpt_client.catalog.items.filter(
            RQLQuery("externalIds.vendor").eq("adobe-reseller-transfer")
        )
        for idx, fake_item in enumerate(fake_items.iterate(), 1):
            logger.info("%s - processing catalog item %s", idx, fake_item.id)
            fake_item_dict = fake_item.to_dict()
            try:
                vendor = fake_item_dict["externalIds"]["vendor"]
            except KeyError:
                logger.exception("%s - error processing item %s", idx, fake_item.id)
                continue
            if vendor == "adobe-reseller-transfer":
                logger.info("%s - vendor is: '%s' removing item %s", idx, vendor, fake_item.id)
                try:
                    fake_item.delete()
                except Exception:
                    logger.exception("%s - error processing item %s", idx, fake_item.id)
