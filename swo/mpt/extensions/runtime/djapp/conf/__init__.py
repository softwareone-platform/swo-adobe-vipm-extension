from typing import Any


def extract_product_ids(product_ids):
	return product_ids.split(",")


def to_postfix(product_id: str) -> str:
	"""
	Converts SWO MPT product id to the postfix to use in a settings variable
	Example, PRD-1111-1111-1111 -> PRD_1111_1111_1111
	"""
	return product_id.replace("-", "_")


def get_for_product(settings, variable_name: str, product_id: str) -> Any:
	"""
	A shortcut to return product scoped variable from the extension settings.
	For example WEBHOOK_SECRET_<product-id> variable values
	"""
	return settings.EXTENSION_CONFIG[f"{variable_name}_{to_postfix(product_id)}"]
