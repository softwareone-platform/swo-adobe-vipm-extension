import datetime as dt
from copy import deepcopy

import pytest

from adobe_vipm.adobe.constants import ORDER_TYPE_PREVIEW
from adobe_vipm.adobe.errors import AdobeAPIError
from adobe_vipm.flows.constants import Param
from adobe_vipm.flows.errors import MPTError
from adobe_vipm.flows.utils import get_ordering_parameter
from adobe_vipm.flows.validation.transfer import validate_reseller_change

pytestmark = pytest.mark.usefixtures("mock_adobe_config")


@pytest.mark.usefixtures("mock_get_product_items_by_skus", "mock_get_agreement")
def test_validate_reseller_change_success(
    mock_mpt_client,
    mock_adobe_client,
    order_factory,
    reseller_change_order_parameters_factory,
    adobe_reseller_change_preview_factory,
    lines_factory,
    adobe_order_factory,
    mock_update_order,
    mock_get_preview_order,
):
    """Test successful reseller change validation with transfer items."""
    mock_adobe_client.create_preview_order.return_value = adobe_order_factory(
        ORDER_TYPE_PREVIEW, deployment_id=""
    )
    mock_adobe_client.reseller_change_request.return_value = adobe_reseller_change_preview_factory()
    mock_update_order.return_value = order_factory(
        order_parameters=reseller_change_order_parameters_factory(),
        lines=lines_factory(old_quantity=170),
    )
    order = order_factory(lines=[], order_parameters=reseller_change_order_parameters_factory())

    has_errors, validated_order = validate_reseller_change(mock_mpt_client, order)  # act

    assert has_errors is False
    assert validated_order["lines"] == [
        {
            "id": "ALI-2119-4550-8674-5962-0001",
            "item": {
                "externalIds": {"vendor": "65304578CA"},
                "id": "ITM-1234-1234-1234-0001",
                "name": "Awesome product",
            },
            "oldQuantity": 170,
            "price": {"unitPP": 1234.55},
            "quantity": 170,
            "subscription": {
                "id": "SUB-1000-2000-3000",
                "name": "Subscription for Acrobat Pro for Teams; Multi Language",
                "status": "Active",
            },
        }
    ]
    mock_get_preview_order.return_value.assert_called_once()


@pytest.mark.usefixtures("mock_get_product_items_by_skus", "mock_get_agreement")
def test_validate_reseller_change_success_reviving(
    mock_mpt_client,
    mock_adobe_client,
    order_factory,
    reseller_change_order_parameters_factory,
    adobe_reseller_change_preview_factory,
    lines_factory,
    mock_update_order,
    adobe_order_factory,
    mock_get_preview_order,
):
    """Test successful reseller change validation when reviving a reseller."""
    order = order_factory(order_parameters=reseller_change_order_parameters_factory())
    order["lines"] = [
        {
            "id": "ALI-2119-4550-8674-5962-0001",
            "item": {
                "externalIds": {"vendor": "65304578CA"},
                "id": "ITM-1234-1234-1234-0001",
                "name": "Awesome product",
            },
            "oldQuantity": 0,
            "price": {"unitPP": 0.55},
            "quantity": 170,
            "subscription": {
                "id": "SUB-1000-2000-3000",
                "name": "Subscription for Acrobat Pro for Teams; Multi Language",
                "status": "Active",
            },
        }
    ]
    mock_adobe_client.create_preview_order.return_value = adobe_order_factory(
        ORDER_TYPE_PREVIEW, deployment_id=""
    )
    mock_adobe_client.reseller_change_request.return_value = adobe_reseller_change_preview_factory(
        items=[]
    )
    mock_update_order.return_value = order_factory(
        order_parameters=reseller_change_order_parameters_factory(),
        lines=lines_factory(old_quantity=170),
    )

    has_errors, validated_order = validate_reseller_change(mock_mpt_client, order)  # act

    assert has_errors is False
    assert validated_order["lines"] == order["lines"]
    mock_get_preview_order.return_value.assert_called_once()


@pytest.mark.usefixtures("mock_get_product_items_by_skus", "mock_get_agreement")
def test_validate_reseller_change_expired_code(
    mock_mpt_client,
    mock_adobe_client,
    order_factory,
    reseller_change_order_parameters_factory,
    adobe_reseller_change_preview_factory,
    mock_add_reseller_change_lines_to_order,
):
    """Test validation fails when reseller change code has expired."""
    today = dt.datetime.now(tz=dt.UTC).date()
    adobe_preview = adobe_reseller_change_preview_factory(
        approval_expiry=(today - dt.timedelta(days=1)).isoformat(),
    )
    mock_adobe_client.reseller_change_request.return_value = adobe_preview
    order = order_factory(order_parameters=reseller_change_order_parameters_factory())

    has_errors, validated_order = validate_reseller_change(mock_mpt_client, order)  # act

    assert has_errors is True
    param = get_ordering_parameter(validated_order, Param.CHANGE_RESELLER_CODE.value)
    assert param == {
        "constraints": {"hidden": False, "required": True},
        "error": {
            "id": "VIPM0036",
            "message": "Error processing the reseller change code 88888888: "
            "Reseller change code has expired",
        },
        "externalId": "changeResellerCode",
        "id": "PAR-0000-0005",
        "name": "Change of reseller code",
        "type": "SingleLineText",
        "value": "88888888",
    }
    mock_add_reseller_change_lines_to_order.return_value.assert_not_called()


@pytest.mark.usefixtures("mock_get_product_items_by_skus", "mock_get_agreement")
def test_validate_reseller_change_adobe_api_error(
    mock_adobe_client,
    mock_mpt_client,
    order_factory,
    reseller_change_order_parameters_factory,
    mock_validate_reseller_change,
):
    """Test validation fails when Adobe API returns an error."""
    mock_adobe_client.reseller_change_request.side_effect = AdobeAPIError(
        400, {"code": "9999", "message": "Adobe error"}
    )
    order = order_factory(order_parameters=reseller_change_order_parameters_factory())

    has_errors, validated_order = validate_reseller_change(mock_mpt_client, order)  # act

    assert has_errors is True
    param = get_ordering_parameter(validated_order, Param.CHANGE_RESELLER_CODE.value)
    assert param == {
        "constraints": {"hidden": False, "required": True},
        "error": {
            "id": "VIPM0036",
            "message": "Error processing the reseller change code 88888888: 9999 - Adobe error",
        },
        "externalId": "changeResellerCode",
        "id": "PAR-0000-0005",
        "name": "Change of reseller code",
        "type": "SingleLineText",
        "value": "88888888",
    }
    mock_validate_reseller_change.return_value.assert_not_called()


@pytest.mark.usefixtures("mock_get_product_items_by_skus", "mock_get_agreement")
def test_validate_reseller_change_no_subscriptions(
    mock_adobe_client,
    mock_mpt_client,
    order_factory,
    reseller_change_order_parameters_factory,
    adobe_reseller_change_preview_factory,
    adobe_customer_factory,
    mock_get_preview_order,
):
    """Test validation succeeds when customer has no subscriptions."""
    mock_adobe_client.reseller_change_request.return_value = adobe_reseller_change_preview_factory(
        items=[]
    )
    mock_adobe_client.get_customer.return_value = adobe_customer_factory()
    mock_adobe_client.get_subscriptions.return_value = {"items": []}
    order = order_factory(order_parameters=reseller_change_order_parameters_factory())

    has_errors, _ = validate_reseller_change(mock_mpt_client, order)  # act

    assert has_errors is False
    mock_get_preview_order.return_value.assert_called_once()


@pytest.mark.usefixtures("mock_get_product_items_by_skus", "mock_get_agreement")
def test_validate_reseller_change_lines_mismatch(
    mock_mpt_client,
    mock_adobe_client,
    order_factory,
    reseller_change_order_parameters_factory,
    adobe_reseller_change_preview_factory,
    adobe_transfer_items_factory,
    adobe_customer_factory,
    lines_factory,
    adobe_order_factory,
    mock_update_order,
    mock_get_preview_order,
):
    """Test validation fails when order lines don't match transfer lines."""
    mock_adobe_client.create_preview_order.return_value = adobe_order_factory(
        ORDER_TYPE_PREVIEW, deployment_id=""
    )
    mock_adobe_client.reseller_change_request.return_value = adobe_reseller_change_preview_factory(
        items=adobe_transfer_items_factory(deployment_id="", quantity=170)
    )
    mock_adobe_client.get_customer.return_value = adobe_customer_factory()
    mock_update_order.return_value = order_factory(
        order_parameters=reseller_change_order_parameters_factory(), lines=lines_factory()
    )
    order = order_factory(order_parameters=reseller_change_order_parameters_factory())
    order["lines"] = [
        {
            "id": "ALI-2119-4550-8674-5962-0001",
            "item": {
                "externalIds": {"vendor": "65304578CA"},
                "id": "ITM-1234-1234-1234-0001",
                "name": "Awesome product",
            },
            "oldQuantity": 100,
            "price": {"unitPP": 0.55},
            "quantity": 150,
        }
    ]

    has_errors, validated_order = validate_reseller_change(mock_mpt_client, order)  # act

    assert has_errors is True
    assert validated_order["lines"] == [
        {
            "id": "ALI-2119-4550-8674-5962-0001",
            "item": {
                "externalIds": {"vendor": "65304578CA"},
                "id": "ITM-1234-1234-1234-0001",
                "name": "Awesome product",
            },
            "oldQuantity": 100,
            "price": {"unitPP": 0.55},
            "quantity": 150,
        }
    ]
    mock_get_preview_order.return_value.assert_not_called()


@pytest.mark.usefixtures("mock_get_product_items_by_skus", "mock_get_agreement")
def test_validate_reseller_change_no_lines_and_empty_transfer(
    mock_mpt_client,
    mock_adobe_client,
    order_factory,
    reseller_change_order_parameters_factory,
    adobe_reseller_change_preview_factory,
    mock_get_preview_order,
    mock_update_order,
):
    """Test validation fails when both order and transfer have no lines."""
    mock_adobe_client.reseller_change_request.return_value = adobe_reseller_change_preview_factory(
        items=[]
    )
    order = order_factory(lines=[], order_parameters=reseller_change_order_parameters_factory())
    mock_update_order.return_value = order

    has_errors, _ = validate_reseller_change(mock_mpt_client, order)  # act

    assert has_errors is True
    mock_get_preview_order.return_value.assert_not_called()


@pytest.mark.usefixtures("mock_get_product_items_by_skus", "mock_get_agreement")
def test_validate_reseller_change_filters_items_with_deployment(
    mocker,
    mock_mpt_client,
    mock_adobe_client,
    order_factory,
    reseller_change_order_parameters_factory,
    adobe_reseller_change_preview_factory,
    adobe_transfer_items_factory,
    items_factory,
    adobe_order_factory,
    mock_update_order,
    mock_get_product_items_by_skus,
    mock_get_preview_order,
):
    """Test that items with deploymentId are filtered out."""
    adobe_items_no_deployment = adobe_transfer_items_factory(line_number=1, deployment_id="")
    adobe_items_with_deployment = adobe_transfer_items_factory(
        line_number=2, offer_id="65304578CA02B12", deployment_id="deploy-123"
    )
    mock_adobe_client.reseller_change_request.return_value = adobe_reseller_change_preview_factory(
        items=adobe_items_no_deployment + adobe_items_with_deployment
    )
    mock_adobe_client.create_preview_order.return_value = adobe_order_factory(
        ORDER_TYPE_PREVIEW, deployment_id=""
    )
    mock_get_product_items_by_skus.return_value = items_factory()
    mock_update_order.return_value = order_factory(
        order_parameters=reseller_change_order_parameters_factory()
    )
    order = order_factory(lines=[], order_parameters=reseller_change_order_parameters_factory())

    has_errors, validated_order = validate_reseller_change(mock_mpt_client, order)  # act

    assert has_errors is False
    assert len(validated_order["lines"]) == 1
    assert mock_update_order.mock_calls == [
        mocker.call(
            mock_mpt_client,
            "ORD-0792-5000-2253-4210",
            lines=[
                {
                    "item": {
                        "id": "ITM-1234-1234-1234-0001",
                        "name": "Awesome product",
                        "externalIds": {"vendor": "65304578CA"},
                        "terms": {"period": "1y", "model": "quantity"},
                        "status": "Published",
                    },
                    "quantity": 170,
                }
            ],
        )
    ]
    mock_get_preview_order.return_value.assert_called_once()


@pytest.mark.usefixtures("mock_get_product_items_by_skus", "mock_get_agreement")
def test_validate_reseller_change_multiple_lines_match(
    mock_mpt_client,
    mock_adobe_client,
    order_factory,
    reseller_change_order_parameters_factory,
    adobe_reseller_change_preview_factory,
    adobe_customer_factory,
    adobe_order_factory,
    mock_update_order,
    mock_get_product_items_by_skus,
    mock_get_preview_order,
):
    """Test validation succeeds with multiple matching lines."""
    adobe_items = [
        {
            "lineItemNumber": 1,
            "offerId": "65304578CA01A12",
            "quantity": 170,
            "subscriptionId": "sub-1",
            "deploymentId": "",
            "currencyCode": "USD",
        },
        {
            "lineItemNumber": 2,
            "offerId": "65304579CA01A12",
            "quantity": 50,
            "subscriptionId": "sub-2",
            "deploymentId": "",
            "currencyCode": "USD",
        },
    ]
    mock_adobe_client.reseller_change_request.return_value = adobe_reseller_change_preview_factory(
        items=adobe_items
    )
    mock_adobe_client.create_preview_order.return_value = adobe_order_factory(
        ORDER_TYPE_PREVIEW, deployment_id=""
    )
    mock_adobe_client.get_customer.return_value = adobe_customer_factory()
    mock_get_product_items_by_skus.return_value = [
        {
            "externalIds": {"vendor": "65304578CA"},
            "id": "ITM-001",
            "name": "Product 1",
        },
        {
            "externalIds": {"vendor": "65304579CA"},
            "id": "ITM-002",
            "name": "Product 2",
        },
    ]
    order = order_factory(order_parameters=reseller_change_order_parameters_factory())
    order["lines"] = [
        {
            "id": "ALI-001",
            "item": {
                "externalIds": {"vendor": "65304578CA"},
                "id": "ITM-001",
                "name": "Product 1",
            },
            "oldQuantity": 170,
            "quantity": 170,
            "price": {"unitPP": 10.0},
        },
        {
            "id": "ALI-002",
            "item": {
                "externalIds": {"vendor": "65304579CA"},
                "id": "ITM-002",
                "name": "Product 2",
            },
            "oldQuantity": 50,
            "quantity": 50,
            "price": {"unitPP": 20.0},
        },
    ]
    mock_update_order.return_value = order

    has_errors, validated_order = validate_reseller_change(mock_mpt_client, order)  # act

    assert has_errors is False
    assert len(validated_order["lines"]) == 2
    mock_get_preview_order.return_value.assert_called_once()


@pytest.mark.usefixtures("mock_get_product_items_by_skus", "mock_get_agreement")
def test_validate_reseller_change_lines_different_vendor_id(
    mock_mpt_client,
    mock_adobe_client,
    order_factory,
    reseller_change_order_parameters_factory,
    adobe_reseller_change_preview_factory,
    adobe_transfer_items_factory,
    adobe_customer_factory,
    adobe_order_factory,
    mock_update_order,
    mock_get_preview_order,
):
    """Test validation fails when order line has different vendor ID than transfer."""
    order = order_factory(order_parameters=reseller_change_order_parameters_factory())
    order["lines"] = [
        {
            "id": "ALI-2119-4550-8674-5962-0001",
            "item": {
                "externalIds": {"vendor": "65304579CA"},
                "id": "ITM-1234-1234-1234-0002",
                "name": "Different product",
            },
            "oldQuantity": 170,
            "price": {"unitPP": 0.55},
            "quantity": 170,
        }
    ]
    updated_order = deepcopy(order)
    updated_order["lines"][0]["item"]["externalIds"]["vendor"] = "65304578CA"
    mock_update_order.return_value = updated_order
    mock_adobe_client.create_preview_order.return_value = adobe_order_factory(
        ORDER_TYPE_PREVIEW, deployment_id=""
    )
    mock_adobe_client.reseller_change_request.return_value = adobe_reseller_change_preview_factory(
        items=adobe_transfer_items_factory(
            subscription_id="1234567890",
            deployment_id="",
            quantity=170,
            offer_id="65304578CA01A12",
        )
    )
    mock_adobe_client.get_customer.return_value = adobe_customer_factory()

    has_errors, validated_order = validate_reseller_change(mock_mpt_client, order)  # act

    assert has_errors is True
    assert len(validated_order["lines"]) == 1
    mock_get_preview_order.return_value.assert_not_called()


@pytest.mark.usefixtures("mock_get_product_items_by_skus", "mock_get_agreement")
def test_validate_reseller_change_lines_different_line_count(
    mock_mpt_client,
    mock_adobe_client,
    order_factory,
    reseller_change_order_parameters_factory,
    adobe_reseller_change_preview_factory,
    adobe_transfer_items_factory,
    adobe_customer_factory,
    items_factory,
    adobe_order_factory,
    mock_get_product_items_by_skus,
    mock_get_preview_order,
):
    """Test validation fails when order has different number of lines than transfer."""
    mock_adobe_client.create_preview_order.return_value = adobe_order_factory(
        ORDER_TYPE_PREVIEW, deployment_id=""
    )
    mock_adobe_client.reseller_change_request.return_value = adobe_reseller_change_preview_factory(
        items=adobe_transfer_items_factory(deployment_id="", quantity=170)
    )
    mock_adobe_client.get_customer.return_value = adobe_customer_factory()
    mock_get_product_items_by_skus.return_value = items_factory()
    order = order_factory(order_parameters=reseller_change_order_parameters_factory())
    order["lines"] = [
        {
            "id": "ALI-001",
            "item": {
                "externalIds": {"vendor": "65304578CA"},
                "id": "ITM-001",
                "name": "Product 1",
            },
            "oldQuantity": 170,
            "quantity": 170,
            "price": {"unitPP": 10.0},
        },
        {
            "id": "ALI-002",
            "item": {
                "externalIds": {"vendor": "65304579CA"},
                "id": "ITM-002",
                "name": "Product 2",
            },
            "oldQuantity": 50,
            "quantity": 50,
            "price": {"unitPP": 20.0},
        },
    ]

    has_errors, _ = validate_reseller_change(mock_mpt_client, order)  # act

    assert has_errors is True
    mock_get_preview_order.return_value.assert_not_called()


@pytest.mark.usefixtures("mock_get_product_items_by_skus", "mock_get_agreement")
def test_validate_reseller_change_missing_reseller_item_raises_error(
    mock_adobe_client,
    mock_mpt_client,
    order_factory,
    reseller_change_order_parameters_factory,
    adobe_reseller_change_preview_factory,
    mock_get_product_items_by_skus,
    mock_send_error,
):
    """Test that missing reseller item raises MPTError during validation."""
    order = order_factory(
        order_parameters=reseller_change_order_parameters_factory(),
        lines=[],
    )
    mock_adobe_client.reseller_change_request.return_value = adobe_reseller_change_preview_factory(
        items=[
            {
                "lineItemNumber": 1,
                "offerId": "65304578CA01A12",
                "quantity": 10,
                "subscriptionId": "sub-id-1",
                "deploymentId": "",
                "currencyCode": "USD",
            }
        ]
    )
    mock_get_product_items_by_skus.return_value = []

    with pytest.raises(MPTError) as exc_info:
        validate_reseller_change(mock_mpt_client, order)  # Act

    assert "No reseller item found for partial SKU '65304578CA'" in str(exc_info.value)
    mock_send_error.assert_called_once_with(
        "Transfer Validation - Missing reseller item",
        "No reseller item found for partial SKU '65304578CA'",
    )
