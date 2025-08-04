import copy

from adobe_vipm.flows.constants import Param
from adobe_vipm.flows.utils.parameter import get_fulfillment_parameter


def get_deployments(order: dict) -> list[str]:
    """
    Get the deployments parameter from the order.

    Args:
        order: MPT order.

    Returns:
        List of deployment ids.
    """
    deployments_param = get_fulfillment_parameter(
        order,
        Param.DEPLOYMENTS.value,
    )
    return deployments_param.get("value").split(",") if deployments_param.get("value") else []


def set_deployments(order: dict, deployments: list[str]) -> dict:
    """
    Set the deployments parameter on the order.

    Args:
        order: The order to update.
        deployments: Deployment ids to set to the order parameter.

    Returns:
        Updated MPT order.
    """
    updated_order = copy.deepcopy(order)
    deployments_param = get_fulfillment_parameter(
        updated_order,
        Param.DEPLOYMENTS.value,
    )
    deployments_param["value"] = ",".join(deployments)
    return updated_order


def exclude_items_with_deployment_id(adobe_transfer: dict) -> dict:
    """
    Excludes items with deployment ID from the transfer order.

    Args:
        adobe_transfer: The Adobe transfer order.

    Returns:
        The Adobe transfer order with items without deployment ID.
    """
    line_items = [item for item in adobe_transfer["lineItems"] if not item.get("deploymentId", "")]
    adobe_transfer["lineItems"] = line_items
    return adobe_transfer


def exclude_subscriptions_with_deployment_id(adobe_subscriptions: dict) -> dict:
    """
    Excludes subscriptions with deployment ID from the Adobe customer subscriptions.

    Args:
        adobe_subscriptions: The Adobe customer subscriptions.

    Returns:
        The Adobe customer subscriptions with subscriptions without deployment ID.
    """
    items = [item for item in adobe_subscriptions["items"] if not item.get("deploymentId", "")]
    adobe_subscriptions["items"] = items
    return adobe_subscriptions


def get_deployment_id(source: dict) -> str | None:
    """
    Get the deploymentId parameter from the source.

    Args:
        source (dict): MPT order or agreement.

    Returns:
        The value of the deploymentId parameter.
    """
    param = get_fulfillment_parameter(
        source,
        "deploymentId",
    )
    return param.get("value")
