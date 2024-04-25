from typing import Any


def extract_product_ids(product_ids: str) -> list[str]:
	return product_ids.split(",")


def get_for_product(settings, variable_name: str, product_id: str) -> Any:
	"""
	A shortcut to return product scoped variable from the extension settings.
	"""
	return settings.EXTENSION_CONFIG[variable_name][product_id]
