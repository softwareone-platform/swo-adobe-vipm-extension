import logging
from typing import Any

from mpt_extension_sdk.mpt_http.mpt import get_template_by_name

from adobe_vipm.flows.utils import get_template_name_by_subscription
from adobe_vipm.shared import mpt_client

logger = logging.getLogger(__name__)


def get_template_data_by_adobe_subscription(
    adobe_subscription: dict[str, Any], product_id: str
) -> dict[str, Any]:
    """Get template data by Adobe subscription.

    Args:
        adobe_subscription: The Adobe subscription data.
        product_id: The product identifier.

    Returns:
        A dictionary with template data if found, otherwise None.

    """
    template_name = get_template_name_by_subscription(adobe_subscription)
    template = get_template_by_name(mpt_client, product_id, template_name)
    if template:
        template_data = {
            "id": template["id"],
            "name": template["name"],
        }
    else:
        logger.warning("Template %s not found for product %s", template_name, product_id)
        template_data = None

    return template_data
