import copy

from adobe_vipm.flows.constants import PARAM_DEPLOYMENTS
from adobe_vipm.flows.utils.parameter import get_fulfillment_parameter


def get_deployments(order):
    """
    Get the deployments parameter from the order.
    Args:
        order (dict): The order to update.

    Returns:
        list: List of deployments.
    """
    deployments_param = get_fulfillment_parameter(
        order,
        PARAM_DEPLOYMENTS,
    )
    return deployments_param.get("value").split(",") if deployments_param.get("value") else []


def set_deployments(order, deployments):
    """
    Set the deployments parameter on the order.
    Args:
        order (dict): The order to update.
        deployments (list): The value to set.

    Returns:
        dict: The updated order.
    """
    updated_order = copy.deepcopy(order)
    deployments_param = get_fulfillment_parameter(
        updated_order,
        PARAM_DEPLOYMENTS,
    )
    deployments_param["value"] = ",".join(deployments)
    return updated_order


def exclude_items_with_deployment_id(adobe_transfer):
    """
    Excludes items with deployment ID from the transfer order.

    Args:
        adobe_transfer (dict): The Adobe transfer order.

    Returns:
        dict: The Adobe transfer order with items without deployment ID.
    """
    line_items = [item for item in adobe_transfer["lineItems"] if not item.get("deploymentId", "")]
    adobe_transfer["lineItems"] = line_items
    return adobe_transfer


def exclude_subscriptions_with_deployment_id(adobe_subscriptions):
    """
    Excludes subscriptions with deployment ID from the Adobe customer subscriptions.

    Args:
        adobe_subscriptions (dict): The Adobe customer subscriptions.

    Returns:
        dict: The Adobe customer subscriptions with subscriptions without deployment ID.
    """
    items = [item for item in adobe_subscriptions["items"] if not item.get("deploymentId", "")]
    adobe_subscriptions["items"] = items
    return adobe_subscriptions


def get_deployment_id(source):
    """
    Get the deploymentId parameter from the source.
    Args:
        source (dict): The order to update.

    Returns:
        string: The value of the deploymentId parameter.
    """
    param = get_fulfillment_parameter(
        source,
        "deploymentId",
    )
    return param.get("value")
