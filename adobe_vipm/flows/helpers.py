"""This module contains orders helper functions."""

import logging

from mpt_extension_sdk.mpt_http.mpt import (
    get_agreement,
    get_licensee,
)

logger = logging.getLogger(__name__)


def populate_order_info(client, order: dict) -> dict:
    """
    Enrich the order with the full representation of the agreement object.

    Args:
        client (MPTClient): an instance of the Marketplace platform client.
        order: the order that is being processed.

    Returns:
        The enriched order.
    """
    order["agreement"] = get_agreement(client, order["agreement"]["id"])
    order["agreement"]["licensee"] = get_licensee(client, order["agreement"]["licensee"]["id"])

    return order
