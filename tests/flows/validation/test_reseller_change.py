import datetime as dt

import pytest

from adobe_vipm.adobe.errors import AdobeAPIError
from adobe_vipm.flows.constants import (
    ERR_ADOBE_RESSELLER_CHANGE_PREVIEW,
    Param,
)
from adobe_vipm.flows.utils import get_ordering_parameter
from adobe_vipm.flows.validation.transfer import validate_reseller_change

pytestmark = pytest.mark.usefixtures("mock_adobe_config")


def test_validate_reseller_change_success(
    mocker,
    mock_mpt_client,
    mock_adobe_client,
    order_factory,
    reseller_change_order_parameters_factory,
    adobe_reseller_change_preview_factory,
    adobe_customer_factory,
    adobe_items_factory,
    items_factory,
    lines_factory,
):
    today = dt.datetime.now(tz=dt.UTC).date()
    order = order_factory(order_parameters=reseller_change_order_parameters_factory())
    adobe_items = adobe_items_factory(
        renewal_date=(today + dt.timedelta(days=1)).isoformat(), subscription_id="1234567890"
    )
    adobe_preview = adobe_reseller_change_preview_factory(items=adobe_items)
    product_items = items_factory()
    mock_adobe_client.reseller_change_request.return_value = adobe_preview
    mocker.patch(
        "adobe_vipm.flows.validation.transfer.get_product_items_by_skus", return_value=product_items
    )
    mocker.patch("adobe_vipm.flows.helpers.get_adobe_client", return_value=mock_adobe_client)

    has_errors, validated_order = validate_reseller_change(mock_mpt_client, order)

    assert has_errors is False
    assert isinstance(validated_order["lines"], list)


def test_validate_reseller_change_success_adding_line(
    mocker,
    mock_mpt_client,
    mock_adobe_client,
    order_factory,
    reseller_change_order_parameters_factory,
    adobe_reseller_change_preview_factory,
    adobe_customer_factory,
    adobe_items_factory,
    items_factory,
    lines_factory,
):
    today = dt.datetime.now(tz=dt.UTC).date()
    order = order_factory(order_parameters=reseller_change_order_parameters_factory())
    order["lines"] = []
    adobe_items = adobe_items_factory(
        renewal_date=(today + dt.timedelta(days=1)).isoformat(), subscription_id="1234567890"
    )
    adobe_preview = adobe_reseller_change_preview_factory(items=adobe_items)
    product_items = items_factory()
    mock_adobe_client.reseller_change_request.return_value = adobe_preview
    mocker.patch(
        "adobe_vipm.flows.validation.transfer.get_product_items_by_skus", return_value=product_items
    )
    mocker.patch("adobe_vipm.flows.helpers.get_adobe_client", return_value=mock_adobe_client)

    has_errors, validated_order = validate_reseller_change(mock_mpt_client, order)

    order_line = [
        {
            "item": {
                "id": "ITM-1234-1234-1234-0001",
                "name": "Awesome product",
                "externalIds": {"vendor": "65304578CA"},
                "terms": {"model": "quantity", "period": "1y"},
            },
            "quantity": 1,
            "oldQuantity": 0,
            "price": {"unitPP": 0},
        }
    ]
    assert has_errors is False
    assert validated_order["lines"] == order_line
    assert isinstance(validated_order["lines"], list)


def test_validate_reseller_change_success_adding_additional_licenses(
    mocker,
    mock_mpt_client,
    mock_adobe_client,
    order_factory,
    reseller_change_order_parameters_factory,
    adobe_reseller_change_preview_factory,
    adobe_customer_factory,
    adobe_items_factory,
    items_factory,
    lines_factory,
):
    today = dt.datetime.now(tz=dt.UTC).date()
    order = order_factory(order_parameters=reseller_change_order_parameters_factory())
    order["lines"] = [
        {
            "item": {
                "id": "ITM-1234-1234-1234-0002",
                "name": "Awesome product",
                "externalIds": {"vendor": "65304578CA"},
                "terms": {"period": "1y"},
            },
            "quantity": 1,
            "oldQuantity": 0,
            "price": {"unitPP": 0},
        }
    ]
    adobe_items = adobe_items_factory(
        renewal_date=(today + dt.timedelta(days=1)).isoformat(), subscription_id="1234567890"
    )
    adobe_preview = adobe_reseller_change_preview_factory(items=adobe_items)
    mock_adobe_client.reseller_change_request.return_value = adobe_preview
    product_items = items_factory()
    mocker.patch(
        "adobe_vipm.flows.validation.transfer.get_product_items_by_skus",
        return_value=product_items,
    )
    mocker.patch("adobe_vipm.flows.helpers.get_adobe_client", return_value=mock_adobe_client)

    has_errors, validated_order = validate_reseller_change(mock_mpt_client, order)

    order_line = [
        {
            "item": {
                "id": "ITM-1234-1234-1234-0001",
                "name": "Awesome product",
                "externalIds": {"vendor": "65304578CA"},
                "terms": {"model": "quantity", "period": "1y"},
            },
            "quantity": 1,
            "oldQuantity": 0,
            "price": {"unitPP": 0},
        }
    ]
    assert has_errors is True
    assert validated_order["lines"] == order_line
    assert isinstance(validated_order["lines"], list)


def test_validate_reseller_change_expired_code(
    mocker,
    mock_mpt_client,
    mock_adobe_client,
    order_factory,
    reseller_change_order_parameters_factory,
    adobe_reseller_change_preview_factory,
    adobe_customer_factory,
    adobe_items_factory,
):
    today = dt.datetime.now(tz=dt.UTC).date()
    order = order_factory(order_parameters=reseller_change_order_parameters_factory())
    adobe_items = adobe_items_factory(
        renewal_date=(today + dt.timedelta(days=1)).isoformat(), subscription_id="1234567890"
    )
    adobe_preview = adobe_reseller_change_preview_factory(
        items=adobe_items, approval_expiry=(today - dt.timedelta(days=1)).isoformat()
    )
    mock_adobe_client.reseller_change_request.return_value = adobe_preview

    mocker.patch("adobe_vipm.flows.helpers.get_adobe_client", return_value=mock_adobe_client)

    has_errors, validated_order = validate_reseller_change(mock_mpt_client, order)

    assert has_errors is True
    param = get_ordering_parameter(validated_order, Param.CHANGE_RESELLER_CODE.value)
    assert param["error"]["id"] == ERR_ADOBE_RESSELLER_CHANGE_PREVIEW.id
    assert "expired" in param["error"]["message"]
    assert param["constraints"]["hidden"] is False
    assert param["constraints"]["required"] is True


def test_validate_reseller_change_adobe_api_error(
    mocker,
    mock_adobe_client,
    mock_mpt_client,
    order_factory,
    reseller_change_order_parameters_factory,
):
    order = order_factory(order_parameters=reseller_change_order_parameters_factory())
    api_error = AdobeAPIError(400, {"code": "9999", "message": "Adobe error"})
    mock_adobe_client.reseller_change_request.side_effect = api_error

    has_errors, validated_order = validate_reseller_change(mock_mpt_client, order)

    assert has_errors is True
    param = get_ordering_parameter(validated_order, Param.CHANGE_RESELLER_CODE.value)
    assert param["error"] == ERR_ADOBE_RESSELLER_CHANGE_PREVIEW.to_dict(
        reseller_change_code=param["value"], error=str(api_error)
    )
    assert param["constraints"]["hidden"] is False
    assert param["constraints"]["required"] is True


def test_validate_reseller_change_no_subscriptions(
    mocker,
    mock_adobe_client,
    mock_mpt_client,
    order_factory,
    reseller_change_order_parameters_factory,
    adobe_reseller_change_preview_factory,
    adobe_customer_factory,
    items_factory,
):
    today = dt.datetime.now(tz=dt.UTC).date()
    order = order_factory(order_parameters=reseller_change_order_parameters_factory())
    adobe_preview = adobe_reseller_change_preview_factory(
        items=[], approval_expiry=(today + dt.timedelta(days=5)).isoformat()
    )
    mock_adobe_client.reseller_change_request.return_value = adobe_preview
    mock_adobe_client.get_customer.return_value = adobe_customer_factory()
    mock_adobe_client.get_subscriptions.return_value = {"items": []}
    product_items = items_factory()
    mocker.patch(
        "adobe_vipm.flows.validation.transfer.get_product_items_by_skus",
        return_value=product_items,
    )

    has_errors, validated_order = validate_reseller_change(mock_mpt_client, order)

    assert has_errors is False
    assert isinstance(validated_order["lines"], list)


def test_validate_reseller_change_missing_admin_email(
    mock_adobe_client,
    mock_mpt_client,
    order_factory,
    reseller_change_order_parameters_factory,
    adobe_reseller_change_preview_factory,
    adobe_customer_factory,
    adobe_items_factory,
):
    today = dt.datetime.now(tz=dt.UTC).date()
    params = reseller_change_order_parameters_factory(admin_email=None)
    adobe_items = adobe_items_factory(
        renewal_date=(today + dt.timedelta(days=1)).isoformat(), subscription_id="1234567890"
    )
    order = order_factory(order_parameters=params)
    adobe_preview = adobe_reseller_change_preview_factory(
        items=adobe_items, approval_expiry=(today - dt.timedelta(days=1)).isoformat()
    )
    mock_adobe_client.reseller_change_request.return_value = adobe_preview
    mock_adobe_client.get_customer.return_value = adobe_customer_factory()
    mock_adobe_client.get_subscriptions.return_value = {"items": adobe_items_factory()}

    has_errors, validated_order = validate_reseller_change(mock_mpt_client, order)

    assert isinstance(has_errors, bool)
    assert isinstance(validated_order, dict)
