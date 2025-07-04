import functools

from adobe_vipm.flows.constants import Param
from adobe_vipm.flows.utils.parameter import get_ordering_parameter
from adobe_vipm.notifications import send_exception


def get_notifications_recipient(order):
    return (get_ordering_parameter(order, Param.CONTACT).get("value", {}) or {}).get("email") or (
        order["agreement"]["buyer"].get("contact", {}) or {}
    ).get("email")


@functools.cache
def notify_unhandled_exception_in_teams(process, order_id, traceback):
    send_exception(
        f"Order {process} unhandled exception!",
        f"An unhandled exception has been raised while performing {process} "
        f"of the order **{order_id}**:\n\n"
        f"```{traceback}```",
    )


@functools.cache
def notify_agreement_unhandled_exception_in_teams(agreement_id, traceback):
    """
    Notify that an agreement has been unhandled exception
    """
    send_exception(
        "Agreement unhandled exception!",
        f"An unhandled exception has been raised of the agreement **{agreement_id}**:\n\n"
        f"```{traceback}```",
    )


def notify_missing_prices(agreement_id, missing_skus, product_id, currency, commitment_date=None):
    """
    Notifies about SKUs with missing prices in the agreement.
    Args:
        agreement_id (str): The agreement ID
        missing_skus (list): List of SKUs without prices
        product_id (str): The product ID
        currency (str): The currency code
        commitment_date (str, optional): The 3YC commitment date if applicable
    """
    context = (
        f"3YC prices (commitment date: {commitment_date})" if commitment_date else "regular prices"
    )

    message = (
        f"Missing prices detected in agreement **{agreement_id}**\n\n"
        f"The following SKUs don't have {context} available:\n"
        f"- Product ID: {product_id}\n"
        f"- Currency: {currency}\n"
        f"- SKUs:\n"
    )

    for sku in missing_skus:
        message += f"  - {sku}\n"

    send_exception("Missing prices detected", message)


def notify_not_updated_subscriptions(order_id, error_message, updated_subscriptions, product_id):
    """
    Notifies about SKUs with missing prices in the agreement.
    Args:
        agreement_id (str): The agreement ID
        missing_skus (list): List of SKUs without prices
        product_id (str): The product ID
        currency (str): The currency code
        commitment_date (str, optional): The 3YC commitment date if applicable
    """
    message = (
        f"{error_message}\n\n"
        f"The order **{order_id}**\n\n"
        f"has failed changing the auto-renewal status\n\n "
        f"- Product ID: {product_id}\n\n"
    )

    if updated_subscriptions:
        message += "The following subscriptions has been updated and rolled back:\n"
        message += "".join(
            f"  - {sub['subscription_vendor_id']}\n" for sub in updated_subscriptions
        )

    send_exception(f"Error updating the subscriptions in configuration order: {order_id}", message)
