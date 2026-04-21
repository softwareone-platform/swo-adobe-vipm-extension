import logging
import os

from mpt_tool.migration import SchemaBaseMigration
from mpt_tool.migration.mixins import MPTAPIClientMixin

logger = logging.getLogger(__name__)


class Migration(SchemaBaseMigration, MPTAPIClientMixin):
    """Migration to create Adobe Order IDs parameter in Order scope."""

    @staticmethod
    def new_parameter() -> dict:
        """Return parameter definition for Adobe Order IDs."""
        return {
            "externalId": "adobeOrderIds",
            "displayOrder": 100,
            "scope": "Order",
            "phase": "Order",
            "name": "Adobe Order IDs",
            "description": "Adobe Order IDs",
            "multiple": False,
            "constraints": {"hidden": True, "readonly": True, "required": False},
            "options": {
                "placeholderText": "Adobe Order IDs",
                "hintText": "Comma-separated Adobe order IDs",
            },
            "type": "SingleLineText",
        }

    def run(self):
        """Create the Adobe Order IDs order parameter for configured products if missing."""
        product_ids = os.getenv("MPT_PRODUCTS_IDS", "")
        list_of_product_ids = [
            product_id.strip() for product_id in product_ids.split(",") if product_id.strip()
        ]

        if not list_of_product_ids:
            logger.info("MPT_PRODUCTS_IDS is empty. No products to process.")
            return

        param_def = self.new_parameter()
        external_id = param_def["externalId"]

        for product_id in list_of_product_ids:
            params_service = self.mpt_client.catalog.products.parameters(product_id)
            existing_external_ids = {
                parameter.to_dict().get("externalId", "")
                for parameter in params_service.iterate()
                if parameter.to_dict().get("status") == "Active"
            }

            if external_id in existing_external_ids:
                logger.info(
                    "Product %s: parameter %s already exists, skipping.",
                    product_id,
                    external_id,
                )
                continue

            params_service.create(param_def)
            logger.info("Product %s: created parameter %s.", product_id, external_id)
