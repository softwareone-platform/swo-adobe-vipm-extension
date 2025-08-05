import datetime as dt
from dataclasses import dataclass, field


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
