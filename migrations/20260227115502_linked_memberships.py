import logging
import os

from mpt_tool.migration import SchemaBaseMigration
from mpt_tool.migration.mixins import MPTAPIClientMixin

logger = logging.getLogger(__name__)


class Migration(SchemaBaseMigration, MPTAPIClientMixin):
    """Migration to create parameters for linked memberships in MPT."""

    @classmethod
    def new_parameters(cls):
        """Return the new parameters for linked memberships in MPT."""
        return [
            {
                "externalId": "lmID",
                "displayOrder": 100,
                "scope": "Agreement",
                "phase": "Fulfillment",
                "name": "Linked Membership Id",
                "description": "lmID",
                "multiple": False,
                "constraints": {"hidden": False, "readonly": False, "required": False},
                "options": {
                    "placeholderText": "Linked Membership Id",
                    "hintText": "Linked Membership Id",
                },
                "type": "SingleLineText",
            },
            {
                "externalId": "lmName",
                "displayOrder": 100,
                "scope": "Agreement",
                "phase": "Fulfillment",
                "name": "Linked Membership Name",
                "description": "lmName",
                "multiple": False,
                "constraints": {"hidden": False, "readonly": False, "required": False},
                "options": {
                    "placeholderText": "Linked Membership Name",
                    "hintText": "Linked Membership Name",
                },
                "type": "SingleLineText",
            },
            {
                "externalId": "lmType",
                "displayOrder": 100,
                "scope": "Agreement",
                "phase": "Fulfillment",
                "name": "Linked Membership type",
                "description": "lmType",
                "multiple": False,
                "constraints": {"hidden": False, "readonly": False, "required": False},
                "options": {
                    "placeholderText": "Linked Membership type",
                    "hintText": "Linked Membership type",
                },
                "type": "SingleLineText",
            },
            {
                "externalId": "lmRole",
                "displayOrder": 100,
                "scope": "Agreement",
                "phase": "Fulfillment",
                "name": "Linked Membership role",
                "description": "lmRole",
                "multiple": False,
                "constraints": {"hidden": False, "readonly": False, "required": False},
                "options": {
                    "placeholderText": "Linked Membership role",
                    "hintText": "Linked Membership role",
                },
                "type": "SingleLineText",
            },
            {
                "externalId": "lmCreated",
                "displayOrder": 100,
                "scope": "Agreement",
                "phase": "Fulfillment",
                "multiple": False,
                "description": "lmCreated",
                "type": "Date",
                "constraints": {"hidden": False, "required": False, "readonly": False},
                "name": "Linked membership create date",
                "options": {
                    "type": "Date",
                    "dateRange": False,
                    "name": "Linked membership create date",
                    "hintText": "Linked membership create date",
                },
            },
        ]

    def run(self):  # noqa: C901,WPS210,WPS231,WPS232
        """Create parameters for linked memberships in MPT."""
        product_ids = os.getenv("MPT_PRODUCTS_IDS")
        list_of_product_ids = product_ids.split(",")
        desired_external_ids = {
            new_parameter["externalId"] for new_parameter in self.new_parameters()
        }

        for product_id in list_of_product_ids:
            params_service = self.mpt_client.catalog.products.parameters(product_id)
            existing_external_ids = set()

            for mpt_param in params_service.iterate():
                parameter_dict = mpt_param.to_dict()
                external_id = parameter_dict.get("externalId", "")
                if external_id and parameter_dict.get("status") == "Active":
                    existing_external_ids.add(external_id)

            missing_ids = desired_external_ids - existing_external_ids

            if not missing_ids:
                logger.info("Product %s: all parameters already exist, skipping.", product_id)
                continue

            logger.info("Product %s: missing parameters %s", product_id, missing_ids)
            for param_def in self.new_parameters():
                if param_def["externalId"] in missing_ids:
                    params_service.create(param_def)
                    logger.info("Created parameter %s", param_def["externalId"])
