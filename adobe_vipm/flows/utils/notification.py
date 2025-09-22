import functools

from adobe_vipm.notifications import send_exception


@functools.cache
def notify_unhandled_exception_in_teams(process: str, order_id: str, traceback: str) -> None:
    """
    Notify unhandled exception when processing the order to teams channel.

    Args:
        process: Name of the process or action.
        order_id: MPT order id.
        traceback: Traceback to report in the notification.
    """
    send_exception(
        f"Order {process} unhandled exception!",
        f"An unhandled exception has been raised while performing {process} "
        f"of the order **{order_id}**:\n\n"
        f"```{traceback}```",
    )


@functools.cache
def notify_agreement_unhandled_exception_in_teams(agreement_id: str, traceback: str) -> None:
    """
    Notify that an agreement has raised unhandled exception.

    Args:
        agreement_id: MPT agreement id.
        traceback: Traceback to report in the notification.
    """
    send_exception(
        "Agreement unhandled exception!",
        f"An unhandled exception has been raised of the agreement **{agreement_id}**:\n\n"
        f"```{traceback}```",
    )


def notify_missing_prices(
    agreement_id: str,
    missing_skus: list[str],
    product_id: str,
    currency: str,
    commitment_date: str | None = None,
) -> None:
    """
    Notifies about SKUs with missing prices in the agreement.

    Args:
        agreement_id: The agreement ID
        missing_skus: List of SKUs without prices
        product_id: The product ID
        currency: The currency code
        commitment_date: The 3YC commitment date if applicable
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


def notify_not_updated_subscriptions(
    order_id: str, error_message: str, updated_subscriptions: list[dict], product_id: str
) -> None:
    """
    Notifies about SKUs with missing prices in the agreement.

    Args:
        order_id: MPT order id.
        error_message: Error message to include into the notification
        updated_subscriptions: MPT subscriptions that were updated
        product_id (str): The product ID
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
