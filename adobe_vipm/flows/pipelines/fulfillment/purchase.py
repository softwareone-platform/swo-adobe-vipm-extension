from typing import override

from mpt_extension_sdk.pipeline import BaseStep

from adobe_vipm.flows.constants import TEMPLATE_NAME_PURCHASE
from adobe_vipm.flows.pipelines.base import AdobeOrderPipeline
from adobe_vipm.flows.steps.complete_order import CompleteOrder
from adobe_vipm.flows.steps.create_adobe_customer import CreateAdobeCustomer
from adobe_vipm.flows.steps.create_or_update_assets import CreateOrUpdateAssets
from adobe_vipm.flows.steps.create_or_update_subscriptions import CreateOrUpdateSubscriptions
from adobe_vipm.flows.steps.get_preview_order import GetPreviewOrder
from adobe_vipm.flows.steps.nullify_flex_discount_param import NullifyFlexDiscountParam
from adobe_vipm.flows.steps.prepare_customer_data import PrepareCustomerData
from adobe_vipm.flows.steps.refresh_customer import RefreshCustomer
from adobe_vipm.flows.steps.set_adobe_customer import SetAdobeCustomer
from adobe_vipm.flows.steps.set_or_update_coterm_date import SetOrUpdateCotermDate
from adobe_vipm.flows.steps.setup_due_date import SetupDueDate
from adobe_vipm.flows.steps.start_order_processing import StartOrderProcessing
from adobe_vipm.flows.steps.submit_new_order import SubmitNewOrder
from adobe_vipm.flows.steps.sync_agreement import SyncAgreement
from adobe_vipm.flows.steps.update_agreement_params_visibility import (
    UpdateAgreementParamsVisibility,
)
from adobe_vipm.flows.steps.update_prices import UpdatePrices
from adobe_vipm.flows.steps.validate_duplicate_lines import ValidateDuplicateLines
from adobe_vipm.flows.steps.validate_education_sub_segments import ValidateEducationSubSegments
from adobe_vipm.flows.steps.validate_government_lga import ValidateGovernmentLGA
from adobe_vipm.flows.steps.validate_three_yc_commitment import Validate3YCCommitment


class PurchasePipeline(AdobeOrderPipeline):
    """Pipeline for purchase order fulfillment."""

    @override
    @property
    def steps(self) -> list[BaseStep]:
        return [
            SetAdobeCustomer(),
            StartOrderProcessing(template_name=TEMPLATE_NAME_PURCHASE),
            SetupDueDate(),
            ValidateDuplicateLines(),
            ValidateGovernmentLGA(),
            PrepareCustomerData(),
            CreateAdobeCustomer(),
            ValidateEducationSubSegments(),
            Validate3YCCommitment(),
            GetPreviewOrder(),
            UpdatePrices(),
            SubmitNewOrder(),
            CreateOrUpdateAssets(),
            CreateOrUpdateSubscriptions(),
            RefreshCustomer(),
            SetOrUpdateCotermDate(),
            UpdateAgreementParamsVisibility(),
            CompleteOrder(template_name=TEMPLATE_NAME_PURCHASE),
            NullifyFlexDiscountParam(),
            SyncAgreement(),
        ]
