import logging
import os

from mpt_api_client import RQLQuery
from mpt_tool.migration import SchemaBaseMigration
from mpt_tool.migration.mixins import MPTAPIClientMixin

logger = logging.getLogger(__name__)


class Migration(SchemaBaseMigration, MPTAPIClientMixin):
    """Migration to unpublish fake items."""

    def run(self):
        """Migration to unpublish fake items."""
        items_service = self.mpt_client.catalog.items
        fake_items = items_service.filter(
            RQLQuery("externalIds.vendor").eq("adobe-reseller-transfer")
            & RQLQuery(product__id__in=os.environ["MPT_PRODUCTS_IDS"].replace(" ", "").split(","))
        )
        for idx, fake_item in enumerate(fake_items.iterate(), 1):
            logger.info("%s - unpublish item %s", idx, fake_item.id)
            try:
                items_service.unpublish(fake_item.id)
            except Exception:
                logger.exception("%s - error processing item %s", idx, fake_item.id)
