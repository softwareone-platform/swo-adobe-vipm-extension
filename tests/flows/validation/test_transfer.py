import datetime as dt
from unittest.mock import ANY

import pytest
from mpt_extension_sdk.mpt_http.wrap_http_error import MPTAPIError

from adobe_vipm.adobe.constants import (
    AdobeStatus,
    ThreeYearCommitmentStatus,
)
from adobe_vipm.adobe.errors import AdobeAPIError, AdobeHttpError
from adobe_vipm.flows.constants import (
    ERR_ADOBE_MEMBERSHIP_ID,
    ERR_ADOBE_MEMBERSHIP_ID_EMPTY,
    ERR_ADOBE_MEMBERSHIP_ID_INACTIVE_ACCOUNT,
    ERR_ADOBE_MEMBERSHIP_ID_ITEM,
    ERR_ADOBE_MEMBERSHIP_NOT_FOUND,
    ERR_ADOBE_MEMBERSHIP_PROCESSING,
    ERR_ADOBE_UNEXPECTED_ERROR,
    ERR_UPDATING_TRANSFER_ITEMS,
    Param,
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
    today = dt.datetime.now(tz=dt.UTC).date()
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
        renewal_date=today.isoformat(),
    )
    expired_items = adobe_items_factory(
        offer_id="65304999CA01A12",
        line_number=2,
        renewal_date=(today - dt.timedelta(days=5)).isoformat(),
    )
    items = valid_items + expired_items
    adobe_preview_transfer = adobe_preview_transfer_factory(items=items)
    mocker.patch(
        "adobe_vipm.flows.validation.transfer.get_prices_for_skus",
        return_value={
            valid_items[0]["offerId"]: 12.14,
            expired_items[0]["offerId"]: 33.04,
        },
    )
    mocked_adobe_client = mocker.MagicMock()
    mocked_adobe_client.preview_transfer.return_value = adobe_preview_transfer

    mocked_get_product_items_by_skus = mocker.patch(
        "adobe_vipm.flows.validation.transfer.get_product_items_by_skus",
        return_value=product_items,
    )
    mocker.patch(
        "adobe_vipm.flows.validation.transfer.get_adobe_client",
        return_value=mocked_adobe_client,
    )
    has_errors, validated_order = validate_transfer(m_client, order)
    lines = lines_factory(line_id=None, unit_purchase_price=12.14)
    assert has_errors is False
    assert len(validated_order["lines"]) == len(lines)

    mocked_get_product_items_by_skus.assert_called_once_with(
        m_client,
        ANY,
        [
            adobe_preview_transfer["items"][0]["offerId"][:10],
            adobe_preview_transfer["items"][1]["offerId"][:10],
        ],
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
    today = dt.datetime.now(tz=dt.UTC).date()
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
        renewal_date=today.isoformat(),
    )
    expired_items = adobe_items_factory(
        offer_id="65304999CA01A12",
        line_number=2,
        renewal_date=(today - dt.timedelta(days=5)).isoformat(),
    )
    items = valid_items + expired_items
    adobe_preview_transfer = adobe_preview_transfer_factory(items=items)
    mocker.patch(
        "adobe_vipm.flows.validation.transfer.get_prices_for_skus",
        return_value={
            valid_items[0]["offerId"]: 12.14,
            expired_items[0]["offerId"]: 33.04,
        },
    )

    mocked_adobe_client = mocker.MagicMock()
    mocked_adobe_client.preview_transfer.return_value = adobe_preview_transfer

    mocked_get_product_items_by_skus = mocker.patch(
        "adobe_vipm.flows.validation.transfer.get_product_items_by_skus",
        return_value=product_items,
    )
    mocker.patch(
        "adobe_vipm.flows.validation.transfer.get_adobe_client",
        return_value=mocked_adobe_client,
    )
    has_errors, validated_order = validate_transfer(m_client, order)
    assert has_errors is False
    assert validated_order["lines"] == lines_factory()

    mocked_get_product_items_by_skus.assert_called_once_with(
        m_client,
        ANY,
        [
            adobe_preview_transfer["items"][0]["offerId"][:10],
            adobe_preview_transfer["items"][1]["offerId"][:10],
        ],
    )


@pytest.mark.parametrize(
    "status_code",
    [
        AdobeStatus.TRANSFER_INVALID_MEMBERSHIP.value,
        AdobeStatus.TRANSFER_INVALID_MEMBERSHIP_OR_TRANSFER_IDS.value,
        AdobeStatus.TRANSFER_INELIGIBLE.value,
        AdobeStatus.TRANSFER_ALREADY_TRANSFERRED.value,
        AdobeStatus.TRANSFER_INACTIVE_RESELLER.value,
        AdobeStatus.TRANSFER_NO_ADMIN_CONTACTS.value,
        AdobeStatus.TRANSFER_IN_PROGRESS.value,
    ],
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

    mocker.patch(
        "adobe_vipm.flows.validation.transfer.get_adobe_client",
        return_value=mocked_adobe_client,
    )
    has_errors, validated_order = validate_transfer(m_client, order)

    assert has_errors is True

    param = get_ordering_parameter(validated_order, Param.MEMBERSHIP_ID.value)
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

    mocker.patch(
        "adobe_vipm.flows.validation.transfer.get_adobe_client",
        return_value=mocked_adobe_client,
    )
    has_errors, validated_order = validate_transfer(m_client, order)

    assert has_errors is True

    param = get_ordering_parameter(validated_order, Param.MEMBERSHIP_ID.value)
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
    mocker.patch(
        "adobe_vipm.flows.validation.transfer.get_adobe_client",
        return_value=mocked_adobe_client,
    )
    has_errors, validated_order = validate_transfer(m_client, order)

    assert has_errors is True
    param = get_ordering_parameter(validated_order, Param.MEMBERSHIP_ID.value)
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
    mocker.patch(
        "adobe_vipm.flows.validation.transfer.get_adobe_client",
        return_value=mocked_adobe_client,
    )
    has_errors, validated_order = validate_transfer(m_client, order)

    membership_param = get_ordering_parameter(order, Param.MEMBERSHIP_ID.value)

    assert has_errors is False
    assert validated_order == order
    mocked_get_transfer.assert_called_once_with(
        ANY,
        adobe_authorizations_file["authorizations"][0]["authorization_id"],
        membership_param["value"],
    )
    mocked_adobe_client.get_subscriptions.assert_called_once_with(
        adobe_authorizations_file["authorizations"][0]["authorization_id"],
        mocked_transfer.customer_id,
    )

    mocked_add_lines_to_order.assert_called_once_with(
        m_client, ANY, [adobe_subscription], {}, Param.CURRENT_QUANTITY.value, is_transferred=True
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
    mocker.patch(
        "adobe_vipm.flows.validation.transfer.get_adobe_client",
        return_value=mocked_adobe_client,
    )
    has_errors, validated_order = validate_transfer(m_client, order)

    assert has_errors is True

    param = get_ordering_parameter(validated_order, Param.MEMBERSHIP_ID.value)
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

    mocker.patch(
        "adobe_vipm.flows.validation.transfer.get_adobe_client",
        return_value=mocked_adobe_client,
    )
    has_errors, validated_order = validate_transfer(m_client, order)

    assert has_errors is True

    param = get_ordering_parameter(validated_order, Param.MEMBERSHIP_ID.value)
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
        return_value=[],
    )

    get_product_items_by_skus_mock = mocker.patch(
        "adobe_vipm.flows.validation.transfer.get_product_items_by_skus",
        side_effect=MPTAPIError(400, {"rql_validation": ["Value has to be a non empty array."]}),
    )

    m_client = mocker.MagicMock()
    order = order_factory(order_parameters=transfer_order_parameters_factory())
    adobe_preview_transfer = adobe_preview_transfer_factory(items=[])
    mocked_adobe_client = mocker.MagicMock()
    mocked_adobe_client.preview_transfer.return_value = adobe_preview_transfer

    mocker.patch(
        "adobe_vipm.flows.validation.transfer.get_adobe_client",
        return_value=mocked_adobe_client,
    )

    has_errors, validated_order = validate_transfer(m_client, order)

    assert has_errors is True
    param = get_ordering_parameter(validated_order, Param.MEMBERSHIP_ID.value)
    assert param["error"] == ERR_ADOBE_MEMBERSHIP_ID_EMPTY.to_dict()
    assert param["constraints"]["hidden"] is False
    assert param["constraints"]["required"] is True
    get_product_items_by_skus_mock.assert_not_called()


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
        status=AdobeStatus.TRANSFER_INACTIVE_ACCOUNT.value,
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

    mocker.patch(
        "adobe_vipm.flows.validation.transfer.get_adobe_client",
        return_value=mocked_adobe_client,
    )
    has_errors, validated_order = validate_transfer(m_client, order)

    assert has_errors is True

    param = get_ordering_parameter(validated_order, Param.MEMBERSHIP_ID.value)
    assert param["error"] == ERR_ADOBE_MEMBERSHIP_ID_INACTIVE_ACCOUNT.to_dict(
        status=AdobeStatus.TRANSFER_INACTIVE_ACCOUNT.value,
    )
    assert param["constraints"]["hidden"] is False
    assert param["constraints"]["required"] is True


@pytest.mark.parametrize(
    "commitment_status",
    [ThreeYearCommitmentStatus.ACTIVE.value, ThreeYearCommitmentStatus.COMMITTED.value],
)
def test_get_prices_3yc(mocker, order_factory, adobe_commitment_factory, commitment_status):
    today = dt.datetime.now(tz=dt.UTC).date()
    commitment = adobe_commitment_factory(
        end_date=(today + dt.timedelta(days=1)).isoformat(),
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
        dt.date.fromisoformat(commitment["startDate"]),
        ["sku-1"],
    )


def test_get_prices_3yc_expired(mocker, order_factory, adobe_commitment_factory):
    today = dt.datetime.now(tz=dt.UTC).date()
    commitment = adobe_commitment_factory(
        end_date=(today - dt.timedelta(days=1)).isoformat(),
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


def test_validate_transfer_already_migrated_all_items_expired(
    mocker,
    order_factory,
    transfer_order_parameters_factory,
    adobe_customer_factory,
    adobe_subscription_factory,
    adobe_authorizations_file,
    items_factory,
    lines_factory,
):
    order_params = transfer_order_parameters_factory()
    order = order_factory(order_parameters=order_params, lines=[])
    mocked_transfer = mocker.MagicMock()
    mocked_transfer.customer_id = "customer-id"

    m_client = mocker.MagicMock()
    adobe_subscription = adobe_subscription_factory(
        status=AdobeStatus.INACTIVE_OR_GENERIC_FAILURE.value
    )

    product_items = items_factory(
        item_id=1, name="Awesome Expired product 1", external_vendor_id="65304578CA"
    ) + items_factory(item_id=2, external_vendor_id="99999999CA", term_period="one-time")

    mocked_get_transfer = mocker.patch(
        "adobe_vipm.flows.validation.transfer.get_transfer_by_authorization_membership_or_customer",
        return_value=mocked_transfer,
    )
    mocker.patch(
        "adobe_vipm.flows.validation.transfer.get_product_items_by_skus",
        return_value=product_items,
    )
    mocker.patch(
        "adobe_vipm.flows.validation.transfer.get_prices_for_skus",
        return_value={adobe_subscription["offerId"]: 33.04},
    )
    mocker.patch(
        "adobe_vipm.flows.validation.transfer.get_transfer_item_sku_by_subscription",
        return_value="65304578CA01A12",
    )

    mocked_adobe_client = mocker.MagicMock()
    mocked_adobe_client.get_subscriptions.return_value = {
        "items": [adobe_subscription],
    }
    mocked_adobe_client.get_customer.return_value = adobe_customer_factory()

    mocker.patch(
        "adobe_vipm.flows.validation.transfer.get_adobe_client",
        return_value=mocked_adobe_client,
    )
    has_errors, validated_order = validate_transfer(m_client, order)

    membership_param = get_ordering_parameter(order, Param.MEMBERSHIP_ID.value)

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

    assert adobe_subscription["offerId"] == "65304578CA01A12"
    lines = lines_factory(
        line_id=None,
        item_id=1,
        quantity=10,
        name="Awesome Expired product 1",
        external_vendor_id="65304578CA",
        unit_purchase_price=33.04,
    )

    assert len(validated_order["lines"]) == len(lines)


def test_validate_transfer_already_migrated_all_items_expired_with_one_time_item_active(
    mocker,
    order_factory,
    transfer_order_parameters_factory,
    adobe_customer_factory,
    adobe_subscription_factory,
    adobe_authorizations_file,
    items_factory,
    lines_factory,
):
    order_params = transfer_order_parameters_factory()
    order = order_factory(order_parameters=order_params, lines=[])
    mocked_transfer = mocker.MagicMock()
    mocked_transfer.customer_id = "customer-id"

    m_client = mocker.MagicMock()
    adobe_subscription = adobe_subscription_factory(
        status=AdobeStatus.INACTIVE_OR_GENERIC_FAILURE.value
    )
    adobe_one_time_subscription = adobe_subscription_factory(offer_id="99999999CA")

    product_items = items_factory(
        item_id=1, name="Awesome Expired product 1", external_vendor_id="65304578CA"
    ) + items_factory(item_id=2, external_vendor_id="99999999CA", term_period="one-time")

    mocked_get_transfer = mocker.patch(
        "adobe_vipm.flows.validation.transfer.get_transfer_by_authorization_membership_or_customer",
        return_value=mocked_transfer,
    )
    mocker.patch(
        "adobe_vipm.flows.validation.transfer.get_product_items_by_skus",
        return_value=product_items,
    )
    mocker.patch(
        "adobe_vipm.flows.validation.transfer.get_prices_for_skus",
        return_value={adobe_subscription["offerId"]: 33.04},
    )

    mocker.patch(
        "adobe_vipm.flows.validation.transfer.get_transfer_item_sku_by_subscription",
        side_effect=["65304578CA01A12", "99999999CA01A12"],
    )

    mocked_adobe_client = mocker.MagicMock()
    mocked_adobe_client.get_subscriptions.return_value = {
        "items": [adobe_subscription, adobe_one_time_subscription],
    }
    mocked_adobe_client.get_customer.return_value = adobe_customer_factory()

    mocker.patch(
        "adobe_vipm.flows.validation.transfer.get_adobe_client",
        return_value=mocked_adobe_client,
    )
    has_errors, validated_order = validate_transfer(m_client, order)

    membership_param = get_ordering_parameter(order, Param.MEMBERSHIP_ID.value)

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

    assert adobe_subscription["offerId"] == "65304578CA01A12"
    lines = lines_factory(
        line_id=None,
        item_id=1,
        quantity=10,
        name="Awesome Expired product 1",
        external_vendor_id="65304578CA",
        unit_purchase_price=33.04,
    )

    assert len(validated_order["lines"]) == len(lines)


def test_validate_transfer_already_migrated_all_items_expired_delete_existing_line(
    mocker,
    order_factory,
    transfer_order_parameters_factory,
    adobe_customer_factory,
    adobe_subscription_factory,
    adobe_authorizations_file,
    items_factory,
    lines_factory,
):
    order_params = transfer_order_parameters_factory()
    order = order_factory(
        order_parameters=order_params,
        lines=lines_factory(
            line_id=None,
            item_id=1,
            name="Awesome Expired product 1",
            external_vendor_id="65304990CA",
            unit_purchase_price=33.04,
        ),
    )
    mocked_transfer = mocker.MagicMock()
    mocked_transfer.customer_id = "customer-id"

    m_client = mocker.MagicMock()
    adobe_subscription = adobe_subscription_factory(
        status=AdobeStatus.INACTIVE_OR_GENERIC_FAILURE.value, offer_id="65304990CA"
    )
    adobe_subscription_2 = adobe_subscription_factory(
        status=AdobeStatus.INACTIVE_OR_GENERIC_FAILURE.value, offer_id="65304991CA"
    )

    product_items = items_factory(
        item_id=1, name="Awesome Expired product 1", external_vendor_id="65304990CA"
    )
    product_items.extend(
        items_factory(item_id=2, name="Awesome Expired product 2", external_vendor_id="65304991CA")
    )

    mocked_get_transfer = mocker.patch(
        "adobe_vipm.flows.validation.transfer.get_transfer_by_authorization_membership_or_customer",
        return_value=mocked_transfer,
    )
    mocker.patch(
        "adobe_vipm.flows.utils.order.get_product_onetime_items_by_ids",
        return_value=items_factory(item_id=2, external_vendor_id="99999999CA"),
    )
    mocker.patch(
        "adobe_vipm.flows.validation.transfer.get_product_items_by_skus",
        return_value=product_items,
    )
    mocker.patch(
        "adobe_vipm.flows.validation.transfer.get_prices_for_skus",
        return_value={adobe_subscription["offerId"]: 33.04},
    )

    mocker.patch(
        "adobe_vipm.flows.validation.transfer.get_transfer_item_sku_by_subscription",
        side_effect=["65304990CA03A12", "65304991CA"],
    )

    mocked_adobe_client = mocker.MagicMock()
    mocked_adobe_client.get_subscriptions.return_value = {
        "items": [adobe_subscription, adobe_subscription_2],
    }
    mocked_adobe_client.get_customer.return_value = adobe_customer_factory()

    mocker.patch(
        "adobe_vipm.flows.validation.transfer.get_adobe_client",
        return_value=mocked_adobe_client,
    )
    has_errors, validated_order = validate_transfer(m_client, order)

    membership_param = get_ordering_parameter(order, Param.MEMBERSHIP_ID.value)

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

    assert adobe_subscription["offerId"] == "65304990CA03A12"
    lines = lines_factory(
        line_id=None,
        item_id=1,
        quantity=170,
        name="Awesome Expired product 1",
        external_vendor_id="65304990CA",
        unit_purchase_price=33.04,
    )

    assert validated_order["lines"] == lines


def test_validate_transfer_already_migrated_all_items_expired_update_existing_line(
    mocker,
    order_factory,
    transfer_order_parameters_factory,
    adobe_customer_factory,
    adobe_subscription_factory,
    adobe_authorizations_file,
    items_factory,
    lines_factory,
):
    order_params = transfer_order_parameters_factory()
    order_lines = lines_factory(
        line_id=None,
        item_id=1,
        quantity=10,
        name="Awesome Expired product 1",
        external_vendor_id="65304990CA",
        unit_purchase_price=33.04,
    )
    order_lines.extend(
        lines_factory(
            line_id=None,
            item_id=2,
            quantity=20,
            name="Awesome Expired product 2",
            external_vendor_id="65304991CA",
            unit_purchase_price=35.09,
        )
    )
    order = order_factory(order_parameters=order_params, lines=order_lines)
    mocked_transfer = mocker.MagicMock()
    mocked_transfer.customer_id = "customer-id"

    m_client = mocker.MagicMock()
    adobe_subscription = adobe_subscription_factory(
        status=AdobeStatus.INACTIVE_OR_GENERIC_FAILURE.value, offer_id="65304990CA"
    )
    adobe_subscription_2 = adobe_subscription_factory(
        status=AdobeStatus.INACTIVE_OR_GENERIC_FAILURE.value, offer_id="65304991CA"
    )

    product_items = items_factory(
        item_id=1, name="Awesome Expired product 1", external_vendor_id="65304990CA"
    )
    product_items.extend(
        items_factory(item_id=2, name="Awesome Expired product 2", external_vendor_id="65304991CA")
    )

    mocked_get_transfer = mocker.patch(
        "adobe_vipm.flows.validation.transfer.get_transfer_by_authorization_membership_or_customer",
        return_value=mocked_transfer,
    )
    mocker.patch(
        "adobe_vipm.flows.utils.order.get_product_onetime_items_by_ids",
        return_value=items_factory(item_id=2, external_vendor_id="99999999CA"),
    )
    mocker.patch(
        "adobe_vipm.flows.validation.transfer.get_product_items_by_skus",
        return_value=product_items,
    )
    mocker.patch(
        "adobe_vipm.flows.validation.transfer.get_prices_for_skus",
        return_value={adobe_subscription["offerId"]: 33.04},
    )

    mocker.patch(
        "adobe_vipm.flows.validation.transfer.get_transfer_item_sku_by_subscription",
        side_effect=["65304990CA03A12", "65304991CA"],
    )

    mocked_adobe_client = mocker.MagicMock()
    mocked_adobe_client.get_subscriptions.return_value = {
        "items": [adobe_subscription, adobe_subscription_2],
    }
    mocked_adobe_client.get_customer.return_value = adobe_customer_factory()

    mocker.patch(
        "adobe_vipm.flows.validation.transfer.get_adobe_client",
        return_value=mocked_adobe_client,
    )
    has_errors, validated_order = validate_transfer(m_client, order)

    membership_param = get_ordering_parameter(order, Param.MEMBERSHIP_ID.value)

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

    assert adobe_subscription["offerId"] == "65304990CA03A12"
    lines = lines_factory(
        line_id=None,
        item_id=1,
        quantity=10,
        name="Awesome Expired product 1",
        external_vendor_id="65304990CA",
        unit_purchase_price=33.04,
    )
    lines.extend(
        lines_factory(
            line_id=None,
            item_id=2,
            quantity=20,
            name="Awesome Expired product 2",
            external_vendor_id="65304991CA",
            unit_purchase_price=35.09,
        )
    )

    assert validated_order["lines"] == lines


def test_validate_transfer_already_migrated_all_items_expired_add_new_line(
    mocker,
    order_factory,
    transfer_order_parameters_factory,
    adobe_customer_factory,
    adobe_subscription_factory,
    adobe_authorizations_file,
    items_factory,
    lines_factory,
):
    order_params = transfer_order_parameters_factory()
    order_lines = lines_factory(
        line_id=None,
        item_id=1,
        quantity=10,
        name="Awesome Expired product 1",
        external_vendor_id="65304990CA",
        unit_purchase_price=33.04,
    )
    order_lines.extend(
        lines_factory(
            line_id=None,
            item_id=2,
            quantity=20,
            name="Awesome Expired product 2",
            external_vendor_id="65304991CA",
            unit_purchase_price=35.09,
        )
    )
    order_lines.extend(
        lines_factory(
            line_id=None,
            item_id=3,
            quantity=30,
            name="Awesome Expired product 3",
            external_vendor_id="65304992CA",
            unit_purchase_price=65.25,
        )
    )
    order = order_factory(order_parameters=order_params, lines=order_lines)
    mocked_transfer = mocker.MagicMock()
    mocked_transfer.customer_id = "customer-id"

    m_client = mocker.MagicMock()
    adobe_subscription = adobe_subscription_factory(
        status=AdobeStatus.INACTIVE_OR_GENERIC_FAILURE.value, offer_id="65304990CA"
    )
    adobe_subscription_2 = adobe_subscription_factory(
        status=AdobeStatus.INACTIVE_OR_GENERIC_FAILURE.value, offer_id="65304991CA"
    )

    product_items = items_factory(
        item_id=1, name="Awesome Expired product 1", external_vendor_id="65304990CA"
    )
    product_items.extend(
        items_factory(item_id=2, name="Awesome Expired product 2", external_vendor_id="65304991CA")
    )
    product_items.extend(
        items_factory(item_id=3, name="Awesome Expired product 3", external_vendor_id="65304992CA")
    )

    mocked_get_transfer = mocker.patch(
        "adobe_vipm.flows.validation.transfer.get_transfer_by_authorization_membership_or_customer",
        return_value=mocked_transfer,
    )
    mocker.patch(
        "adobe_vipm.flows.utils.order.get_product_onetime_items_by_ids",
        return_value=items_factory(item_id=2, external_vendor_id="99999999CA"),
    )
    mocker.patch(
        "adobe_vipm.flows.validation.transfer.get_product_items_by_skus",
        return_value=product_items,
    )
    mocker.patch(
        "adobe_vipm.flows.validation.transfer.get_prices_for_skus",
        return_value={
            adobe_subscription["offerId"]: 33.04,
            adobe_subscription_2["offerId"]: 35.09,
        },
    )

    mocker.patch(
        "adobe_vipm.flows.validation.transfer.get_transfer_item_sku_by_subscription",
        side_effect=["65304990CA03A12", "65304991CA"],
    )

    mocked_adobe_client = mocker.MagicMock()
    mocked_adobe_client.get_subscriptions.return_value = {
        "items": [adobe_subscription, adobe_subscription_2],
    }
    mocked_adobe_client.get_customer.return_value = adobe_customer_factory()

    mocker.patch(
        "adobe_vipm.flows.validation.transfer.get_adobe_client",
        return_value=mocked_adobe_client,
    )
    has_errors, validated_order = validate_transfer(m_client, order)

    membership_param = get_ordering_parameter(order, Param.MEMBERSHIP_ID.value)

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

    assert adobe_subscription["offerId"] == "65304990CA03A12"
    lines = lines_factory(
        line_id=None,
        item_id=1,
        quantity=10,
        name="Awesome Expired product 1",
        external_vendor_id="65304990CA",
        unit_purchase_price=33.04,
    )
    lines.extend(
        lines_factory(
            line_id=None,
            item_id=2,
            quantity=20,
            name="Awesome Expired product 2",
            external_vendor_id="65304991CA",
            unit_purchase_price=35.09,
        )
    )
    lines.extend(
        lines_factory(
            line_id=None,
            item_id=3,
            quantity=30,
            name="Awesome Expired product 3",
            external_vendor_id="65304992CA",
            unit_purchase_price=65.25,
        )
    )

    assert validated_order["lines"] == lines


def test_validate_transfer_already_migrated_partial_items_expired_with_one_time_item_active(
    mocker,
    order_factory,
    transfer_order_parameters_factory,
    adobe_customer_factory,
    adobe_subscription_factory,
    adobe_authorizations_file,
    items_factory,
):
    order_params = transfer_order_parameters_factory()
    order = order_factory(order_parameters=order_params, lines=[])
    mocked_transfer = mocker.MagicMock()
    mocked_transfer.customer_id = "customer-id"

    m_client = mocker.MagicMock()
    adobe_subscription = adobe_subscription_factory(
        status=AdobeStatus.INACTIVE_OR_GENERIC_FAILURE.value
    )
    adobe_subscription_1 = adobe_subscription_factory(offer_id="65304578CA")
    adobe_one_time_subscription = adobe_subscription_factory(offer_id="99999999CA")

    product_items = items_factory(
        item_id=1, name="Awesome Expired product 1", external_vendor_id="65304578CA"
    ) + items_factory(item_id=2, external_vendor_id="99999999CA", term_period="one-time")
    product_items.extend(
        items_factory(
            item_id=2,
            name="Awesome one-time product 2",
            external_vendor_id="99999999CA",
        )
    )

    mocked_get_transfer = mocker.patch(
        "adobe_vipm.flows.validation.transfer.get_transfer_by_authorization_membership_or_customer",
        return_value=mocked_transfer,
    )
    mocker.patch(
        "adobe_vipm.flows.validation.transfer.get_product_items_by_skus",
        return_value=product_items,
    )
    mocker.patch(
        "adobe_vipm.flows.validation.transfer.get_prices_for_skus",
        return_value={
            adobe_subscription_1["offerId"]: 33.04,
            adobe_one_time_subscription["offerId"]: 99,
        },
    )

    mocker.patch(
        "adobe_vipm.flows.validation.transfer.get_transfer_item_sku_by_subscription",
        side_effect=["65304578CA", "65304578CA", "99999999CA"],
    )

    mocked_adobe_client = mocker.MagicMock()
    mocked_adobe_client.get_subscriptions.return_value = {
        "items": [
            adobe_subscription,
            adobe_subscription_1,
            adobe_one_time_subscription,
        ],
    }
    mocked_adobe_client.get_customer.return_value = adobe_customer_factory()

    mocker.patch(
        "adobe_vipm.flows.validation.transfer.get_adobe_client",
        return_value=mocked_adobe_client,
    )
    has_errors, validated_order = validate_transfer(m_client, order)

    membership_param = get_ordering_parameter(order, Param.MEMBERSHIP_ID.value)

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

    assert adobe_subscription["offerId"] == "65304578CA"
    assert len(validated_order["lines"]) == 2
    assert validated_order["lines"] == [
        {
            "item": {
                "externalIds": {"vendor": "65304578CA"},
                "id": "ITM-1234-1234-1234-0001",
                "name": "Awesome Expired product 1",
                "terms": {"model": "quantity", "period": "1y"},
            },
            "oldQuantity": 0,
            "price": {"unitPP": 33.04},
            "quantity": 10,
        },
        {
            "item": {
                "externalIds": {"vendor": "99999999CA"},
                "id": "ITM-1234-1234-1234-0002",
                "name": "Awesome one-time product 2",
                "terms": {"model": "quantity", "period": "1y"},
            },
            "oldQuantity": 0,
            "price": {"unitPP": 99},
            "quantity": 10,
        },
    ]


def test_validate_transfer_already_migrated_partial_items_expired_add_new_line_error(
    mocker,
    order_factory,
    transfer_order_parameters_factory,
    adobe_customer_factory,
    adobe_subscription_factory,
    adobe_authorizations_file,
    items_factory,
    lines_factory,
):
    order_params = transfer_order_parameters_factory()
    order_lines = lines_factory(
        line_id=None,
        item_id=1,
        quantity=10,
        name="Awesome product 1",
        external_vendor_id="65304990CA",
        unit_purchase_price=33.04,
    )
    order_lines.extend(
        lines_factory(
            line_id=None,
            item_id=2,
            quantity=20,
            name="Awesome Expired product 2",
            external_vendor_id="65304991CA",
            unit_purchase_price=35.09,
        )
    )

    order = order_factory(order_parameters=order_params, lines=order_lines)
    mocked_transfer = mocker.MagicMock()
    mocked_transfer.customer_id = "customer-id"

    m_client = mocker.MagicMock()
    adobe_subscription = adobe_subscription_factory(offer_id="65304990CA")
    adobe_subscription_2 = adobe_subscription_factory(
        status=AdobeStatus.INACTIVE_OR_GENERIC_FAILURE.value, offer_id="65304991CA"
    )

    product_items = items_factory(
        item_id=1, name="Awesome product 1", external_vendor_id="65304990CA"
    )
    product_items.extend(
        items_factory(item_id=2, name="Awesome Expired product 2", external_vendor_id="65304991CA")
    )

    mocker.patch(
        "adobe_vipm.flows.validation.transfer.get_transfer_by_authorization_membership_or_customer",
        return_value=mocked_transfer,
    )
    mocker.patch(
        "adobe_vipm.flows.utils.order.get_product_onetime_items_by_ids",
        return_value=items_factory(item_id=2, external_vendor_id="99999999CA"),
    )
    mocker.patch(
        "adobe_vipm.flows.validation.transfer.get_product_items_by_skus",
        return_value=product_items,
    )
    mocker.patch(
        "adobe_vipm.flows.validation.transfer.get_prices_for_skus",
        return_value={adobe_subscription["offerId"]: 33.04},
    )

    mocker.patch(
        "adobe_vipm.flows.validation.transfer.get_transfer_item_sku_by_subscription",
        side_effect=["65304990CA03A12", "65304991CA"],
    )

    mocked_adobe_client = mocker.MagicMock()
    mocked_adobe_client.get_subscriptions.return_value = {
        "items": [adobe_subscription, adobe_subscription_2],
    }
    mocked_adobe_client.get_customer.return_value = adobe_customer_factory()

    mocker.patch(
        "adobe_vipm.flows.validation.transfer.get_adobe_client",
        return_value=mocked_adobe_client,
    )
    has_errors, validated_order = validate_transfer(m_client, order)

    assert has_errors is True
    assert validated_order["error"] == ERR_UPDATING_TRANSFER_ITEMS.to_dict()

    lines = lines_factory(
        line_id=None,
        item_id=1,
        quantity=10,
        name="Awesome product 1",
        external_vendor_id="65304990CA",
        unit_purchase_price=33.04,
    )

    assert validated_order["lines"] == lines


def test_validate_transfer_already_migrated_partial_items_expired_update_line_error(
    mocker,
    order_factory,
    transfer_order_parameters_factory,
    adobe_customer_factory,
    adobe_subscription_factory,
    adobe_authorizations_file,
    items_factory,
    lines_factory,
):
    order_params = transfer_order_parameters_factory()
    order_lines = lines_factory(
        line_id=None,
        item_id=1,
        quantity=200,
        name="Awesome Expired product 1",
        external_vendor_id="65304990CA",
        unit_purchase_price=33.04,
    )

    order = order_factory(order_parameters=order_params, lines=order_lines)
    mocked_transfer = mocker.MagicMock()
    mocked_transfer.customer_id = "customer-id"

    m_client = mocker.MagicMock()
    adobe_subscription = adobe_subscription_factory(offer_id="65304990CA")
    adobe_subscription_2 = adobe_subscription_factory(
        status=AdobeStatus.INACTIVE_OR_GENERIC_FAILURE.value, offer_id="65304991CA"
    )

    product_items = items_factory(
        item_id=1, name="Awesome Expired product 1", external_vendor_id="65304990CA"
    )

    mocker.patch(
        "adobe_vipm.flows.validation.transfer.get_transfer_by_authorization_membership_or_customer",
        return_value=mocked_transfer,
    )
    mocker.patch(
        "adobe_vipm.flows.utils.order.get_product_onetime_items_by_ids",
        return_value=items_factory(item_id=2, external_vendor_id="99999999CA"),
    )
    mocker.patch(
        "adobe_vipm.flows.validation.transfer.get_product_items_by_skus",
        return_value=product_items,
    )
    mocker.patch(
        "adobe_vipm.flows.validation.transfer.get_prices_for_skus",
        return_value={adobe_subscription["offerId"]: 33.04},
    )

    mocker.patch(
        "adobe_vipm.flows.validation.transfer.get_transfer_item_sku_by_subscription",
        side_effect=["65304990CA03A12", "65304991CA"],
    )

    mocked_adobe_client = mocker.MagicMock()
    mocked_adobe_client.get_subscriptions.return_value = {
        "items": [adobe_subscription, adobe_subscription_2],
    }
    mocked_adobe_client.get_customer.return_value = adobe_customer_factory()

    mocker.patch(
        "adobe_vipm.flows.validation.transfer.get_adobe_client",
        return_value=mocked_adobe_client,
    )
    has_errors, validated_order = validate_transfer(m_client, order)

    assert has_errors is True
    assert validated_order["error"] == ERR_UPDATING_TRANSFER_ITEMS.to_dict()

    lines = lines_factory(
        line_id=None,
        item_id=1,
        quantity=10,
        name="Awesome Expired product 1",
        external_vendor_id="65304990CA",
        unit_purchase_price=33.04,
    )

    assert validated_order["lines"] == lines


def test_validate_transfer_already_migrated_partial_items_expired_remove_line_error(
    mocker,
    order_factory,
    transfer_order_parameters_factory,
    adobe_customer_factory,
    adobe_subscription_factory,
    adobe_authorizations_file,
    items_factory,
    lines_factory,
):
    order_params = transfer_order_parameters_factory()
    order_lines = lines_factory(
        line_id=None,
        item_id=1,
        quantity=200,
        name="Awesome Expired product 1",
        external_vendor_id="65304990CA",
        unit_purchase_price=33.04,
    )

    order = order_factory(order_parameters=order_params, lines=order_lines)
    mocked_transfer = mocker.MagicMock()
    mocked_transfer.customer_id = "customer-id"

    m_client = mocker.MagicMock()
    adobe_subscription = adobe_subscription_factory(offer_id="65304990CA")
    adobe_subscription_2 = adobe_subscription_factory(offer_id="65304991CA")
    adobe_subscription_3 = adobe_subscription_factory(
        status=AdobeStatus.INACTIVE_OR_GENERIC_FAILURE.value, offer_id="65304991CA"
    )

    product_items = items_factory(
        item_id=1, name="Awesome Expired product 1", external_vendor_id="65304990CA"
    )
    product_items.extend(
        items_factory(item_id=2, name="Awesome Expired product 2", external_vendor_id="65304991CA")
        + items_factory(item_id=2, external_vendor_id="99999999CA", term_period="one-time")
    )

    mocker.patch(
        "adobe_vipm.flows.validation.transfer.get_transfer_by_authorization_membership_or_customer",
        return_value=mocked_transfer,
    )

    mocker.patch(
        "adobe_vipm.flows.validation.transfer.get_product_items_by_skus",
        return_value=product_items,
    )
    mocker.patch(
        "adobe_vipm.flows.validation.transfer.get_prices_for_skus",
        return_value={
            adobe_subscription["offerId"]: 33.04,
            adobe_subscription_2["offerId"]: 35.04,
        },
    )

    mocker.patch(
        "adobe_vipm.flows.validation.transfer.get_transfer_item_sku_by_subscription",
        side_effect=["65304990CA", "65304991CA", "99999999CA"],
    )

    mocked_adobe_client = mocker.MagicMock()
    mocked_adobe_client.get_subscriptions.return_value = {
        "items": [adobe_subscription, adobe_subscription_2, adobe_subscription_3],
    }
    mocked_adobe_client.get_customer.return_value = adobe_customer_factory()

    mocker.patch(
        "adobe_vipm.flows.validation.transfer.get_adobe_client",
        return_value=mocked_adobe_client,
    )
    has_errors, validated_order = validate_transfer(m_client, order)

    assert has_errors is True
    assert validated_order["error"] == ERR_UPDATING_TRANSFER_ITEMS.to_dict()

    lines = lines_factory(
        line_id=None,
        item_id=1,
        quantity=10,
        name="Awesome Expired product 1",
        external_vendor_id="65304990CA",
        unit_purchase_price=33.04,
    )
    lines.extend(
        lines_factory(
            line_id=None,
            item_id=2,
            quantity=10,
            name="Awesome Expired product 2",
            external_vendor_id="65304991CA",
            unit_purchase_price=35.04,
        )
    )

    assert len(validated_order["lines"]) == len(lines)


def test_validate_transfer_already_migrated_no_items(
    mocker,
    order_factory,
    transfer_order_parameters_factory,
    adobe_customer_factory,
    adobe_subscription_factory,
    adobe_authorizations_file,
    items_factory,
    lines_factory,
):
    order_params = transfer_order_parameters_factory()

    order = order_factory(order_parameters=order_params, lines=[])
    mocked_transfer = mocker.MagicMock()
    mocked_transfer.customer_id = "customer-id"

    m_client = mocker.MagicMock()

    mocker.patch(
        "adobe_vipm.flows.validation.transfer.get_transfer_by_authorization_membership_or_customer",
        return_value=mocked_transfer,
    )

    mocked_adobe_client = mocker.MagicMock()
    mocked_adobe_client.get_subscriptions.return_value = {
        "items": [],
    }
    mocked_adobe_client.get_customer.return_value = adobe_customer_factory()
    mocker.patch(
        "adobe_vipm.flows.validation.transfer.get_adobe_client",
        return_value=mocked_adobe_client,
    )

    has_errors, validated_order = validate_transfer(m_client, order)

    assert has_errors is False

    assert validated_order["lines"] == []


def test_validate_transfer_already_migrated_no_items_add_line(
    mocker,
    order_factory,
    transfer_order_parameters_factory,
    adobe_customer_factory,
    adobe_subscription_factory,
    adobe_authorizations_file,
    items_factory,
    lines_factory,
):
    order_params = transfer_order_parameters_factory()

    order_lines = lines_factory(
        line_id=None,
        item_id=1,
        quantity=200,
        name="Awesome Expired product 1",
        external_vendor_id="65304990CA",
        unit_purchase_price=33.04,
    )

    order = order_factory(order_parameters=order_params, lines=order_lines)

    mocked_transfer = mocker.MagicMock()
    mocked_transfer.customer_id = "customer-id"

    m_client = mocker.MagicMock()
    product_items = items_factory(
        item_id=1, name="Awesome Expired product 1", external_vendor_id="65304990CA"
    )

    mocker.patch(
        "adobe_vipm.flows.validation.transfer.get_transfer_by_authorization_membership_or_customer",
        return_value=mocked_transfer,
    )
    mocker.patch(
        "adobe_vipm.flows.utils.order.get_product_onetime_items_by_ids",
        return_value=items_factory(item_id=2, external_vendor_id="99999999CA"),
    )
    mocker.patch(
        "adobe_vipm.flows.validation.transfer.get_product_items_by_skus",
        return_value=product_items,
    )
    mocker.patch(
        "adobe_vipm.flows.validation.transfer.get_prices_for_skus",
        return_value={
            "65304990CA": 33.04,
        },
    )

    mocker.patch(
        "adobe_vipm.flows.validation.transfer.get_transfer_item_sku_by_subscription",
        side_effect=["65304990CA"],
    )

    mocker.patch(
        "adobe_vipm.flows.validation.transfer.get_transfer_by_authorization_membership_or_customer",
        return_value=mocked_transfer,
    )

    mocked_adobe_client = mocker.MagicMock()
    mocked_adobe_client.get_subscriptions.return_value = {
        "items": [],
    }
    mocked_adobe_client.get_customer.return_value = adobe_customer_factory()

    mocker.patch(
        "adobe_vipm.flows.validation.transfer.get_adobe_client",
        return_value=mocked_adobe_client,
    )
    has_errors, validated_order = validate_transfer(m_client, order)

    assert has_errors is False
    lines = lines_factory(
        line_id=None,
        item_id=1,
        quantity=200,
        name="Awesome Expired product 1",
        external_vendor_id="65304990CA",
        unit_purchase_price=33.04,
    )

    assert len(validated_order["lines"]) == len(lines)


def test_validate_transfer_already_migrated_items_with_deployment(
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

    mocker.patch(
        "adobe_vipm.flows.validation.transfer.get_transfer_item_sku_by_subscription",
        return_value="65304578CA03A12",
    )
    adobe_subscription = adobe_subscription_factory(deployment_id="deployment-id")

    mocked_adobe_client = mocker.MagicMock()
    mocked_adobe_client.get_subscriptions.return_value = {
        "items": [adobe_subscription],
    }
    mocked_adobe_client.get_customer.return_value = adobe_customer_factory(
        global_sales_enabled=True
    )

    mocker.patch(
        "adobe_vipm.flows.validation.transfer.get_adobe_client",
        return_value=mocked_adobe_client,
    )
    has_errors, validated_order = validate_transfer(m_client, order)

    membership_param = get_ordering_parameter(validated_order, Param.MEMBERSHIP_ID.value)

    assert has_errors is True
    assert membership_param["error"] == {
        "id": "VIPM0005",
        "message": "The `Membership Id` is not valid: ('No subscriptions found"
        " without deployment ID to be added to the main agreement',).",
    }

    mocked_get_transfer.assert_called_once_with(
        ANY,
        adobe_authorizations_file["authorizations"][0]["authorization_id"],
        membership_param["value"],
    )
    mocked_adobe_client.get_subscriptions.assert_called_once_with(
        adobe_authorizations_file["authorizations"][0]["authorization_id"],
        mocked_transfer.customer_id,
    )


def test_validate_transfer_with_one_line_items(
    mocker,
    order_factory,
    items_factory,
    transfer_order_parameters_factory,
    adobe_preview_transfer_factory,
    adobe_items_factory,
    lines_factory,
):
    today = dt.datetime.now(tz=dt.UTC).date()
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
    product_items.extend(
        items_factory(item_id=2, external_vendor_id="99999999CA", term_period="one-time")
    )
    valid_items = adobe_items_factory(
        renewal_date=today.isoformat(),
    )
    one_time_item = adobe_items_factory(
        renewal_date=today.isoformat(),
        line_number=3,
        offer_id="99999999CA01A12",
    )

    expired_items = adobe_items_factory(
        offer_id="65304999CA01A12",
        line_number=2,
        renewal_date=(today - dt.timedelta(days=5)).isoformat(),
    )
    items = valid_items + expired_items + one_time_item
    adobe_preview_transfer = adobe_preview_transfer_factory(items=items)
    mocker.patch(
        "adobe_vipm.flows.validation.transfer.get_prices_for_skus",
        return_value={
            valid_items[0]["offerId"]: 12.14,
            expired_items[0]["offerId"]: 33.04,
        },
    )
    mocked_adobe_client = mocker.MagicMock()
    mocked_adobe_client.preview_transfer.return_value = adobe_preview_transfer

    mocked_get_product_items_by_skus = mocker.patch(
        "adobe_vipm.flows.validation.transfer.get_product_items_by_skus",
        return_value=product_items,
    )
    mocker.patch(
        "adobe_vipm.flows.validation.transfer.get_adobe_client",
        return_value=mocked_adobe_client,
    )

    has_errors, validated_order = validate_transfer(m_client, order)

    assert has_errors is False
    assert len(validated_order["lines"]) == 2
    assert validated_order["lines"] == [
        {
            "item": {
                "externalIds": {"vendor": "65304578CA"},
                "id": "ITM-1234-1234-1234-0001",
                "name": "Awesome product",
                "terms": {"model": "quantity", "period": "1y"},
            },
            "oldQuantity": 0,
            "price": {"unitPP": 12.14},
            "quantity": 170,
        },
        {
            "item": {
                "externalIds": {"vendor": "99999999CA"},
                "id": "ITM-1234-1234-1234-0002",
                "name": "Awesome product",
                "terms": {"model": "quantity", "period": "one-time"},
            },
            "oldQuantity": 0,
            "price": {"unitPP": 0},
            "quantity": 170,
        },
    ]

    mocked_get_product_items_by_skus.assert_called_once_with(
        m_client,
        ANY,
        [
            adobe_preview_transfer["items"][0]["offerId"][:10],
            adobe_preview_transfer["items"][1]["offerId"][:10],
            adobe_preview_transfer["items"][2]["offerId"][:10],
        ],
    )


@pytest.mark.parametrize(
    ("error", "expected_error_message"),
    [
        (AdobeHttpError(404, "Not Found"), "404 - Not Found"),
        (AdobeHttpError(500, "Internal Server Error"), "500 - Internal Server Error"),
        (
            AdobeAPIError(400, {"code": "5112", "message": "Test error"}),
            "5112 - Test error",
        ),
        (
            AdobeAPIError(
                400,
                {
                    "error": "invalid_client",
                    "error_description": "invalid client_id parameter",
                },
            ),
            "invalid_client - invalid client_id parameter",
        ),
        (
            AdobeAPIError(400, {"very very weird": "error"}),
            "None - {'very very weird': 'error'}",
        ),
    ],
)
def test_validate_transfer_adobe_errors(
    mocker,
    order_factory,
    transfer_order_parameters_factory,
    error,
    expected_error_message,
):
    """
    Test validate_transfer when Adobe API returns different types of errors.

    Args:
        mocker: pytest-mock fixture
        order_factory: Factory for creating test orders
        transfer_order_parameters_factory: Factory for creating transfer parameters
        adobe_api_error_factory: Factory for creating Adobe API errors
        error: The error to be raised by the Adobe client
        expected_error_message: The expected error message in the response
    """
    # Setup
    order_params = transfer_order_parameters_factory()
    order = order_factory(order_parameters=order_params)
    mocked_transfer = mocker.MagicMock()
    mocked_transfer.customer_id = "customer-id"
    mocked_transfer.membership_id = "test-membership-id"
    mocked_transfer.status = "completed"

    m_client = mocker.MagicMock()
    mocked_adobe_client = mocker.MagicMock()

    mocker.patch(
        "adobe_vipm.flows.validation.transfer.get_transfer_by_authorization_membership_or_customer",
        return_value=mocked_transfer,
    )

    mocked_adobe_client.get_subscriptions.side_effect = error

    mocker.patch(
        "adobe_vipm.flows.validation.transfer.get_adobe_client",
        return_value=mocked_adobe_client,
    )
    has_errors, validated_order = validate_transfer(m_client, order)

    assert has_errors is True
    param = get_ordering_parameter(validated_order, Param.MEMBERSHIP_ID.value)

    assert param["error"] == ERR_ADOBE_MEMBERSHIP_PROCESSING.to_dict(
        membership_id=mocked_transfer.membership_id,
        error=expected_error_message,
    )
