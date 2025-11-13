import pytest

from adobe_vipm.adobe.mixins.subscription import SubscriptionClientMixin


@pytest.fixture()
def subscription_mixin_client(mocker, adobe_subscription_factory):
    client = SubscriptionClientMixin()
    items = [
        adobe_subscription_factory(deployment_id=""),
        adobe_subscription_factory(deployment_id="fake_1"),
    ]
    mocker.patch.object(
        client,
        "get_subscriptions",
        return_value={"items": items, "links": {}, "totalCount": len(items)},
    )

    return client


def test_get_subscriptions_by_deployment(subscription_mixin_client):
    result = subscription_mixin_client.get_subscriptions_by_deployment(
        authorization_id="fake_auth", customer_id="fake_customer", deployment_id="fake_1"
    )

    items = result["items"]
    assert len(items) == 1
    assert items[0]["deploymentId"] == "fake_1"


def get_subscriptions_by_deployment_missing_deployment_id(subscription_mixin_client):
    result = subscription_mixin_client.get_subscriptions_by_deployment(
        authorization_id="fake_auth",
        customer_id="fake_customer",
        deployment_id="missing_deployment_id",
    )

    assert len(result["items"]) == 0
