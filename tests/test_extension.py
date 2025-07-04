import json

from mpt_extension_sdk.core.events.dataclasses import Event
from mpt_extension_sdk.runtime.djapp.conf import get_for_product

from adobe_vipm.extension import ext, jwt_secret_callback, process_order_fulfillment
from adobe_vipm.flows.constants import PARAM_COMPANY_NAME
from adobe_vipm.flows.utils import set_ordering_parameter_error


def test_listener_registered():
    assert ext.events.get_listener("orders") == process_order_fulfillment


def test_process_order_fulfillment(mocker):
    mocked_fulfill_order = mocker.patch(
        "adobe_vipm.extension.fulfill_order",
    )

    client = mocker.MagicMock()
    event = Event("evt-id", "orders", {"id": "ORD-0792-5000-2253-4210"})

    process_order_fulfillment(client, event)

    mocked_fulfill_order.assert_called_once_with(client, event.data)


def test_jwt_secret_callback(mocker, settings, mpt_client, webhook):
    mocked_webhook = mocker.patch(
        "adobe_vipm.extension.get_webhook",
        return_value=webhook,
    )
    assert jwt_secret_callback(mpt_client, {"webhook_id": "WH-123-123"}) == get_for_product(
        settings, "WEBHOOKS_SECRETS", "PRD-1111-1111"
    )
    mocked_webhook.assert_called_once_with(mpt_client, "WH-123-123")


def test_process_order_validation(client, mocker, order_factory, jwt_token, webhook):
    mocker.patch(
        "adobe_vipm.extension.get_webhook",
        return_value=webhook,
    )
    validated_order = set_ordering_parameter_error(
        order_factory(),
        PARAM_COMPANY_NAME,
        {"id": "my_err_id", "message": "my_msg"},
    )
    order = order_factory()
    m_validate = mocker.patch("adobe_vipm.extension.validate_order", return_value=validated_order)
    resp = client.post(
        "/api/v1/orders/validate",
        content_type="application/json",
        headers={
            "Authorization": f"Bearer {jwt_token}",
            "X-Forwarded-Host": "adobe.ext.s1.com",
        },
        data=json.dumps(order),
    )
    assert resp.status_code == 200
    assert resp.json() == validated_order
    m_validate.assert_called_once_with(mocker.ANY, order)


def test_process_order_validation_error(client, mocker, jwt_token, webhook):
    mocker.patch(
        "adobe_vipm.extension.get_webhook",
        return_value=webhook,
    )
    mocker.patch(
        "adobe_vipm.extension.validate_order",
        side_effect=Exception("A super duper error"),
    )
    resp = client.post(
        "/api/v1/orders/validate",
        content_type="application/json",
        headers={
            "Authorization": f"Bearer {jwt_token}",
            "X-Forwarded-Host": "adobe.ext.s1.com",
        },
        data={"whatever": "order"},
    )
    assert resp.status_code == 400
    assert resp.json() == {
        "id": "VIPMG001",
        "message": "Unexpected error during validation: A super duper error.",
    }
