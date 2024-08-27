from datetime import date, timedelta

import pytest

from adobe_vipm.adobe.constants import (
    STATUS_3YC_ACTIVE,
    STATUS_3YC_COMMITTED,
    STATUS_TRANSFER_INACTIVE_ACCOUNT,
    STATUS_TRANSFER_INVALID_MEMBERSHIP,
    STATUS_TRANSFER_INVALID_MEMBERSHIP_OR_TRANSFER_IDS,
    UNRECOVERABLE_TRANSFER_STATUSES,
)
from adobe_vipm.adobe.errors import AdobeAPIError, AdobeHttpError
from adobe_vipm.flows.constants import (
    ERR_ADOBE_MEMBERSHIP_ID,
    ERR_ADOBE_MEMBERSHIP_ID_EMPTY,
    ERR_ADOBE_MEMBERSHIP_ID_INACTIVE_ACCOUNT,
    ERR_ADOBE_MEMBERSHIP_ID_ITEM,
    ERR_ADOBE_MEMBERSHIP_NOT_FOUND,
    ERR_ADOBE_UNEXPECTED_ERROR,
    PARAM_MEMBERSHIP_ID,
)
from adobe_vipm.flows.utils import get_ordering_parameter
from adobe_vipm.flows.validation.transfer import get_prices, validate_transfer

pytestmark = pytest.mark.usefixtures("mock_adobe_config")


def test_validate_transfer(
    mocker,
    order_factory,
    items_factory,
    transfer_order_parameters_factory,
    adobe_preview_transfer_factory,
    adobe_items_factory,
    lines_factory,
):
    mocker.patch(
        "adobe_vipm.flows.validation.transfer.get_transfer_by_authorization_membership_or_customer",
        return_value=None,
    )
    m_client = mocker.MagicMock()
    order = order_factory(
        order_parameters=transfer_order_parameters_factory(),
        lines=[],
    )
    product_items = items_factory()
    valid_items = adobe_items_factory(
        renewal_date=date.today().isoformat(),
    )
    expired_items = adobe_items_factory(
        offer_id="65304999CA01A12",
        line_number=2,
        renewal_date=(date.today() - timedelta(days=5)).isoformat(),
    )
    items = valid_items + expired_items
    adobe_preview_transfer = adobe_preview_transfer_factory(items=items)
    mocker.patch(
        "adobe_vipm.flows.validation.transfer.get_prices_for_skus",
        return_value={
            valid_items[0]["offerId"]: 12.14,
            expired_items[0]["offerId"]: 33.04,
        }
    )
    mocked_adobe_client = mocker.MagicMock()
    mocked_adobe_client.preview_transfer.return_value = adobe_preview_transfer

    mocked_get_product_items_by_skus = mocker.patch(
        "adobe_vipm.flows.validation.transfer.get_product_items_by_skus",
        return_value=product_items,
    )

    has_errors, validated_order = validate_transfer(
        m_client, mocked_adobe_client, order
    )
    lines = lines_factory(line_id=None, unit_purchase_price=12.14)
    assert has_errors is False
    assert validated_order["lines"] == lines

    mocked_get_product_items_by_skus.assert_called_once_with(
        m_client,
        order["agreement"]["product"]["id"],
        [adobe_preview_transfer["items"][0]["offerId"][:10]],
    )


def test_validate_transfer_lines_exist(
    mocker,
    order_factory,
    items_factory,
    transfer_order_parameters_factory,
    adobe_preview_transfer_factory,
    adobe_items_factory,
    lines_factory,
):
    mocker.patch(
        "adobe_vipm.flows.validation.transfer.get_transfer_by_authorization_membership_or_customer",
        return_value=None,
    )
    m_client = mocker.MagicMock()
    order = order_factory(
        order_parameters=transfer_order_parameters_factory(),
    )
    product_items = items_factory()

    valid_items = adobe_items_factory(
        renewal_date=date.today().isoformat(),
    )
    expired_items = adobe_items_factory(
        offer_id="65304999CA01A12",
        line_number=2,
        renewal_date=(date.today() - timedelta(days=5)).isoformat(),
    )
    items = valid_items + expired_items
    adobe_preview_transfer = adobe_preview_transfer_factory(items=items)
    mocker.patch(
        "adobe_vipm.flows.validation.transfer.get_prices_for_skus",
        return_value={
            valid_items[0]["offerId"]: 12.14,
            expired_items[0]["offerId"]: 33.04,
        }
    )

    mocked_adobe_client = mocker.MagicMock()
    mocked_adobe_client.preview_transfer.return_value = adobe_preview_transfer

    mocked_get_product_items_by_skus = mocker.patch(
        "adobe_vipm.flows.validation.transfer.get_product_items_by_skus",
        return_value=product_items,
    )

    has_errors, validated_order = validate_transfer(
        m_client, mocked_adobe_client, order
    )
    assert has_errors is False
    assert validated_order["lines"] == lines_factory()

    mocked_get_product_items_by_skus.assert_called_once_with(
        m_client,
        order["agreement"]["product"]["id"],
        [adobe_preview_transfer["items"][0]["offerId"][:10]],
    )


@pytest.mark.parametrize(
    "status_code",
    [
        STATUS_TRANSFER_INVALID_MEMBERSHIP,
        STATUS_TRANSFER_INVALID_MEMBERSHIP_OR_TRANSFER_IDS,
    ]
    + UNRECOVERABLE_TRANSFER_STATUSES,
)
def test_validate_transfer_membership_error(
    mocker,
    order_factory,
    transfer_order_parameters_factory,
    adobe_api_error_factory,
    status_code,
):
    mocker.patch(
        "adobe_vipm.flows.validation.transfer.get_transfer_by_authorization_membership_or_customer",
        return_value=None,
    )
    m_client = mocker.MagicMock()
    order = order_factory(order_parameters=transfer_order_parameters_factory())
    api_error = AdobeAPIError(
        400,
        adobe_api_error_factory(status_code, "An error"),
    )
    mocked_adobe_client = mocker.MagicMock()
    mocked_adobe_client.preview_transfer.side_effect = api_error

    has_errors, validated_order = validate_transfer(
        m_client, mocked_adobe_client, order
    )

    assert has_errors is True

    param = get_ordering_parameter(validated_order, PARAM_MEMBERSHIP_ID)
    assert param["error"] == ERR_ADOBE_MEMBERSHIP_ID.to_dict(
        title=param["name"],
        details=str(api_error),
    )
    assert param["constraints"]["hidden"] is False
    assert param["constraints"]["required"] is True


@pytest.mark.parametrize(
    ("error", "expected_message"),
    [
        (AdobeHttpError(404, "Not Found"), ERR_ADOBE_MEMBERSHIP_NOT_FOUND),
        (
            AdobeHttpError(500, "Internal Server Error"),
            ERR_ADOBE_UNEXPECTED_ERROR,
        ),
    ],
)
def test_validate_transfer_http_error(
    mocker,
    order_factory,
    transfer_order_parameters_factory,
    error,
    expected_message,
):
    mocker.patch(
        "adobe_vipm.flows.validation.transfer.get_transfer_by_authorization_membership_or_customer",
        return_value=None,
    )
    m_client = mocker.MagicMock()
    order = order_factory(order_parameters=transfer_order_parameters_factory())

    mocked_adobe_client = mocker.MagicMock()
    mocked_adobe_client.preview_transfer.side_effect = error

    has_errors, validated_order = validate_transfer(
        m_client, mocked_adobe_client, order
    )

    assert has_errors is True

    param = get_ordering_parameter(validated_order, PARAM_MEMBERSHIP_ID)
    assert param["error"] == ERR_ADOBE_MEMBERSHIP_ID.to_dict(
        title=param["name"],
        details=expected_message,
    )
    assert param["constraints"]["hidden"] is False
    assert param["constraints"]["required"] is True


def test_validate_transfer_unknown_item(
    mocker,
    order_factory,
    transfer_order_parameters_factory,
    adobe_preview_transfer_factory,
):
    mocker.patch(
        "adobe_vipm.flows.validation.transfer.get_transfer_by_authorization_membership_or_customer",
        return_value=None,
    )
    m_client = mocker.MagicMock()
    order = order_factory(order_parameters=transfer_order_parameters_factory())
    adobe_preview_transfer = adobe_preview_transfer_factory()
    mocked_adobe_client = mocker.MagicMock()
    mocked_adobe_client.preview_transfer.return_value = adobe_preview_transfer

    mocker.patch(
        "adobe_vipm.flows.validation.transfer.get_product_items_by_skus",
        return_value=[],
    )
    mocker.patch(
        "adobe_vipm.flows.validation.transfer.get_prices",
        return_value=[],
    )

    has_errors, validated_order = validate_transfer(
        m_client, mocked_adobe_client, order
    )

    assert has_errors is True
    param = get_ordering_parameter(validated_order, PARAM_MEMBERSHIP_ID)
    assert param["error"] == ERR_ADOBE_MEMBERSHIP_ID_ITEM.to_dict(
        title=param["name"],
        item_sku=adobe_preview_transfer["items"][0]["offerId"][:10],
    )
    assert param["constraints"]["hidden"] is False
    assert param["constraints"]["required"] is True


def test_validate_transfer_already_migrated(
    mocker,
    order_factory,
    transfer_order_parameters_factory,
    adobe_customer_factory,
    adobe_subscription_factory,
    adobe_authorizations_file,
):
    order_params = transfer_order_parameters_factory()
    order = order_factory(order_parameters=order_params)
    mocked_transfer = mocker.MagicMock()
    mocked_transfer.customer_id = "customer-id"

    m_client = mocker.MagicMock()

    mocked_get_transfer = mocker.patch(
        "adobe_vipm.flows.validation.transfer.get_transfer_by_authorization_membership_or_customer",
        return_value=mocked_transfer,
    )

    mocked_add_lines_to_order = mocker.patch(
        "adobe_vipm.flows.validation.transfer.add_lines_to_order",
        return_value=(False, order),
    )
    mocker.patch(
        "adobe_vipm.flows.validation.transfer.get_transfer_item_sku_by_subscription",
        return_value="65304578CA03A12",
    )
    adobe_subscription = adobe_subscription_factory()

    mocked_adobe_client = mocker.MagicMock()
    mocked_adobe_client.get_subscriptions.return_value = {
        "items": [adobe_subscription],
    }
    mocked_adobe_client.get_customer.return_value = adobe_customer_factory()

    has_errors, validated_order = validate_transfer(
        m_client, mocked_adobe_client, order
    )

    membership_param = get_ordering_parameter(order, PARAM_MEMBERSHIP_ID)

    assert has_errors is False
    assert validated_order == order
    mocked_get_transfer.assert_called_once_with(
        order["agreement"]["product"]["id"],
        adobe_authorizations_file["authorizations"][0]["authorization_id"],
        membership_param["value"],
    )
    mocked_adobe_client.get_subscriptions.assert_called_once_with(
        adobe_authorizations_file["authorizations"][0]["authorization_id"],
        mocked_transfer.customer_id,
    )

    mocked_add_lines_to_order.assert_called_once_with(
        m_client,
        order,
        {
            "items": [adobe_subscription],
        },
        {},
        "currentQuantity",
    )
    assert adobe_subscription["offerId"] == "65304578CA03A12"


def test_validate_transfer_migration_running(
    mocker,
    order_factory,
    transfer_order_parameters_factory,
):
    m_client = mocker.MagicMock()
    mocked_adobe_client = mocker.MagicMock()

    order_params = transfer_order_parameters_factory()
    order = order_factory(order_parameters=order_params)
    mocked_transfer = mocker.MagicMock()
    mocked_transfer.customer_id = "customer-id"
    mocked_transfer.status = "running"

    m_client = mocker.MagicMock()

    mocker.patch(
        "adobe_vipm.flows.validation.transfer.get_transfer_by_authorization_membership_or_customer",
        return_value=mocked_transfer,
    )

    has_errors, validated_order = validate_transfer(
        m_client, mocked_adobe_client, order
    )

    assert has_errors is True

    param = get_ordering_parameter(validated_order, PARAM_MEMBERSHIP_ID)
    assert param["error"] == ERR_ADOBE_MEMBERSHIP_ID.to_dict(
        title=param["name"],
        details="Migration in progress, retry later",
    )
    assert param["constraints"]["hidden"] is False
    assert param["constraints"]["required"] is True


def test_validate_transfer_migration_synchronized(
    mocker,
    order_factory,
    transfer_order_parameters_factory,
):
    m_client = mocker.MagicMock()
    mocked_adobe_client = mocker.MagicMock()

    order_params = transfer_order_parameters_factory()
    order = order_factory(order_parameters=order_params)
    mocked_transfer = mocker.MagicMock()
    mocked_transfer.customer_id = "customer-id"
    mocked_transfer.status = "synchronized"

    m_client = mocker.MagicMock()

    mocker.patch(
        "adobe_vipm.flows.validation.transfer.get_transfer_by_authorization_membership_or_customer",
        return_value=mocked_transfer,
    )

    has_errors, validated_order = validate_transfer(
        m_client, mocked_adobe_client, order
    )

    assert has_errors is True

    param = get_ordering_parameter(validated_order, PARAM_MEMBERSHIP_ID)
    assert param["error"] == ERR_ADOBE_MEMBERSHIP_ID.to_dict(
        title=param["name"],
        details="Membership has already been migrated",
    )
    assert param["constraints"]["hidden"] is False
    assert param["constraints"]["required"] is True


def test_validate_transfer_no_items(
    mocker,
    order_factory,
    transfer_order_parameters_factory,
    adobe_preview_transfer_factory,
):
    mocker.patch(
        "adobe_vipm.flows.validation.transfer.get_transfer_by_authorization_membership_or_customer",
        return_value=None,
    )
    m_client = mocker.MagicMock()
    order = order_factory(order_parameters=transfer_order_parameters_factory())
    adobe_preview_transfer = adobe_preview_transfer_factory(items=[])
    mocked_adobe_client = mocker.MagicMock()
    mocked_adobe_client.preview_transfer.return_value = adobe_preview_transfer

    has_errors, validated_order = validate_transfer(
        m_client, mocked_adobe_client, order
    )

    assert has_errors is True
    param = get_ordering_parameter(validated_order, PARAM_MEMBERSHIP_ID)
    assert param["error"] == ERR_ADOBE_MEMBERSHIP_ID_EMPTY.to_dict()
    assert param["constraints"]["hidden"] is False
    assert param["constraints"]["required"] is True


def test_get_prices(mocker, order_factory):
    mocked_get_prices_for_skus = mocker.patch(
        "adobe_vipm.flows.validation.transfer.get_prices_for_skus",
        return_value={"sku-1": 10.11},
    )
    order = order_factory()
    assert get_prices(order, None, ["sku-1"]) == {"sku-1": 10.11}

    mocked_get_prices_for_skus.assert_called_once_with(
        order["agreement"]["product"]["id"],
        order["agreement"]["listing"]["priceList"]["currency"],
        ["sku-1"],
    )


def test_validate_transfer_account_inactive(
    mocker,
    order_factory,
    transfer_order_parameters_factory,
    adobe_transfer_factory,
    adobe_subscription_factory,
):
    m_client = mocker.MagicMock()
    mocked_adobe_client = mocker.MagicMock()
    adobe_subscription = adobe_subscription_factory()
    adobe_transfer = adobe_transfer_factory(
        status=STATUS_TRANSFER_INACTIVE_ACCOUNT,
    )

    order_params = transfer_order_parameters_factory()
    order = order_factory(order_parameters=order_params)
    mocked_transfer = mocker.MagicMock()
    mocked_transfer.customer_id = "customer-id"
    mocked_transfer.status = "completed"

    mocker.patch(
        "adobe_vipm.flows.validation.transfer.get_transfer_by_authorization_membership_or_customer",
        return_value=mocked_transfer,
    )

    mocked_adobe_client.get_subscriptions.return_value = {
        "items": [adobe_subscription],
    }
    mocked_adobe_client.get_transfer.return_value = adobe_transfer

    has_errors, validated_order = validate_transfer(
        m_client, mocked_adobe_client, order
    )

    assert has_errors is True

    param = get_ordering_parameter(validated_order, PARAM_MEMBERSHIP_ID)
    assert param["error"] == ERR_ADOBE_MEMBERSHIP_ID_INACTIVE_ACCOUNT.to_dict(
        status=STATUS_TRANSFER_INACTIVE_ACCOUNT,
    )
    assert param["constraints"]["hidden"] is False
    assert param["constraints"]["required"] is True


@pytest.mark.parametrize(
    "commitment_status",
    [STATUS_3YC_ACTIVE, STATUS_3YC_COMMITTED],
)
def test_get_prices_3yc(mocker, order_factory, adobe_commitment_factory, commitment_status):
    commitment = adobe_commitment_factory(
        end_date=(date.today() + timedelta(days=1)).isoformat(),
        status=commitment_status,
    )

    mocked_get_prices_for_skus = mocker.patch(
        "adobe_vipm.flows.validation.transfer.get_prices_for_3yc_skus",
        return_value={"sku-1": 10.11},
    )
    order = order_factory()
    assert get_prices(order, commitment, ["sku-1"]) == {"sku-1": 10.11}

    mocked_get_prices_for_skus.assert_called_once_with(
        order["agreement"]["product"]["id"],
        order["agreement"]["listing"]["priceList"]["currency"],
        date.fromisoformat(commitment["startDate"]),
        ["sku-1"],
    )


def test_get_prices_3yc_expired(mocker, order_factory, adobe_commitment_factory):
    commitment = adobe_commitment_factory(
        end_date=(date.today() - timedelta(days=1)).isoformat(),
    )

    mocked_get_prices_for_skus = mocker.patch(
        "adobe_vipm.flows.validation.transfer.get_prices_for_skus",
        return_value={"sku-1": 10.11},
    )
    mocked_get_prices_for_3yc_skus = mocker.patch(
        "adobe_vipm.flows.validation.transfer.get_prices_for_3yc_skus",
    )
    order = order_factory()
    assert get_prices(order, commitment, ["sku-1"]) == {"sku-1": 10.11}

    mocked_get_prices_for_skus.assert_called_once_with(
        order["agreement"]["product"]["id"],
        order["agreement"]["listing"]["priceList"]["currency"],
        ["sku-1"],
    )
    mocked_get_prices_for_3yc_skus.assert_not_called()
