from dataclasses import dataclass, field
from datetime import date

from adobe_vipm.flows.utils.date import is_within_last_two_weeks


@dataclass
class Context:
    order: dict
    due_date: date | None = None
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
    customer_data: dict | None = None
    validation_succeeded: bool = True
    adobe_customer_id: str | None = None
    adobe_customer: dict | None = None
    adobe_new_order_id: str | None = None
    adobe_preview_order: dict | None = None
    adobe_new_order: dict | None = None
    adobe_returnable_orders: dict = field(default_factory=dict)
    adobe_return_orders: dict = field(default_factory=dict)
    deployment_id: str | None = None

    def __str__(self):
        due_date = self.due_date.strftime("%Y-%m-%d") if self.due_date else "-"
        return (
            f"{self.product_id} {(self.type or '-').upper()} {self.agreement_id} {self.order_id} "
            f"{self.authorization_id} {due_date} "
            f"{self.adobe_customer_id or '-'} {self.adobe_new_order_id or '-'}"
        )

    def is_within_coterm_window(self):
        """
        Checks if the current date is within the last two weeks before the cotermination date.

        Returns:
            bool: True if within the window, False otherwise
        """
        return (
            self.adobe_customer.get("cotermDate") and
            is_within_last_two_weeks(self.adobe_customer["cotermDate"])
        )

    def has_coterm_date(self):
        """
        Checks if the customer has a cotermination date.

        Returns:
            bool: True if cotermination date exists, False otherwise
        """
        return bool(self.adobe_customer.get("cotermDate"))
