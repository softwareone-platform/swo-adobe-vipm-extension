import datetime as dt
from dataclasses import dataclass, field
from typing import Self

from mpt_extension_sdk.errors.runtime import ConfigError
from mpt_extension_sdk.pipeline import ContextAdapter, OrderContext

from adobe_vipm.adobe.models import AdobeCustomer, AdobeOrder, AdobePreviewOrder
from adobe_vipm.flows.constants import MARKET_SEGMENT_LARGE_GOVERNMENT_AGENCY, Param


@dataclass
class AdobeContext:
    """Adobe-specific mutable state carried through the order pipeline."""

    adobe_customer: AdobeCustomer = None
    adobe_orders: list[AdobeOrder] = field(default_factory=list)
    adobe_return_orders: list[AdobeOrder] = field(default_factory=list)
    adobe_preview_order: AdobePreviewOrder = None
    adobe_new_order: AdobeOrder = None


@dataclass
class AdobeOrderContext(AdobeContext, OrderContext, ContextAdapter):
    """Order context enriched with Adobe-specific data and helpers."""

    @property
    def adobe_customer_id(self) -> str | None:
        """Return the Adobe customer identifier from fulfillment parameters."""
        if not self.adobe_customer:
            return None

        return self.adobe_customer.customer_id

    @property
    def adobe_order_id(self) -> str | None:
        """Return the vendor-facing Adobe order identifier."""
        return self.order.external_ids.vendor

    @property
    def customer_data(self) -> dict:
        """Return the customer data for the order."""
        customer_data = {}
        for param_ext_id in (
            Param.COMPANY_NAME,
            Param.ADDRESS,
            Param.CONTACT,
            Param.THREE_YC,
            Param.THREE_YC_CONSUMABLES,
            Param.THREE_YC_LICENSES,
            Param.AGENCY_TYPE,
        ):
            customer_data[param_ext_id.value] = self.order.parameters.get_ordering_value(
                param_ext_id
            )

        for param_ext_id in (Param.DEPLOYMENT_ID, Param.DEPLOYMENTS):
            customer_data[param_ext_id.value] = self.order.parameters.get_fulfillment_value(
                param_ext_id
            )

        return customer_data

    # REVIEW: should due date part of the order instead of the root context?
    @property
    def due_date(self) -> dt.date | None:
        """Return the due date for the order."""
        param_value = self.order.parameters.get_fulfillment_value(Param.DUE_DATE)
        if param_value is None:
            return None

        return dt.datetime.strptime(param_value, "%Y-%m-%d").replace(tzinfo=dt.UTC).date()

    @property
    def is_large_government_agency(self) -> bool:
        """Return whether the current product targets the LGA segment."""
        return self.market_segment == MARKET_SEGMENT_LARGE_GOVERNMENT_AGENCY

    @property
    def market_segment(self):
        """Return the market segment for the current product."""
        try:
            return self.ext_settings.product_segment[self.order.product_id]
        except KeyError:
            raise ConfigError(f"No market segment found for product {self.order.product_id}")

    @classmethod
    def from_context(cls, ctx: OrderContext) -> Self:
        """Build an Adobe-specific context from the SDK-provided order context."""
        return cls(
            ext_settings=ctx.ext_settings,
            runtime_settings=ctx.runtime_settings,
            account_settings=ctx.account_settings,
            meta=ctx.meta,
            logger=ctx.logger,
            mpt_api_service=ctx.mpt_api_service,
            order=ctx.order,
            order_state=ctx.order_state,
            state=ctx.state,
        )

    def with_due_date(self, due_date: dt.date | None):
        """Return order parameters with the desired due date value."""
        due_date_value = None if due_date is None else due_date.isoformat()
        return self.order.parameters.with_fulfillment_value(Param.DUE_DATE, due_date_value)
