# noqa: WPS100


def _check_adobe_subscription_id(subscription_id, adobe_subscription):
    return adobe_subscription.get("subscriptionId", "") == subscription_id
