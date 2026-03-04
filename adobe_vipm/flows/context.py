import datetime as dt
from dataclasses import dataclass, field
from typing import Any

from adobe_vipm.flows.constants import Param
from adobe_vipm.flows.utils import get_fulfillment_parameter, get_ordering_parameter


@dataclass
class Context:
    """Order flow processing context."""

    order: dict
    due_date: dt.date | None = None
    downsize_lines: list = field(default_factory=list)
    upsize_lines: list = field(default_factory=list)
    new_lines: list = field(default_factory=list)
    type: str | None = None
    product_id: str | None = None
    market_segment: str | None = None
    agreement_id: str | None = None
    order_id: str | None = None
    authorization_id: str | None = None
    seller_id: str | None = None
    currency: str | None = None
    validation_succeeded: bool = True
    adobe_customer_id: str | None = None
    adobe_customer: dict | None = None
    adobe_new_order_id: str | None = None
    adobe_preview_order: dict | None = None
    adobe_new_order: dict | None = None
    adobe_returnable_orders: dict = field(default_factory=dict)
    adobe_return_orders: dict = field(default_factory=dict)
    membership_id: str | None = None
    adobe_transfer: dict | None = None
    adobe_transfer_order: dict = field(default_factory=dict)

    def __str__(self):
        due_date = self.due_date.strftime("%Y-%m-%d") if self.due_date else "-"
        return (
            f"{self.product_id} {(self.type or '-').upper()} {self.agreement_id} {self.order_id} "
            f"{self.authorization_id} {due_date} "
            f"{self.adobe_customer_id or '-'} {self.adobe_new_order_id or '-'}"
        )

    @property
    def customer_data(self) -> dict[str, Any]:
        """Customer data extracted from the corresponding parameters."""
        customer_data = {}
        for param_external_id in (
            Param.COMPANY_NAME,
            Param.ADDRESS,
            Param.CONTACT,
            Param.THREE_YC,
            Param.THREE_YC_CONSUMABLES,
            Param.THREE_YC_LICENSES,
            Param.AGENCY_TYPE,
        ):
            ordering_param = get_ordering_parameter(self.order, param_external_id)
            customer_data[param_external_id.value] = ordering_param.get("value")

        for param_external_id in (Param.DEPLOYMENT_ID, Param.DEPLOYMENTS):
            fulfillment_param = get_fulfillment_parameter(self.order, param_external_id)
            customer_data[param_external_id.value] = fulfillment_param.get("value")

        return customer_data
