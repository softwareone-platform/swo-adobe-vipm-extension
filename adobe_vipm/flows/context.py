from dataclasses import dataclass, field


@dataclass
class Context:
    order: dict
    current_attempt: int = 0
    downsize_lines: list = field(default_factory=list)
    upsize_lines: list = field(default_factory=list)
    type: str | None = None
    product_id: str | None = None
    agreement_id: str | None = None
    order_id: str | None = None
    authorization_id: str | None = None
    currency: str | None = None
    validation_succeeded: bool = False
    adobe_customer_id: str | None = None
    adobe_customer: dict | None = None
    adobe_new_order_id: str | None = None
    adobe_new_order: dict | None = None
    adobe_returnable_orders: dict = field(default_factory=dict)
    adobe_return_orders: dict = field(default_factory=dict)

    def __str__(self):
        return (
            f"{self.product_id} {(self.type or '-').upper()} {self.agreement_id} {self.order_id} "
            f"{self.authorization_id} {self.current_attempt} "
            f"{self.adobe_customer_id or '-'} {self.adobe_new_order_id or '-'}"
        )
