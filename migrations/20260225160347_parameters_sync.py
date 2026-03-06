import copy
import json
import logging
import os
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

import typer
from mpt_api_client import RQLQuery
from mpt_api_client.exceptions import MPTAPIError
from mpt_api_client.models import ResourceData
from mpt_extension_sdk.runtime.utils import initialize_extension
from mpt_tool.migration import DataBaseMigration
from mpt_tool.migration.mixins import MPTAPIClientMixin


DRY_RUN = False
LOG_LEVEL = logging.INFO


class AgreementTypeEnum(StrEnum):
    New = "New"
    Migrate = "Migrate"
    Transfer = "Transfer"


class SegmentEnum(StrEnum):
    COM = "COM"
    EDU = "EDU"
    GOV = "GOV"


class SubSegmentEnum(StrEnum):
    LGA = "LGA"


agreement_select = [
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
    "parameters",
]

visible_params_rules: dict[str, list[str]] = {
    AgreementTypeEnum.New: [
        "agreementType",
        "companyName",
        "address",
        "contact",
        "customerId",
        "cotermDate",
        "dueDate",
        "lastSyncDate",
        "3YC",
        "3YCLicenses",
        "3YCConsumables",
        "3YCCommitmentRequestStatus",
        "3YCRecommit",
        "3YCRecommitmentRequestStatus",
        "globalCustomer",
        "deploymentId",
        "deployments",
    ],
    AgreementTypeEnum.Migrate: [
        "agreementType",
        "companyName",
        "address",
        "contact",
        "membershipId",
        "customerId",
        "cotermDate",
        "dueDate",
        "lastSyncDate",
        "3YC",
        "3YCLicenses",
        "3YCConsumables",
        "3YCCommitmentRequestStatus",
        "3YCRecommit",
        "3YCRecommitmentRequestStatus",
        "globalCustomer",
        "deploymentId",
        "deployments",
    ],
    AgreementTypeEnum.Transfer: [
        "agreementType",
        "companyName",
        "address",
        "contact",
        "adobeCustomerAdminEmail",
        "changeResellerCode",
        "customerId",
        "cotermDate",
        "dueDate",
        "lastSyncDate",
        "3YC",
        "3YCLicenses",
        "3YCConsumables",
        "3YCCommitmentRequestStatus",
        "3YCRecommit",
        "3YCRecommitmentRequestStatus",
        "globalCustomer",
        "deploymentId",
        "deployments",
    ],
    SubSegmentEnum.LGA: ["companyAgencyType"],
    SegmentEnum.EDU: ["educationSubSegment"],
}


@dataclass
class Context:
    product_id: str
    segment: SegmentEnum
    product_parameters: list[ResourceData]
    progressbar: Any
    agreement: ResourceData
    agreement_type: AgreementTypeEnum
    is_lga: bool = False
    dry_run: bool = False


def get_agreement_type(agreement: ResourceData) -> AgreementTypeEnum:
    """Get the agreement type from the agreement parameters.

    Return:
        New - if the agreement type parameter is found and its value is "New".
        Migrate - For VIPM Migrate accounts
        Transfer - For reseller transfer accounts
    """

    agreement_type_param = next(
        (
            param
            for param in agreement["parameters"]["ordering"]
            if param["externalId"] == "agreementType"
        ),
        None,
    )
    agreement_type = agreement_type_param.get("value", None) if agreement_type_param else None
    if agreement_type == "New":
        return AgreementTypeEnum.New
    if agreement_type == "Migrate":
        return AgreementTypeEnum.Migrate
    if agreement_type == "Transfer":
        return AgreementTypeEnum.Transfer
    raise ValueError(f"{agreement['id']} - Invalid agreement type: `{agreement_type}`")


def get_product_segment(product_id: str) -> SegmentEnum:
    """Get the product segment from the product ID.

    raw_segment can be: COM, EDU, GOV, GOV_LGA
    Adobe segments are: COM, EDU, and GOV.

    Returns:
        str: The adobe product segment for the given product ID.
    """
    segments_str = os.getenv("EXT_PRODUCT_SEGMENT", "{}")
    segments_data = json.loads(segments_str)
    if product_id not in segments_data:
        raise ValueError(f"Product ID {product_id} segment not found.")
    raw_segment = segments_data[product_id]
    if "COM" in raw_segment:
        return SegmentEnum.COM
    if "EDU" in raw_segment:
        return SegmentEnum.EDU
    if "GOV" in raw_segment:
        return SegmentEnum.GOV
    raise ValueError(
        f"Product ID {product_id} segment must contain one of COM, EDU, GOV. Got: {raw_segment}"
    )


def is_product_lga(product_id: str) -> bool:
    """Check if the product ID is a LGA product."""
    segments_str = os.getenv("EXT_PRODUCT_SEGMENT", "{}")
    segments_data = json.loads(segments_str)
    if product_id not in segments_data.keys():
        raise ValueError(f"Product ID {product_id} segment not found.")
    raw_segment = segments_data[product_id]
    return "LGA" in raw_segment


def sync_parameters(
    product_parameters: Iterable[ResourceData], agreement_parameters: Iterable[ResourceData]
) -> list[ResourceData]:
    """Update parameters definition of the agreement parameter with product parameters.

    - If the product parameter exists in the agreement: it updates the
      definition and keeps the value
    - If the product parameter is not in the agreement, it creates it.
    - If the agreement parameter does not exist in the product,
      it deletes it from the agreement.
    """
    updated_parameters = []
    for pp in product_parameters:
        product_param = pp
        external_id = product_param["externalId"]
        parameter_data = {
            "externalId": external_id,
            "name": product_param["name"],
            "type": product_param["type"],
            "phase": product_param["phase"],
            "scope": product_param["scope"],
            "multiple": product_param["multiple"],
            "constraints": product_param["constraints"],
            "value": product_param.get("value", product_param.get("defaultValue", None)),
        }

        # If the parameter exists, use the value from the agreement
        for ap in agreement_parameters:
            if external_id == ap["externalId"]:
                parameter_data = (
                    ap  # overwrites product parameter with existing agreement parameter
                )
                del parameter_data["id"]  # remove id to avoid conflicts

        updated_parameters.append(parameter_data)
    return updated_parameters


def update_parameter_hidden(agreement: ResourceData, external_id: str, *, hidden: bool):
    parameter = next(
        (
            param
            for param in agreement["parameters"]["ordering"]
            if param["externalId"] == external_id
        ),
        None,
    )
    if parameter:
        constraints = parameter.get("constraints", {})
        constraints["hidden"] = hidden
        parameter["constraints"] = constraints
        return
    parameter = next(
        (
            param
            for param in agreement["parameters"]["fulfillment"]
            if param["externalId"] == external_id
        ),
        None,
    )
    if parameter:
        constraints = parameter.get("constraints", {})
        constraints["hidden"] = hidden
        parameter["constraints"] = constraints
        return
    raise ValueError(f"Parameter with external id {external_id} not found")


class Migration(DataBaseMigration, MPTAPIClientMixin):
    """Migrate parameters for a product.

    1. Download product parameters
    2. Get active agreements for the product
    3. Sync agreements parameters with product parameters
    4. Update agreement parameters visibility
    5. Save agreement
    6. Sync agreements with Adobe
    """

    def run(self):
        self.log.setLevel(LOG_LEVEL)
        initialize_extension({})
        product_ids = os.getenv("MPT_PRODUCTS_IDS", "").split(",")
        self.log.info(product_ids)
        self.log.info(f"Preparing parameter migration for {', '.join(product_ids)}")
        for product_id in product_ids:
            self.log.info(f"Starting parameters migration for product `{product_id}`")
            try:
                self._run_product(product_id)
            except Exception as e:
                self.log.exception(f"Error migrating parameters for product `{product_id}`: {e}")
                raise

    def _run_product(self, product_id: str):
        """Migrate parameters for a product."""
        self.log.info(f"Getting product {product_id} parameters")
        product_parameters = [
            p.to_dict()
            for p in self.mpt_client.catalog.products
            .parameters(product_id)
            .filter(RQLQuery(scope="Agreement", status="Active"))
            .iterate()
        ]

        self.log.info(f"Found {len(product_parameters)} parameters for product {product_id}")
        product_params_ids = [p["externalId"] for p in product_parameters]
        self.log.debug(f"Product {product_id} parameters: {product_params_ids}")
        self.log.info(f"Getting product {product_id} segment")
        segment = get_product_segment(product_id)
        self.log.info(f"Product {product_id} segment: {segment}")
        self.log.info(f"Getting agreements for product {product_id}")
        agreement_filter = RQLQuery(status="Active") & RQLQuery(product__id=product_id)
        agreement_service = (
            self.mpt_client.commerce.agreements
            .filter(agreement_filter)
            .order_by("audit.created.at")
            .select(*agreement_select)
        )
        page = agreement_service.fetch_page(0, 0)
        num_agreements = page.meta.pagination.total if page.meta else None
        str_num_agreements = num_agreements if num_agreements is not None else "unknown"
        self.log.info(f"Found {str_num_agreements} agreements for product {product_id}")
        with typer.progressbar(
            agreement_service.iterate(),
            length=num_agreements,
            label=f"Migrating {product_id}",
            show_pos=True,
            show_percent=True,
            show_eta=True,
        ) as progressbar:
            for agreement in progressbar:
                self._run_agreement(
                    product_id, progressbar, segment, product_parameters, agreement.to_dict()
                )

    def _run_agreement(
        self, product_id, progressbar, segment, product_parameters, agreement_data: ResourceData
    ):
        try:
            context = Context(
                product_id=product_id,
                segment=segment,
                product_parameters=product_parameters,
                progressbar=progressbar,
                agreement=agreement_data,
                agreement_type=get_agreement_type(agreement_data),
                is_lga=is_product_lga(product_id),
                dry_run=DRY_RUN,
            )
        except Exception as e:
            self.log.exception(f"Error preparing context for agreement {agreement_data['id']}: {e}")
            return

        context.progressbar.label = f"Migrating {context.product_id} - {context.agreement['id']}"
        try:
            self.sync_product_parameters(context)
        except Exception as e:
            self.log.exception(
                f"Error syncing parameters for agreement {context.agreement['id']}: {e}",
            )
        try:
            self.update_parameters_visibility(context)
        except Exception as e:
            self.log.exception(
                f"Error setting parameters visibility {context.agreement['id']}: {e}"
            )
        try:
            self.save_agreement_parameters(context)
        except Exception as e:
            self.log.exception(f"Error saving agreement {context.agreement['id']}: {e}")
        try:
            self.sync_agreement(context)
        except Exception as e:
            self.log.exception(f"Error syncing agreement {context.agreement['id']}: {e}")

    def save_agreement_parameters(self, context: Context):
        if context.dry_run:
            self.log.info(f"Dry run: Agreement parameters {context.agreement['id']} not saved")
            return

        self.log.info(f"Updating agreement parameters {context.agreement['id']}")
        try:
            response_agreement = self.mpt_client.commerce.agreements.update(
                context.agreement["id"], {"parameters": context.agreement["parameters"]}
            )
            context.agreement = response_agreement.to_dict()
            self.log.info(f"Agreement parameters {context.agreement['id']} updated")
        except MPTAPIError as e:
            self.log.error(f"Error updating agreement parameters {context.agreement['id']}: {e}")

    def sync_agreement(self, context: Context):
        self.log.info(f"Syncing agreement {context.agreement['id']}")
        from django.core.management import call_command

        call_command(
            "sync_agreements", agreements=[context.agreement["id"]], dry_run=context.dry_run
        )
        self.log.info(f"Agreement {context.agreement['id']} synced")

    def sync_product_parameters(self, context: Context):
        """Sync parameters for a product and agreement."""
        context.progressbar.label = (
            f"{context.product_id} - {context.agreement['id']} - Creating parameters"
        )
        self.log.debug(
            f"Agreement {context.agreement['id']} parameters: {context.agreement['parameters']}"
        )
        product_fulfillment_parameters: Iterator[ResourceData] = filter(
            lambda param: param["phase"] == "Fulfillment", context.product_parameters
        )
        product_order_parameters: Iterator[ResourceData] = filter(
            lambda param: param["phase"] == "Order", context.product_parameters
        )
        context.agreement["parameters"]["fulfillment"] = sync_parameters(
            product_fulfillment_parameters, context.agreement["parameters"]["fulfillment"]
        )
        context.agreement["parameters"]["ordering"] = sync_parameters(
            product_order_parameters, context.agreement["parameters"]["ordering"]
        )
        self.log.debug(
            f"Agreement {context.agreement['id']} updated parameters: {context.agreement['parameters']}"
        )

    def update_parameters_visibility(self, context: Context):
        """Update parameters visibility for a product and agreement."""
        context.progressbar.label = (
            f"{context.product_id} - {context.agreement['id']} "
            f"- Updating parameters visibility "
            f"- Type: {context.agreement_type}"
        )
        visible_params = copy.deepcopy(visible_params_rules.get(context.agreement_type, []))
        visible_params.extend(visible_params_rules.get(context.segment, []))
        if context.is_lga:
            visible_params.extend(visible_params_rules.get(SubSegmentEnum.LGA, []))

        self._set_params_visibility(context, visible_params)

    def _set_params_visibility(self, context: Context, visible_params: list[str]):
        for param in context.agreement["parameters"]["fulfillment"]:
            hidden = param["externalId"] not in visible_params
            update_parameter_hidden(context.agreement, param["externalId"], hidden=hidden)
        for param in context.agreement["parameters"]["ordering"]:
            hidden = param["externalId"] not in visible_params
            update_parameter_hidden(context.agreement, param["externalId"], hidden=hidden)
