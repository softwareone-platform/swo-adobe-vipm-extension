import logging
import os

from mpt_api_client import RQLQuery
from mpt_tool.migration import SchemaBaseMigration
from mpt_tool.migration.mixins import MPTAPIClientMixin

logger = logging.getLogger(__name__)

PARAMETER_CONTEXTS = ("Purchase", "Change")
DETAILS_GROUP_NAME = "Details"


class Migration(SchemaBaseMigration, MPTAPIClientMixin):
    """Migration to create Late Renewals Info parameter in Order scope."""

    @staticmethod
    def new_parameter() -> dict:
        """Return parameter definition for Late Renewals Info."""
        return {
            "externalId": "lateRenewalsInfo",
            "displayOrder": 100,
            "context": "Purchase",
            "scope": "Order",
            "phase": "Order",
            "name": "Late Renewals Info",
            "description": "Late Renewals Info",
            "multiple": False,
            "constraints": {"hidden": True, "readonly": True, "required": False},
            "options": {
                "type": "DataObject",
                "objectType": "Json",
                "defaultValue": "{}",
                "name": "lateRenewalsInfo",
                "hintText": "lateRenewalsInfo"
            },
            "type": "DataObject",
        }


    def run(self):
        """Create the Late Renewals Info order parameter for configured products if missing."""
        product_ids = [
            pid.strip() for pid in os.getenv("MPT_PRODUCTS_IDS", "").split(",") if pid.strip()
        ]
        if not product_ids:
            logger.info("MPT_PRODUCTS_IDS is empty. No products to process.")
            return

        for product_id in product_ids:
            self._create_parameter_for_product(product_id)

    def _create_parameter_for_product(self, product_id: str) -> None:
        param_def = self.new_parameter()
        external_id = param_def["externalId"]
        params_service = self.mpt_client.catalog.products.parameters(product_id)

        if external_id in self._active_external_ids(params_service):
            logger.info(
                "Product %s: parameter %s already exists, skipping.",
                product_id,
                external_id,
            )
            return

        base_param = {**param_def, "group": self._fetch_details_group(product_id)}
        for context in PARAMETER_CONTEXTS:
            params_service.create({**base_param, "context": context})
            logger.info(
                "Product %s: created parameter %s for context %s.",
                product_id,
                external_id,
                context,
            )

    @staticmethod
    def _active_external_ids(params_service) -> set[str]:
        return {
            data.get("externalId", "")
            for data in (parameter.to_dict() for parameter in params_service.iterate())
            if data.get("status") == "Active"
        }

    def _fetch_details_group(self, product_id: str) -> dict:
        group = (
            self.mpt_client.catalog.products.parameter_groups(product_id)
            .filter(RQLQuery(name=DETAILS_GROUP_NAME))
            .fetch_one()
            .to_dict()
        )
        return {"id": group["id"], "name": group["name"]}
