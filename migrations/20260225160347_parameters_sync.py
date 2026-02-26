import os
from typing import Any, Iterable, Iterator

from django.core.management import call_command
from mpt_api_client import RQLQuery
from mpt_api_client.resources.catalog.products_parameters import Parameter
from mpt_api_client.resources.commerce.agreements import Agreement
from mpt_tool.migration import DataBaseMigration
from mpt_tool.migration.mixins import MPTAPIClientMixin
import typer

agreement_select =[
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

def sync_parameters(
    product_parameters: Iterable[Parameter], agreement_parameters: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Update parameters definition of the agreement parameter with product parameters.

    - If the product parameter exists in the agreement: it updates the
      definition and keeps the value
    - If the product parameter is not in the agreement, it creates it.
    - If the agreement parameter does not exist in the product,
      it deletes it from the agreement.
    """
    updated_parameters = []
    for pp in product_parameters:
        product_param = pp.to_dict()
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
        for ap in agreement_parameters:
            if external_id == ap["externalId"]:
                parameter_data = ap # keeps current parameter data
                #parameter_data["value"] = ap["value"]
                #parameter_data["displayValue"] = ap["displayValue"]
        updated_parameters.append(parameter_data)
    return updated_parameters

class Migration(DataBaseMigration, MPTAPIClientMixin):
    def run(self):
        product_ids = os.getenv("PRODUCT_IDS", "").split(",")
        typer.echo(f"Preparing parameter migration for {', '.join(product_ids)}")
        for product_id in product_ids:
            typer.echo(f"Starting parameters migration for product {product_id}")
            product_parameters = [p.to_dict() for p in self.mpt_client.catalog.products.parameters(product_id).iterate()]
            self._run_product(product_id, product_parameters)

    def _run_product(self, product_id: str, product_parameters: list[dict[str, Any]]):
        typer.echo(f"Processing agreements for product {product_id}")
        agreement_filter = RQLQuery(status="Active") & RQLQuery(product__id=product_id)
        agreement_service = self.mpt_client.commerce.agreements.filter(agreement_filter).order_by("audit.created.at").select(*agreement_select)
        page = agreement_service.fetch_page(0, 0)
        num_agreements = page.meta.pagination.total if page.meta else None
        typer.echo(f"Found {num_agreements if num_agreements is not None else 'unknown'} agreements for product {product_id}")
        with typer.progressbar(
            agreement_service.iterate(),
            length=num_agreements,
            label=f"Migrating {product_id}",
            show_pos=True,
            show_percent=True,
            show_eta=True,
        ) as progressbar:
            for agreement in progressbar:
                progressbar.label = f"Migrating {product_id} - {agreement.id}"
                try:
                    self.sync_product_parameters(product_id, product_parameters, agreement, progressbar)
                except Exception as e:
                    typer.echo(f"Error syncing parameters for agreement {agreement.id}: {e}")
                    continue
                try:
                    self.update_parameters_visibility(agreement)
                except Exception as e:
                    typer.echo(f"Error saving agreement {agreement.id}: {e}")
                try:
                    call_command("sync_agreements", agreements=[agreement.id])
                except Exception as e:
                    typer.echo(f"Error syncing agreement {agreement.id}: {e}")


    def sync_product_parameters(self, product_id: str, product_parameters: Iterable[Parameter], agreement: Agreement, progressbar):
        progressbar.label = f"{product_id} - {agreement.id} - Creating parameters"
        #product_fulfillment_parameters = [param for param in product_parameters if param.get('phase') == "Fulfillment"]
        # product_order_parameters = [param for param in product_parameters if param.get('phase') == "Order"]
        product_fulfillment_parameters: Iterator[Parameter] = filter(lambda param: param.phase == "Fulfillment", product_parameters)
        product_order_parameters: Iterator[Parameter] = filter(lambda param: param.phase == "Order", product_parameters)
        agreement.parameters.fulfillment = sync_parameters(product_fulfillment_parameters, agreement.parameters.fulfillment)
        agreement.parameters.ordering = sync_parameters(product_order_parameters, agreement.parameters.ordering)


    def _agreement_type(self, agreement: Agreement):
        for param in agreement.parameters.ordering:
            if param["externalId"] == "type":
                return param["value"]
        return None


    def update_parameters_visibility(self, agreement: Agreement):
        pass







