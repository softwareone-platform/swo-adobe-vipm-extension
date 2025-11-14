def check_adobe_subscription_id(subscription_id: str, adobe_subscription: dict) -> bool:
    """Compares the subscription ID with the subscription ID from the Adobe subscription data."""
    return adobe_subscription.get("subscriptionId", "") == subscription_id
