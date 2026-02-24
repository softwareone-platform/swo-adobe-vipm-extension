import logging
from collections.abc import Iterator
from functools import cache
from typing import Any

import typer
from django.core.management import call_command
from mpt_api_client import MPTClient
from mpt_api_client.resources.commerce.agreements import Agreement, AgreementsService
from mpt_api_client.rql import RQLQuery

PARAMETER_PHASE_ORDERING = "Order"
PARAMETER_PHASE_FULFILLMENT = "Fulfillment"

AGREEMENT_PARAM_PHASE_FULFILLMENT = "fulfillment"
AGREEMENT_PARAM_PHASE_ORDERING = "ordering"

AGREEMENT_NEW_ACCOUNT = "new_account"
AGREEMENT_VIPM_MIGRATE = "vipm_migrate"
AGREEMENT_RESELLER_TRANSFER = "reseller_transfer"

logger = logging.getLogger(__name__)


class AgreementClient:
    """Client for agreements."""

    def __init__(self, mpt_client: MPTClient):
        self.mpt_client = mpt_client

    def count(self, product_id: str) -> int | None:
        """Count the number of agreements for the given product."""
        meta = self._agreements_service(product_id).fetch_page(0, 0).meta
        if not meta:
            return None
        return meta.pagination.total

    def iterate(self, product_id: str) -> Iterator[Agreement]:
        """Iterate over agreements for the given product."""
        return self._agreements_service(product_id).iterate()

    def _agreements_service(self, product_id: str) -> AgreementsService:
        select = [
            "-listing",
            "-authorization",
            "-vendor",
            "-client",
            "-price",
            "-subscriptions",
            "-template",
            "-lines",
            "-assets",
            "-termsAndConditions",
        ]
        agreement_filter = RQLQuery(status="Active") & RQLQuery(product__id=product_id)
        return (
            self.mpt_client.commerce.agreements
            .filter(agreement_filter)
            .order_by("audit.created.at")
            .select(*select)
        )

    def update(self, agreement_id: str, agreement_data: dict[str, Any]) -> Agreement:
        """Update an agreement."""
        return self.mpt_client.commerce.agreements.update(agreement_id, agreement_data)


class ProductParameterClient:
    """Client for product parameters."""

    def __init__(self, mpt_client: MPTClient):
        self.mpt_client = mpt_client

    @cache  # noqa: B019
    def get_product_parameters(self, product_id: str) -> list[Any]:
        """Get all parameters defined in the given product."""
        return list(self.mpt_client.catalog.products.parameters(product_id).iterate())

    def get_fulfillment_parameters(self, product_id: str) -> list[dict[str, Any]]:
        """Get product fulfillment parameters."""
        return [
            param
            for param in self.get_product_parameters(product_id)
            if param.phase == PARAMETER_PHASE_FULFILLMENT
        ]

    def get_ordering_parameters(self, product_id: str) -> list[dict[str, Any]]:
        """Get product ordering parameters."""
        return [
            param
            for param in self.get_product_parameters(product_id)
            if param.phase == PARAMETER_PHASE_ORDERING
        ]


class ParameterManager:
    """Manage parameters."""

    @staticmethod
    def migrate_parameters(
        product_parameters: list[dict[str, Any]], agreement_parameters: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        """Update parameters definition of the agreement parameter with product parameters.

        - If the product parameter exists in the agreement: it updates the
          definition and keeps the value
        - If the product parameter is not in the agreement, it creates it.
        - If the agreement parameter does not exist in the product,
          it deletes it from the agreement.
        """
        updated_parameters = []
        for product_param in product_parameters:
            external_id = product_param["externalId"]
            parameter_data = {
                "id": product_param["id"],
                "externalId": product_param["externalId"],
                "name": product_param["name"],
                "type": product_param["type"],
                "phase": product_param["phase"],
                "scope": product_param["scope"],
                "multiple": product_param["multiple"],
                "constraints": product_param["constraints"],
                "value": None,
            }

            # If the parameter exists, use the value from the agreement
            for p in agreement_parameters:
                if external_id == p["externalId"]:
                    parameter_data["value"] = p["value"]
                    parameter_data["displayValue"] = p["displayValue"]
            updated_parameters.append(parameter_data)
        return updated_parameters


class MigrateProductAgreementParameters:
    """Migrate product parameters to agreements."""

    def __init__(self, mpt_client: MPTClient, *, dry_run: bool = False):
        self.mpt_client = mpt_client
        self.agreement_client = AgreementClient(self.mpt_client)
        self.product_parameter_client = ProductParameterClient(self.mpt_client)
        self.dry_run = dry_run

    def migrate_product_parameters(self, product_id: str) -> None:
        """Migrate product parameters to agreements parameters and updates visibility."""
        print(f"Starting migration for product {product_id}")
        print("Counting agreements...")

        num_agreements = self.agreement_client.count(product_id)
        print("Querying agreements...")
        with typer.progressbar(
            self.agreement_client.iterate(product_id),
            length=num_agreements,
            label=f"Migrating agreements for product {product_id}",
            show_pos=True,
            show_percent=True,
            show_eta=True,
        ) as agreements:
            for agreement in agreements:
                self.process_agreement(agreement.to_dict())

    def process_agreement(self, agreement: dict[str, Any]) -> None:
        """Create missing parameters for agreements."""
        self.update_agreement_parameters(agreement)
        self.sync_agreement(agreement["id"])

    def update_agreement_parameters(self, agreement: dict[str, Any]) -> None:
        """Create missing parameters for agreements.

        Compares agreement.parameters with product.parameters and creates missing parameters for
        the agreement.
        """
        product_fulfilment_parameters = self.product_parameter_client.get_fulfillment_parameters(
            agreement["product"]["id"]
        )
        fulfilment_parameters = ParameterManager.migrate_parameters(
            product_fulfilment_parameters, agreement["parameters"]["fulfillment"]
        )

        product_ordering_parameters = self.product_parameter_client.get_ordering_parameters(
            agreement["product"]["id"]
        )
        ordering_parameters = ParameterManager.migrate_parameters(
            product_ordering_parameters, agreement["parameters"]["ordering"]
        )
        parameters = {"fulfillment": fulfilment_parameters, "ordering": ordering_parameters}
        if self.dry_run:
            logger.info(
                "Dry run mode: skipping agreement %s with parameters: %s", agreement["id"], parameters
            )
            return

        logger.info("Updating agreement %s with parameters: %s", agreement["id"], parameters)
        self.agreement_client.update(agreement["id"], {"parameters": parameters})

    def sync_agreement(self, agreement_id: str) -> None:
        """Sync agreement parameters with product parameters."""
        if self.dry_run:
            logger.info("Dry run mode: skipping agreement %s", agreement_id)
            return
        call_command("sync_agreements", agreements=[agreement_id])
