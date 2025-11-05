import copy
import datetime as dt
from unittest import mock
from urllib.parse import urljoin

import pytest
from freezegun import freeze_time

from adobe_vipm.adobe.constants import (
    ORDER_TYPE_NEW,
    ORDER_TYPE_PREVIEW,
    AdobeStatus,
    ResellerChangeAction,
    ThreeYearCommitmentStatus,
)
from adobe_vipm.adobe.errors import AdobeAPIError, AdobeError, AdobeProductNotFoundError
from adobe_vipm.flows.constants import (
    ERR_ADOBE_RESSELLER_CHANGE_PREVIEW,
    ERR_CUSTOMER_LOST_EXCEPTION,
    Param,
)
from adobe_vipm.flows.context import Context
from adobe_vipm.flows.helpers import (
    FetchResellerChangeData,
    PrepareCustomerData,
    SetupContext,
    UpdatePrices,
    Validate3YCCommitment,
    ValidateResellerChange,
    ValidateSkuAvailability,
)
from adobe_vipm.flows.utils import get_customer_data


@freeze_time("2024-01-01")
def test_setup_context_step(
    mocker, agreement, order_factory, lines_factory, fulfillment_parameters_factory
):
    mocked_get_agreement = mocker.patch(
        "adobe_vipm.flows.helpers.get_agreement", return_value=agreement
    )
    mocked_get_licensee = mocker.patch(
        "adobe_vipm.flows.helpers.get_licensee", return_value=agreement["licensee"]
    )
    mocker.patch(
        "adobe_vipm.flows.helpers.get_adobe_client",
    )

    downsizing_items = lines_factory(
        line_id=1,
        item_id=1,
        old_quantity=10,
        quantity=8,
    )
    upsizing_items = lines_factory(
        line_id=2,
        item_id=2,
        old_quantity=10,
        quantity=12,
    )

    order = order_factory(
        lines=downsizing_items + upsizing_items,
        fulfillment_parameters=fulfillment_parameters_factory(
            due_date="2025-01-01",
        ),
    )

    mocked_client = mocker.MagicMock()
    mocked_next_step = mocker.MagicMock()

    context = Context(order=order)

    step = SetupContext()
    step(mocked_client, context, mocked_next_step)

    assert context.order["agreement"] == agreement
    assert context.order["agreement"]["licensee"] == agreement["licensee"]
    assert context.due_date.strftime("%Y-%m-%d") == "2025-01-01"
    assert context.downsize_lines == downsizing_items
    assert context.upsize_lines == upsizing_items
    mocked_get_agreement.assert_called_once_with(
        mocked_client,
        order["agreement"]["id"],
    )
    mocked_get_licensee.assert_called_once_with(
        mocked_client,
        order["agreement"]["licensee"]["id"],
    )
    mocked_next_step.assert_called_once_with(mocked_client, context)


def test_setup_context_step_with_adobe_customer_and_order_id(
    mocker,
    mock_adobe_client,
    agreement,
    order_factory,
    lines_factory,
    fulfillment_parameters_factory,
    adobe_customer_factory,
):
    mocked_get_agreement = mocker.patch(
        "adobe_vipm.flows.helpers.get_agreement", return_value=agreement
    )
    mocked_get_licensee = mocker.patch(
        "adobe_vipm.flows.helpers.get_licensee", return_value=agreement["licensee"]
    )
    adobe_customer = adobe_customer_factory()
    mock_adobe_client.get_customer.return_value = adobe_customer
    order = order_factory(
        fulfillment_parameters=fulfillment_parameters_factory(
            customer_id="adobe-customer-id",
        ),
        external_ids={"vendor": "adobe-order-id"},
    )
    mocked_client = mocker.MagicMock()
    mocked_next_step = mocker.MagicMock()
    context = Context(order=order)

    step = SetupContext()
    step(mocked_client, context, mocked_next_step)

    assert context.order["agreement"] == agreement
    assert context.order["agreement"]["licensee"] == agreement["licensee"]
    assert context.due_date is None
    assert context.downsize_lines == []
    assert context.upsize_lines == []
    assert context.new_lines == order["lines"]
    assert context.adobe_customer_id == "adobe-customer-id"
    assert context.adobe_customer == adobe_customer
    assert context.adobe_new_order_id == "adobe-order-id"
    mocked_get_agreement.assert_called_once_with(mocked_client, order["agreement"]["id"])
    mocked_get_licensee.assert_called_once_with(
        mocked_client,
        order["agreement"]["licensee"]["id"],
    )
    mocked_next_step.assert_called_once_with(mocked_client, context)


@freeze_time("2025-01-01")
def test_setup_context_step_when_retry_count_was_not_zero(
    mocker,
    mock_adobe_client,
    agreement,
    order_factory,
    lines_factory,
    fulfillment_parameters_factory,
    adobe_customer_factory,
):
    mocked_get_agreement = mocker.patch(
        "adobe_vipm.flows.helpers.get_agreement", return_value=agreement
    )
    mocked_get_licensee = mocker.patch(
        "adobe_vipm.flows.helpers.get_licensee", return_value=agreement["licensee"]
    )
    adobe_customer = adobe_customer_factory()
    mock_adobe_client.get_customer.return_value = adobe_customer
    fulfillment_parameters = fulfillment_parameters_factory(customer_id="adobe-customer-id")
    fulfillment_parameters.append({"externalId": Param.RETRY_COUNT.value, "value": "1"})
    order = order_factory(
        fulfillment_parameters=fulfillment_parameters,
        external_ids={"vendor": "adobe-order-id"},
    )
    mocked_client = mocker.MagicMock()
    mocked_next_step = mocker.MagicMock()

    context = Context(order=order)

    step = SetupContext()
    step(mocked_client, context, mocked_next_step)

    assert context.due_date == dt.date(2025, 1, 31)
    mocked_get_agreement.assert_called_once_with(mocked_client, order["agreement"]["id"])
    mocked_get_licensee.assert_called_once_with(mocked_client, order["agreement"]["licensee"]["id"])
    mocked_next_step.assert_called_once_with(mocked_client, context)


def test_setup_context_step_when_adobe_get_customer_fails_with_internal_server_error(
    mocker,
    requests_mocker,
    settings,
    agreement,
    order_factory,
    fulfillment_parameters_factory,
    adobe_api_error_factory,
    adobe_authorizations_file,
    adobe_client_factory,
):
    customer_id = "adobe-customer-id"
    adobe_client, _, _ = adobe_client_factory()
    authorization_uk = adobe_authorizations_file["authorizations"][0]["authorization_uk"]
    adobe_api_error = adobe_api_error_factory(
        code=AdobeStatus.INTERNAL_SERVER_ERROR.value,
        message="Internal Server Error",
    )

    requests_mocker.get(
        urljoin(
            settings.EXTENSION_CONFIG["ADOBE_API_BASE_URL"],
            f"/v3/customers/{customer_id}",
        ),
        status=500,
        json=adobe_api_error,
    )

    with pytest.raises(AdobeError) as exc_info:
        adobe_client.get_customer(authorization_uk, customer_id)
    mocker.patch(
        "adobe_vipm.flows.helpers.get_adobe_client",
        return_value=adobe_client,
    )
    mocked_get_agreement = mocker.patch(
        "adobe_vipm.flows.helpers.get_agreement", return_value=agreement
    )
    mocked_get_licensee = mocker.patch(
        "adobe_vipm.flows.helpers.get_licensee", return_value=agreement["licensee"]
    )

    fulfillment_parameters = fulfillment_parameters_factory(
        customer_id=customer_id,
    )

    external_ids = {"vendor": customer_id}

    order = order_factory(
        fulfillment_parameters=fulfillment_parameters,
        external_ids=external_ids,
    )

    mocked_client = mocker.MagicMock()
    mocked_next_step = mocker.MagicMock()

    context = Context(order=order)

    step = SetupContext()
    step(mocked_client, context, mocked_next_step)

    assert str(exc_info.value) == f"{adobe_api_error['code']} - {adobe_api_error['message']}"
    assert context.order["agreement"] == agreement
    assert context.order["agreement"]["licensee"] == agreement["licensee"]
    assert context.due_date is None
    assert context.downsize_lines == []
    assert context.upsize_lines == []
    assert context.new_lines == order["lines"]
    assert context.adobe_customer_id == customer_id
    assert context.adobe_customer is None
    assert context.adobe_new_order_id is None
    mocked_get_agreement.assert_called_once_with(
        mocked_client,
        order["agreement"]["id"],
    )
    mocked_get_licensee.assert_called_once_with(
        mocked_client,
        order["agreement"]["licensee"]["id"],
    )
    mocked_next_step.assert_not_called()


def test_setup_context_step_when_adobe_get_customer_fails_with_lost_customer(
    mocker,
    mock_mpt_client,
    requests_mocker,
    settings,
    agreement,
    order_factory,
    fulfillment_parameters_factory,
    adobe_api_error_factory,
    adobe_authorizations_file,
    adobe_client_factory,
    mock_send_warning,
):
    customer_id = "adobe-customer-id"
    adobe_client, _, _ = adobe_client_factory()
    authorization_uk = adobe_authorizations_file["authorizations"][0]["authorization_uk"]
    adobe_api_error = adobe_api_error_factory(
        code=AdobeStatus.INVALID_CUSTOMER.value,
        message="Invalid Customer",
    )
    requests_mocker.get(
        urljoin(
            settings.EXTENSION_CONFIG["ADOBE_API_BASE_URL"],
            f"/v3/customers/{customer_id}",
        ),
        status=400,
        json=adobe_api_error,
    )
    with pytest.raises(AdobeError):
        adobe_client.get_customer(authorization_uk, customer_id)
    mocker.patch(
        "adobe_vipm.flows.helpers.get_adobe_client",
        return_value=adobe_client,
    )
    mocker.patch("adobe_vipm.flows.helpers.get_agreement", return_value=agreement)
    mocker.patch("adobe_vipm.flows.helpers.get_licensee", return_value=agreement["licensee"])
    mocked_switch_order_to_failed = mocker.patch(
        "adobe_vipm.flows.helpers.switch_order_to_failed",
    )
    mocker.patch("adobe_vipm.flows.helpers.sync_agreements_by_agreement_ids")
    fulfillment_parameters = fulfillment_parameters_factory(
        customer_id=customer_id,
    )
    external_ids = {"vendor": customer_id}
    order = order_factory(
        fulfillment_parameters=fulfillment_parameters,
        external_ids=external_ids,
    )
    mocked_next_step = mocker.MagicMock()
    context = Context(order=order)

    step = SetupContext()
    step(mock_mpt_client, context, mocked_next_step)

    mocked_switch_order_to_failed.assert_called_once_with(
        mock_mpt_client,
        context.order,
        ERR_CUSTOMER_LOST_EXCEPTION.to_dict(
            error=f"Received Adobe error {adobe_api_error['code']} - {adobe_api_error['message']}"
        ),
    )
    mock_send_warning.assert_called_once_with(
        "Lost customer adobe-customer-id.",
        f"Received Adobe error {adobe_api_error['code']} - {adobe_api_error['message']}",
    )
    mocked_next_step.assert_not_called()


def test_prepare_customer_data_step(mocker, mock_order, customer_data):
    mocked_update_order = mocker.patch(
        "adobe_vipm.flows.helpers.update_order",
    )
    mocked_client = mocker.MagicMock()
    mocked_next_step = mocker.MagicMock()
    context = Context(order=mock_order, customer_data=customer_data)

    step = PrepareCustomerData()
    step(mocked_client, context, mocked_next_step)

    mocked_update_order.assert_not_called()
    mocked_next_step.assert_called_once_with(mocked_client, context)


def test_prepare_customer_data_step_no_company_name(mocker, mock_order, customer_data):
    no_company_customer_data = copy.copy(customer_data)
    del no_company_customer_data[Param.COMPANY_NAME.value]

    mocked_update_order = mocker.patch(
        "adobe_vipm.flows.helpers.update_order",
    )
    mocked_client = mocker.MagicMock()
    mocked_next_step = mocker.MagicMock()
    context = Context(
        order=mock_order,
        order_id="order-id",
        customer_data=no_company_customer_data,
    )

    step = PrepareCustomerData()
    step(mocked_client, context, mocked_next_step)

    assert get_customer_data(context.order) == context.customer_data
    assert (
        context.customer_data[Param.COMPANY_NAME.value]
        == context.order["agreement"]["licensee"]["name"]
    )

    mocked_update_order.assert_called_once_with(
        mocked_client,
        context.order_id,
        parameters=context.order["parameters"],
    )
    mocked_next_step.assert_called_once_with(mocked_client, context)


def test_prepare_customer_data_step_no_address(mocker, mock_order, customer_data):
    no_address_customer_data = copy.copy(customer_data)
    del no_address_customer_data[Param.ADDRESS.value]

    mocked_update_order = mocker.patch(
        "adobe_vipm.flows.helpers.update_order",
    )
    mocked_client = mocker.MagicMock()
    mocked_next_step = mocker.MagicMock()
    context = Context(
        order=mock_order,
        order_id="order-id",
        customer_data=no_address_customer_data,
    )

    step = PrepareCustomerData()
    step(mocked_client, context, mocked_next_step)

    assert get_customer_data(context.order) == context.customer_data
    assert context.customer_data[Param.ADDRESS.value] == {
        "country": context.order["agreement"]["licensee"]["address"]["country"],
        "state": context.order["agreement"]["licensee"]["address"]["state"],
        "city": context.order["agreement"]["licensee"]["address"]["city"],
        "addressLine1": context.order["agreement"]["licensee"]["address"]["addressLine1"],
        "addressLine2": context.order["agreement"]["licensee"]["address"].get("addressLine2"),
        "postCode": context.order["agreement"]["licensee"]["address"]["postCode"],
    }

    mocked_update_order.assert_called_once_with(
        mocked_client,
        context.order_id,
        parameters=context.order["parameters"],
    )
    mocked_next_step.assert_called_once_with(mocked_client, context)


def test_prepare_customer_data_step_no_contact(mocker, mock_order, customer_data):
    no_contact_customer_data = copy.copy(customer_data)
    del no_contact_customer_data[Param.CONTACT.value]

    mocked_update_order = mocker.patch(
        "adobe_vipm.flows.helpers.update_order",
    )
    mocked_client = mocker.MagicMock()
    mocked_next_step = mocker.MagicMock()
    context = Context(
        order=mock_order,
        order_id="order-id",
        customer_data=no_contact_customer_data,
    )

    step = PrepareCustomerData()
    step(mocked_client, context, mocked_next_step)

    assert get_customer_data(context.order) == context.customer_data
    assert context.customer_data[Param.CONTACT.value] == {
        "firstName": context.order["agreement"]["licensee"]["contact"]["firstName"],
        "lastName": context.order["agreement"]["licensee"]["contact"]["lastName"],
        "email": context.order["agreement"]["licensee"]["contact"]["email"],
        "phone": context.order["agreement"]["licensee"]["contact"].get("phone"),
    }

    mocked_update_order.assert_called_once_with(
        mocked_client,
        context.order_id,
        parameters=context.order["parameters"],
    )
    mocked_next_step.assert_called_once_with(mocked_client, context)


def test_update_prices_step_no_orders(mocker, mock_mpt_client, mock_order):
    mocked_next_step = mocker.MagicMock()
    context = Context(
        order=mock_order,
        order_id=mock_order["id"],
        adobe_new_order=None,
        adobe_preview_order=None,
    )

    step = UpdatePrices()
    step(mock_mpt_client, context, mocked_next_step)

    mocked_next_step.assert_called_once_with(mock_mpt_client, context)


def test_update_prices_step_with_new_order(
    mocker,
    mock_mpt_client,
    mock_order,
    adobe_order_factory,
    adobe_items_factory,
    adobe_pricing_factory,
):
    adobe_order = adobe_order_factory(order_type=ORDER_TYPE_NEW)
    sku = adobe_order["lineItems"][0]["offerId"]
    mocked_get_prices = mocker.patch(
        "adobe_vipm.flows.helpers.get_prices_for_skus", return_value={sku: 121.36}
    )
    mocked_update_order = mocker.patch("adobe_vipm.flows.helpers.update_order")
    mocked_next_step = mocker.MagicMock()
    context = Context(
        order=mock_order,
        order_id=mock_order["id"],
        product_id=mock_order["agreement"]["product"]["id"],
        currency=mock_order["agreement"]["listing"]["priceList"]["currency"],
        adobe_new_order=adobe_order,
        adobe_preview_order=adobe_order_factory(
            order_type=ORDER_TYPE_PREVIEW,
            items=adobe_items_factory(pricing=adobe_pricing_factory()),
        ),
    )

    step = UpdatePrices()
    step(mock_mpt_client, context, mocked_next_step)

    mocked_get_prices.assert_not_called()
    mocked_update_order.assert_not_called()
    mocked_next_step.assert_called_once_with(mock_mpt_client, context)


def test_update_prices_step_with_preview_order(
    mocker, mock_mpt_client, mock_order, adobe_order_factory
):
    adobe_order = adobe_order_factory(order_type=ORDER_TYPE_PREVIEW)
    sku = adobe_order["lineItems"][0]["offerId"]
    mocked_get_prices = mocker.patch(
        "adobe_vipm.flows.helpers.get_prices_for_skus", return_value={sku: 121.36}
    )
    mocked_update_order = mocker.patch("adobe_vipm.flows.helpers.update_order")
    mocked_next_step = mocker.MagicMock()
    context = Context(
        order=mock_order,
        order_id=mock_order["id"],
        product_id=mock_order["agreement"]["product"]["id"],
        currency=mock_order["agreement"]["listing"]["priceList"]["currency"],
        adobe_preview_order=adobe_order,
    )

    step = UpdatePrices()
    step(mock_mpt_client, context, mocked_next_step)

    mocked_get_prices.assert_not_called()
    mocked_update_order.assert_called_once_with(
        mock_mpt_client,
        context.order_id,
        lines=[
            {
                "id": mock_order["lines"][0]["id"],
                "price": {"unitPP": 849.16},
            },
        ],
    )
    mocked_next_step.assert_called_once_with(mock_mpt_client, context)


@freeze_time("2024-11-09")
def test_update_prices_step_with_3yc_commitment(
    mocker,
    mock_mpt_client,
    mock_order,
    adobe_order_factory,
    adobe_customer_factory,
    adobe_commitment_factory,
    adobe_items_factory,
    adobe_pricing_factory,
):
    commitment = adobe_commitment_factory(
        status=ThreeYearCommitmentStatus.COMMITTED.value,
        start_date="2024-01-01",
        end_date="2025-01-01",
    )
    adobe_customer = adobe_customer_factory(commitment=commitment, commitment_request=commitment)
    mocked_update_order = mocker.patch("adobe_vipm.flows.helpers.update_order")
    mocked_next_step = mocker.MagicMock()
    context = Context(
        order=mock_order,
        order_id=mock_order["id"],
        product_id=mock_order["agreement"]["product"]["id"],
        currency=mock_order["agreement"]["listing"]["priceList"]["currency"],
        adobe_customer=adobe_customer,
        adobe_preview_order=adobe_order_factory(
            order_type=ORDER_TYPE_PREVIEW,
            items=adobe_items_factory(pricing=adobe_pricing_factory()),
        ),
    )

    step = UpdatePrices()
    step(mock_mpt_client, context, mocked_next_step)

    mocked_update_order.assert_called_once_with(
        mock_mpt_client,
        context.order_id,
        lines=[
            {
                "id": mock_order["lines"][0]["id"],
                "price": {"unitPP": 849.16},
            },
        ],
    )
    mocked_next_step.assert_called_once_with(mock_mpt_client, context)


def test_update_prices_step_with_expired_3yc_commitment(
    mocker,
    mock_mpt_client,
    mock_order,
    adobe_order_factory,
    adobe_customer_factory,
    adobe_commitment_factory,
    adobe_items_factory,
    adobe_pricing_factory,
):
    commitment = adobe_commitment_factory(
        status=ThreeYearCommitmentStatus.COMMITTED.value,
        start_date="2023-01-01",
        end_date="2024-01-01",
    )
    adobe_customer = adobe_customer_factory(commitment=commitment)
    adobe_order = adobe_order_factory(order_type=ORDER_TYPE_NEW)
    sku = adobe_order["lineItems"][0]["offerId"]
    mocked_get_prices = mocker.patch(
        "adobe_vipm.flows.helpers.get_prices_for_skus", return_value={sku: 121.36}
    )
    mocked_update_order = mocker.patch("adobe_vipm.flows.helpers.update_order")
    mocked_next_step = mocker.MagicMock()
    context = Context(
        order=mock_order,
        order_id=mock_order["id"],
        product_id=mock_order["agreement"]["product"]["id"],
        currency=mock_order["agreement"]["listing"]["priceList"]["currency"],
        adobe_customer=adobe_customer,
        adobe_preview_order=adobe_order_factory(
            order_type=ORDER_TYPE_PREVIEW,
            items=adobe_items_factory(pricing=adobe_pricing_factory()),
        ),
    )

    step = UpdatePrices()
    step(mock_mpt_client, context, mocked_next_step)

    mocked_get_prices.assert_not_called()
    mocked_update_order.assert_called_once_with(
        mock_mpt_client,
        context.order_id,
        lines=[
            {
                "id": mock_order["lines"][0]["id"],
                "price": {"unitPP": 849.16},
            },
        ],
    )
    mocked_next_step.assert_called_once_with(mock_mpt_client, context)


def test_update_prices_step_with_multiple_lines(
    mocker,
    order_factory,
    lines_factory,
    adobe_order_factory,
    adobe_items_factory,
    adobe_pricing_factory,
):
    line_1 = lines_factory()[0]
    line_2 = lines_factory(line_id=2, item_id=2)[0]
    order = order_factory(lines=[line_1, line_2])

    adobe_order = adobe_order_factory(order_type=ORDER_TYPE_NEW)
    sku = adobe_order["lineItems"][0]["offerId"]

    mocked_get_prices = mocker.patch(
        "adobe_vipm.flows.helpers.get_prices_for_skus",
        return_value={sku: 121.36},
    )
    mocked_update_order = mocker.patch(
        "adobe_vipm.flows.helpers.update_order",
    )

    mocked_client = mocker.MagicMock()
    mocked_next_step = mocker.MagicMock()

    context = Context(
        order=order,
        order_id=order["id"],
        product_id=order["agreement"]["product"]["id"],
        currency=order["agreement"]["listing"]["priceList"]["currency"],
        adobe_preview_order=adobe_order_factory(
            order_type=ORDER_TYPE_PREVIEW,
            items=adobe_items_factory(pricing=adobe_pricing_factory()),
        ),
    )

    step = UpdatePrices()
    step(mocked_client, context, mocked_next_step)

    mocked_get_prices.assert_not_called()
    mocked_update_order.assert_called_once_with(
        mocked_client,
        context.order_id,
        lines=[
            {
                "id": line_1["id"],
                "price": {"unitPP": 849.16},
            },
            {
                "id": line_2["id"],
                "price": {"unitPP": line_2["price"]["unitPP"]},
            },
        ],
    )
    mocked_next_step.assert_called_once_with(mocked_client, context)


def test_validate_3yc_commitment_without_adobe_customer(
    mocker,
    order_factory,
    mock_get_sku_adobe_mapping_model,
):
    lines = [
        {
            "id": "line-1",
            "item": {
                "externalIds": {"vendor": "65304578CA"},
            },
            "quantity": 25,
            "oldQuantity": 12,
        },
        {
            "id": "line-2",
            "item": {
                "externalIds": {"vendor": "65304578CA"},
            },
            "quantity": 25,
            "oldQuantity": 12,
        },
    ]

    order = order_factory(
        lines=lines,
    )

    context = Context(
        order=order,
        adobe_customer=None,
        adobe_customer_id=None,
        customer_data={
            "3YCLicenses": 10,
        },
        upsize_lines=lines,
    )

    mocked_next_step = mocker.MagicMock()
    mocked_client = mocker.MagicMock()

    mocker.patch(
        "adobe_vipm.flows.helpers.get_adobe_product_by_marketplace_sku",
        side_effect=mock_get_sku_adobe_mapping_model.from_id,
    )

    step = Validate3YCCommitment()
    step(mocked_client, context, mocked_next_step)

    mocked_next_step.assert_called_once_with(mocked_client, context)


def test_validate_3yc_commitment_without_adobe_customer_fail_license_quantity(
    mocker,
    order_factory,
    mock_get_sku_adobe_mapping_model,
):
    mocked_switch_order_to_failed = mocker.patch("adobe_vipm.flows.helpers.switch_order_to_failed")
    lines = [
        {
            "id": "line-1",
            "item": {
                "externalIds": {"vendor": "65304578CA"},
            },
            "quantity": 2,
            "oldQuantity": 0,
        }
    ]

    order = order_factory(
        lines=lines,
    )

    context = Context(
        order=order,
        adobe_customer=None,
        adobe_customer_id=None,
        customer_data={"3YCLicenses": 10},
        upsize_lines=lines,
    )

    mocked_next_step = mocker.MagicMock()
    mocked_client = mocker.MagicMock()

    mocker.patch(
        "adobe_vipm.flows.helpers.get_adobe_product_by_marketplace_sku",
        side_effect=mock_get_sku_adobe_mapping_model.from_id,
    )

    step = Validate3YCCommitment()
    step(mocked_client, context, mocked_next_step)

    error_call = mocked_switch_order_to_failed.call_args
    error_dict = error_call[0][2]
    error_expected = (
        "The quantity selected of 2 would place the account below the "
        "minimum commitment of 10 licenses for the three-year commitment."
    )
    assert error_expected == error_dict.get("message")


def test_validate_3yc_commitment_without_adobe_customer_fail_consumables_quantity(
    mocker,
    order_factory,
    mock_get_sku_adobe_mapping_model,
):
    mocked_switch_order_to_failed = mocker.patch("adobe_vipm.flows.helpers.switch_order_to_failed")
    lines = [
        {
            "id": "line-1",
            "item": {
                "externalIds": {"vendor": "77777777CA"},
            },
            "quantity": 2,
            "oldQuantity": 0,
        }
    ]

    order = order_factory(
        lines=lines,
    )

    context = Context(
        order=order,
        adobe_customer=None,
        adobe_customer_id=None,
        customer_data={"3YCConsumables": 10},
        upsize_lines=lines,
    )

    mocked_next_step = mocker.MagicMock()
    mocked_client = mocker.MagicMock()

    mocker.patch(
        "adobe_vipm.flows.helpers.get_adobe_product_by_marketplace_sku",
        side_effect=mock_get_sku_adobe_mapping_model.from_id,
    )

    step = Validate3YCCommitment()
    step(mocked_client, context, mocked_next_step)

    error_call = mocked_switch_order_to_failed.call_args
    error_dict = error_call[0][2]
    error_expected = (
        "The quantity selected of 2 would place the account below the "
        "minimum commitment of 10 consumables for the three-year commitment."
    )
    assert error_expected == error_dict.get("message")


def test_validate_3yc_commitment_requested_status(
    mocker,
    mock_adobe_client,
    order_factory,
    adobe_customer_factory,
    adobe_commitment_factory,
    mock_get_sku_adobe_mapping_model,
):
    commitment = adobe_commitment_factory(
        status=ThreeYearCommitmentStatus.REQUESTED.value,
        start_date="2024-01-01",
        end_date="2027-01-01",
    )

    adobe_customer = adobe_customer_factory(commitment=commitment, commitment_request=commitment)
    lines = [
        {
            "id": "line-1",
            "item": {
                "externalIds": {"vendor": "65304578CA"},
            },
            "quantity": 15,
            "oldQuantity": 15,
        }
    ]
    order = order_factory(lines=lines)
    context = Context(
        order=order,
        adobe_customer=adobe_customer,
        adobe_customer_id="test-customer-id",
        upsize_lines=lines,
    )
    mocked_next_step = mocker.MagicMock()
    mocked_client = mocker.MagicMock()
    mocker.patch(
        "adobe_vipm.flows.helpers.get_adobe_product_by_marketplace_sku",
        side_effect=mock_get_sku_adobe_mapping_model.from_id,
    )

    step = Validate3YCCommitment()
    step(mocked_client, context, mocked_next_step)

    mocked_next_step.assert_not_called()


def test_validate_3yc_commitment_expired_status(
    mocker,
    mock_adobe_client,
    order_factory,
    adobe_customer_factory,
    adobe_commitment_factory,
    adobe_subscription_factory,
    mock_get_sku_adobe_mapping_model,
):
    mocked_switch_order_to_failed = mocker.patch("adobe_vipm.flows.helpers.switch_order_to_failed")
    mocked_set_order_error = mocker.patch("adobe_vipm.flows.helpers.set_order_error")
    commitment = adobe_commitment_factory(
        status=ThreeYearCommitmentStatus.EXPIRED.value,
        start_date="2024-01-01",
        end_date="2024-01-01",
    )
    adobe_customer = adobe_customer_factory(commitment=commitment, commitment_request=commitment)
    subscriptions = {
        "items": [
            adobe_subscription_factory(
                offer_id="65304578CA",
                renewal_quantity=15,
                autorenewal_enabled=True,
            )
        ]
    }
    mock_adobe_client.get_subscriptions.return_value = subscriptions
    order = order_factory(
        lines=[
            {
                "id": "line-1",
                "item": {
                    "externalIds": {"vendor": "65304578CA"},
                },
                "quantity": 15,
                "oldQuantity": 15,
            }
        ],
    )
    context = Context(
        order=order,
        adobe_customer=adobe_customer,
        adobe_customer_id="test-customer-id",
        authorization_id="test-auth-id",
    )
    mocked_next_step = mocker.MagicMock()
    mocked_client = mocker.MagicMock()
    mocker.patch(
        "adobe_vipm.flows.helpers.get_adobe_product_by_marketplace_sku",
        side_effect=mock_get_sku_adobe_mapping_model.from_id,
    )

    step = Validate3YCCommitment()
    step(mocked_client, context, mocked_next_step)

    mocked_next_step.assert_not_called()
    mocked_switch_order_to_failed.assert_called_once()
    mocked_set_order_error.assert_not_called()
    error_call = mocked_switch_order_to_failed.call_args
    error_dict = error_call[0][2]
    error_expected = (
        "The 3-year commitment is in status EXPIRED. "
        "Please contact support to renew the commitment."
    )
    assert error_expected == error_dict.get("message")


def test_validate_3yc_commitment_item_not_found(
    mocker,
    mock_adobe_client,
    order_factory,
    adobe_customer_factory,
    adobe_commitment_factory,
    adobe_subscription_factory,
    mock_get_sku_adobe_mapping_model,
):
    mocked_switch_order_to_failed = mocker.patch("adobe_vipm.flows.helpers.switch_order_to_failed")
    mocked_set_order_error = mocker.patch("adobe_vipm.flows.helpers.set_order_error")
    commitment = adobe_commitment_factory(
        status=ThreeYearCommitmentStatus.COMMITTED.value,
        start_date="2024-01-01",
        end_date="2027-01-01",
    )
    adobe_customer = adobe_customer_factory(commitment=commitment, commitment_request=commitment)
    subscriptions = {
        "items": [
            adobe_subscription_factory(
                offer_id="77777777CA",
                renewal_quantity=8,
                autorenewal_enabled=True,
            ),
        ]
    }
    mock_adobe_client.get_subscriptions.return_value = subscriptions
    lines = [
        {
            "id": "line-1",
            "item": {
                "externalIds": {"vendor": "65304578CA"},
            },
            "quantity": 15,
            "oldQuantity": 16,
        }
    ]
    order = order_factory(lines=lines)
    context = Context(
        order=order,
        upsize_lines=lines,
        adobe_customer=adobe_customer,
        adobe_customer_id="test-customer-id",
        authorization_id="test-auth-id",
    )
    mocked_next_step = mocker.MagicMock()
    mocked_client = mocker.MagicMock()
    mocker.patch(
        "adobe_vipm.flows.helpers.get_adobe_product_by_marketplace_sku",
        side_effect=mock_get_sku_adobe_mapping_model.from_id,
    )

    step = Validate3YCCommitment()
    step(mocked_client, context, mocked_next_step)

    mocked_next_step.assert_not_called()
    mocked_switch_order_to_failed.assert_called_once()
    mocked_set_order_error.assert_not_called()
    error_call = mocked_switch_order_to_failed.call_args
    error_dict = error_call[0][2]
    assert error_dict.get("message") == "Item 65304578CA not found in Adobe subscriptions"


def test_validate_3yc_commitment_item_not_found_validation(
    mocker,
    mock_adobe_client,
    order_factory,
    adobe_customer_factory,
    adobe_commitment_factory,
    adobe_subscription_factory,
    mock_get_sku_adobe_mapping_model,
):
    mocked_switch_order_to_failed = mocker.patch("adobe_vipm.flows.helpers.switch_order_to_failed")
    mocked_set_order_error = mocker.patch("adobe_vipm.flows.helpers.set_order_error")
    commitment = adobe_commitment_factory(
        status=ThreeYearCommitmentStatus.COMMITTED.value,
        start_date="2024-01-01",
        end_date="2027-01-01",
    )
    adobe_customer = adobe_customer_factory(commitment=commitment, commitment_request=commitment)
    subscriptions = {
        "items": [
            adobe_subscription_factory(
                offer_id="77777777CA",
                renewal_quantity=8,
                autorenewal_enabled=True,
            ),
        ]
    }
    mock_adobe_client.get_subscriptions.return_value = subscriptions
    lines = [
        {
            "id": "line-1",
            "item": {
                "externalIds": {"vendor": "65304578CA"},
            },
            "quantity": 15,
            "oldQuantity": 16,
        }
    ]
    order = order_factory(lines=lines)
    context = Context(
        order=order,
        upsize_lines=lines,
        adobe_customer=adobe_customer,
        adobe_customer_id="test-customer-id",
        authorization_id="test-auth-id",
    )
    mocked_next_step = mocker.MagicMock()
    mocked_client = mocker.MagicMock()
    mocker.patch(
        "adobe_vipm.flows.helpers.get_adobe_product_by_marketplace_sku",
        side_effect=mock_get_sku_adobe_mapping_model.from_id,
    )

    step = Validate3YCCommitment(is_validation=True)
    step(mocked_client, context, mocked_next_step)

    mocked_next_step.assert_not_called()
    mocked_set_order_error.assert_called_once()
    mocked_switch_order_to_failed.assert_not_called()
    error_call = mocked_set_order_error.call_args
    error_dict = error_call[0][1]
    assert error_dict.get("message") == "Item 65304578CA not found in Adobe subscriptions"


@pytest.mark.parametrize("is_validation", [True, False])
def test_validate_3yc_commitment_below_minimum_licenses(
    mocker,
    mock_adobe_client,
    order_factory,
    adobe_customer_factory,
    adobe_commitment_factory,
    adobe_subscription_factory,
    mock_get_sku_adobe_mapping_model,
    is_validation,
):
    mocked_switch_order_to_failed = mocker.patch("adobe_vipm.flows.helpers.switch_order_to_failed")
    mocked_set_order_error = mocker.patch("adobe_vipm.flows.helpers.set_order_error")
    commitment = adobe_commitment_factory(
        status=ThreeYearCommitmentStatus.COMMITTED.value,
        start_date="2024-01-01",
        end_date="2027-01-01",
        licenses=100,
    )
    adobe_customer = adobe_customer_factory(commitment=commitment, commitment_request=commitment)
    subscriptions = {
        "items": [
            adobe_subscription_factory(
                offer_id="65304578CA",
                renewal_quantity=15,
                autorenewal_enabled=True,
            )
        ]
    }
    mock_adobe_client.get_subscriptions.return_value = subscriptions
    lines = [
        {
            "id": "line-1",
            "item": {
                "externalIds": {"vendor": "65304578CA"},
            },
            "quantity": 5,
            "oldQuantity": 15,
        },
    ]

    order = order_factory(lines=lines)
    context = Context(
        order=order,
        adobe_customer=adobe_customer,
        adobe_customer_id="test-customer-id",
        authorization_id="test-auth-id",
        downsize_lines=lines,
    )
    mocked_next_step = mocker.MagicMock()
    mocked_client = mocker.MagicMock()
    mocker.patch(
        "adobe_vipm.flows.helpers.get_adobe_product_by_marketplace_sku",
        side_effect=mock_get_sku_adobe_mapping_model.from_id,
    )

    if is_validation:
        step = Validate3YCCommitment(is_validation=True)
        step(mocked_client, context, mocked_next_step)

        mocked_next_step.assert_not_called()
        mocked_set_order_error.assert_called_once()
        mocked_switch_order_to_failed.assert_not_called()
        error_call = mocked_set_order_error.call_args
        error_dict = error_call[0][1]
        error_expected = (
            "The quantity selected of 5 would place the account "
            "below the minimum commitment of 100 licenses "
            "for the three-year commitment."
        )
        assert error_expected == error_dict.get("message")
    else:
        step = Validate3YCCommitment()
        step(mocked_client, context, mocked_next_step)
        mocked_next_step.assert_not_called()
        mocked_switch_order_to_failed.assert_called_once()
        mocked_set_order_error.assert_not_called()
        error_call = mocked_switch_order_to_failed.call_args
        error_dict = error_call[0][2]
        error_expected = (
            "The quantity selected of 5 would place the account "
            "below the minimum commitment of 100 licenses "
            "for the three-year commitment."
        )
        assert error_expected == error_dict.get("message")


@pytest.mark.parametrize("is_validation", [True, False])
def test_validate_3yc_commitment_below_minimum_consumables(
    mocker,
    mock_adobe_client,
    order_factory,
    adobe_customer_factory,
    adobe_commitment_factory,
    adobe_subscription_factory,
    mock_get_sku_adobe_mapping_model,
    is_validation,
):
    mocked_switch_order_to_failed = mocker.patch("adobe_vipm.flows.helpers.switch_order_to_failed")
    mocked_set_order_error = mocker.patch("adobe_vipm.flows.helpers.set_order_error")
    commitment = adobe_commitment_factory(
        status=ThreeYearCommitmentStatus.COMMITTED.value,
        start_date="2024-01-01",
        end_date="2027-01-01",
        consumables=100,
    )
    adobe_customer = adobe_customer_factory(commitment=commitment, commitment_request=commitment)
    subscriptions = {
        "items": [
            adobe_subscription_factory(
                offer_id="77777777CA",
                renewal_quantity=15,
                autorenewal_enabled=True,
            )
        ]
    }
    mock_adobe_client.get_subscriptions.return_value = subscriptions
    lines = [
        {
            "id": "line-1",
            "item": {
                "externalIds": {"vendor": "77777777CA"},
            },
            "quantity": 5,
            "oldQuantity": 15,
        },
    ]
    order = order_factory(lines=lines)
    context = Context(
        order=order,
        adobe_customer=adobe_customer,
        adobe_customer_id="test-customer-id",
        authorization_id="test-auth-id",
        downsize_lines=lines,
    )

    mocked_next_step = mocker.MagicMock()
    mocked_client = mocker.MagicMock()

    mocker.patch(
        "adobe_vipm.flows.helpers.get_adobe_product_by_marketplace_sku",
        side_effect=mock_get_sku_adobe_mapping_model.from_id,
    )
    if is_validation:
        step = Validate3YCCommitment(is_validation=True)
        step(mocked_client, context, mocked_next_step)

        mocked_next_step.assert_not_called()
        mocked_set_order_error.assert_called_once()
        mocked_switch_order_to_failed.assert_not_called()
        error_call = mocked_set_order_error.call_args
        error_dict = error_call[0][1]
        error_expected = (
            "The order has failed. The reduction in quantity would "
            "place the account below the minimum commitment of "
            "100 consumables for the three-year commitment."
        )
        assert error_expected == error_dict.get("message")
    else:
        step = Validate3YCCommitment()
        step(mocked_client, context, mocked_next_step)
        mocked_next_step.assert_not_called()
        mocked_switch_order_to_failed.assert_called_once()
        mocked_set_order_error.assert_not_called()
        error_call = mocked_switch_order_to_failed.call_args
        error_dict = error_call[0][2]
        error_expected = (
            "The order has failed. The reduction in quantity would "
            "place the account below the minimum commitment of "
            "100 consumables for the three-year commitment."
        )
        assert error_expected == error_dict.get("message")


def test_validate_3yc_commitment_below_minimum_consumables_and_licenses(
    mocker,
    mock_adobe_client,
    order_factory,
    adobe_customer_factory,
    adobe_commitment_factory,
    adobe_subscription_factory,
    mock_get_sku_adobe_mapping_model,
):
    mocked_switch_order_to_failed = mocker.patch("adobe_vipm.flows.helpers.switch_order_to_failed")
    mocked_set_order_error = mocker.patch("adobe_vipm.flows.helpers.set_order_error")
    commitment = adobe_commitment_factory(
        status=ThreeYearCommitmentStatus.COMMITTED.value,
        start_date="2024-01-01",
        end_date="2027-01-01",
        licenses=100,
        consumables=100,
    )
    adobe_customer = adobe_customer_factory(commitment=commitment, commitment_request=commitment)
    subscriptions = {
        "items": [
            adobe_subscription_factory(
                offer_id="65304578CA",
                renewal_quantity=15,
                autorenewal_enabled=True,
            ),
            adobe_subscription_factory(
                offer_id="77777777CA",
                renewal_quantity=15,
                autorenewal_enabled=True,
            ),
        ]
    }
    mock_adobe_client.get_subscriptions.return_value = subscriptions
    lines = [
        {
            "id": "line-1",
            "item": {
                "externalIds": {"vendor": "77777777CA"},
            },
            "quantity": 5,
            "oldQuantity": 15,
        },
    ]
    order = order_factory(lines=lines)
    context = Context(
        order=order,
        adobe_customer=adobe_customer,
        adobe_customer_id="test-customer-id",
        authorization_id="test-auth-id",
        downsize_lines=lines,
    )
    mocked_next_step = mocker.MagicMock()
    mocked_client = mocker.MagicMock()
    mocker.patch(
        "adobe_vipm.flows.helpers.get_adobe_product_by_marketplace_sku",
        side_effect=mock_get_sku_adobe_mapping_model.from_id,
    )

    step = Validate3YCCommitment(is_validation=False)
    step(mocked_client, context, mocked_next_step)

    mocked_next_step.assert_not_called()
    mocked_switch_order_to_failed.assert_called_once()
    mocked_set_order_error.assert_not_called()
    error_call = mocked_switch_order_to_failed.call_args
    error_dict = error_call[0][2]
    error_expected = (
        "The order has failed. The reduction in quantity would "
        "place the account below the minimum commitment of "
        "100 licenses or 100 consumables for the three-year commitment."
    )
    assert error_expected == error_dict.get("message")


def test_validate_3yc_commitment_success(
    mocker,
    mock_adobe_client,
    order_factory,
    adobe_customer_factory,
    adobe_commitment_factory,
    adobe_subscription_factory,
    mock_get_sku_adobe_mapping_model,
):
    mocked_switch_order_to_failed = mocker.patch("adobe_vipm.flows.helpers.switch_order_to_failed")
    mocked_set_order_error = mocker.patch("adobe_vipm.flows.helpers.set_order_error")

    commitment = adobe_commitment_factory(
        status=ThreeYearCommitmentStatus.COMMITTED.value,
        start_date="2024-01-01",
        end_date="2027-01-01",
        licenses=10,
        consumables=5,
    )
    adobe_customer = adobe_customer_factory(commitment=commitment, commitment_request=commitment)
    subscriptions = {
        "items": [
            adobe_subscription_factory(
                offer_id="65304578CA",
                renewal_quantity=15,
                autorenewal_enabled=True,
            ),
            adobe_subscription_factory(
                offer_id="77777777CA",
                renewal_quantity=8,
                autorenewal_enabled=True,
            ),
        ]
    }
    mock_adobe_client.get_subscriptions.return_value = subscriptions
    lines = [
        {
            "id": "line-1",
            "item": {
                "externalIds": {"vendor": "65304578CA"},
            },
            "quantity": 12,
            "oldQuantity": 15,
        },
        {
            "id": "line-1",
            "item": {
                "externalIds": {"vendor": "77777777CA"},
            },
            "quantity": 12,
            "oldQuantity": 7,
        },
    ]
    order = order_factory(lines=lines)
    context = Context(
        order=order,
        adobe_customer=adobe_customer,
        adobe_customer_id="test-customer-id",
        authorization_id="test-auth-id",
        downsize_lines=[order["lines"][0]],
        upsize_lines=[order["lines"][1]],
    )
    mocked_next_step = mocker.MagicMock()
    mocked_client = mocker.MagicMock()
    mocker.patch(
        "adobe_vipm.flows.helpers.get_adobe_product_by_marketplace_sku",
        side_effect=mock_get_sku_adobe_mapping_model.from_id,
    )

    step = Validate3YCCommitment()
    step(mocked_client, context, mocked_next_step)

    mocked_next_step.assert_called_once_with(mocked_client, context)
    mocked_switch_order_to_failed.assert_not_called()
    mocked_set_order_error.assert_not_called()
    assert context.order.get("status") != "failed"


def test_validate_3yc_commitment_rejected(
    mocker,
    mock_adobe_client,
    order_factory,
    adobe_customer_factory,
    adobe_commitment_factory,
    adobe_subscription_factory,
    mock_get_sku_adobe_mapping_model,
):
    mocked_switch_order_to_failed = mocker.patch("adobe_vipm.flows.helpers.switch_order_to_failed")
    mocked_set_order_error = mocker.patch("adobe_vipm.flows.helpers.set_order_error")
    adobe_customer = adobe_customer_factory(commitment=None, commitment_request=None)
    subscriptions = {
        "items": [
            adobe_subscription_factory(
                offer_id="65304578CA",
                renewal_quantity=15,
                autorenewal_enabled=True,
            )
        ]
    }
    mock_adobe_client.get_subscriptions.return_value = subscriptions
    order = order_factory(
        lines=[
            {
                "id": "line-1",
                "item": {
                    "externalIds": {"vendor": "65304578CA"},
                },
                "quantity": 15,
                "oldQuantity": 15,
            }
        ],
    )
    context = Context(
        order=order,
        adobe_customer=adobe_customer,
        adobe_customer_id="test-customer-id",
        authorization_id="test-auth-id",
        customer_data={
            "3YC": ["Yes"],
        },
    )
    mocked_next_step = mocker.MagicMock()
    mocked_client = mocker.MagicMock()
    mocker.patch(
        "adobe_vipm.flows.helpers.get_adobe_product_by_marketplace_sku",
        side_effect=mock_get_sku_adobe_mapping_model.from_id,
    )

    step = Validate3YCCommitment()
    step(mocked_client, context, mocked_next_step)

    mocked_next_step.assert_not_called()
    mocked_switch_order_to_failed.assert_called_once()
    mocked_set_order_error.assert_not_called()
    error_call = mocked_switch_order_to_failed.call_args
    error_dict = error_call[0][2]
    error_expected = (
        "The 3-year commitment is in status None. Please contact support to renew the commitment."
    )
    assert error_expected == error_dict.get("message")


def test_validate_3yc_commitment_return_order_create(
    mocker,
    order_factory,
    adobe_customer_factory,
    adobe_commitment_factory,
    adobe_subscription_factory,
    mock_get_sku_adobe_mapping_model,
):
    context = Context(
        order=None,
        adobe_customer=None,
        adobe_customer_id="test-customer-id",
        authorization_id="test-auth-id",
        customer_data={
            "3YC": ["Yes"],
        },
        adobe_return_orders={
            "items": [
                {
                    "id": "return-order-1",
                    "status": "PENDING",
                }
            ]
        },
    )

    mocked_next_step = mocker.MagicMock()
    mocked_client = mocker.MagicMock()

    mocker.patch(
        "adobe_vipm.flows.helpers.get_adobe_product_by_marketplace_sku",
        side_effect=mock_get_sku_adobe_mapping_model.from_id,
    )
    step = Validate3YCCommitment()
    step(mocked_client, context, mocked_next_step)

    mocked_next_step.assert_called_once_with(mocked_client, context)


def test_validate_3yc_commitment_no_commitment(
    mocker,
    mock_adobe_client,
    order_factory,
    adobe_customer_factory,
    adobe_subscription_factory,
    mock_get_sku_adobe_mapping_model,
):
    adobe_customer = adobe_customer_factory(commitment=None, commitment_request=None)
    subscriptions = {
        "items": [
            adobe_subscription_factory(
                offer_id="65304578CA",
                renewal_quantity=15,
                autorenewal_enabled=True,
            )
        ]
    }
    mock_adobe_client.get_subscriptions.return_value = subscriptions
    order = order_factory(
        lines=[
            {
                "id": "line-1",
                "item": {
                    "externalIds": {"vendor": "65304578CA"},
                },
                "quantity": 15,
                "oldQuantity": 15,
            }
        ],
    )

    context = Context(
        order=order,
        adobe_customer=adobe_customer,
        adobe_customer_id="test-customer-id",
        authorization_id="test-auth-id",
        customer_data={},
    )

    mocked_next_step = mocker.MagicMock()
    mocked_client = mocker.MagicMock()
    mocker.patch(
        "adobe_vipm.flows.helpers.get_adobe_product_by_marketplace_sku",
        side_effect=mock_get_sku_adobe_mapping_model.from_id,
    )

    step = Validate3YCCommitment()
    step(mocked_client, context, mocked_next_step)

    mocked_next_step.assert_called_once_with(mocked_client, context)


def test_validate_3yc_commitment_date_before_coterm_date(
    mocker,
    mock_adobe_client,
    order_factory,
    adobe_customer_factory,
    adobe_commitment_factory,
    mock_get_sku_adobe_mapping_model,
):
    commitment = adobe_commitment_factory(
        status=ThreeYearCommitmentStatus.COMMITTED.value,
        start_date="2021-01-01",
        end_date="2023-01-01",
    )
    adobe_customer = adobe_customer_factory(commitment=commitment, commitment_request=commitment)
    lines = [
        {
            "id": "line-1",
            "item": {
                "externalIds": {"vendor": "65304578CA"},
            },
            "quantity": 15,
            "oldQuantity": 15,
        }
    ]
    order = order_factory(lines=lines)
    context = Context(
        order=order,
        adobe_customer=adobe_customer,
        adobe_customer_id="test-customer-id",
        upsize_lines=lines,
    )
    mocked_next_step = mocker.MagicMock()
    mocked_client = mocker.MagicMock()
    mocker.patch(
        "adobe_vipm.flows.helpers.get_adobe_product_by_marketplace_sku",
        side_effect=mock_get_sku_adobe_mapping_model.from_id,
    )

    step = Validate3YCCommitment()
    step(mocked_client, context, mocked_next_step)

    mocked_next_step.assert_called_once()


def test_validate_3yc_commitment_date_without_coterm_date(
    mocker,
    mock_adobe_client,
    order_factory,
    adobe_customer_factory,
    adobe_commitment_factory,
    adobe_subscription_factory,
    mock_get_sku_adobe_mapping_model,
):
    mocked_switch_order_to_failed = mocker.patch("adobe_vipm.flows.helpers.switch_order_to_failed")
    mocked_set_order_error = mocker.patch("adobe_vipm.flows.helpers.set_order_error")
    commitment = adobe_commitment_factory(
        status=ThreeYearCommitmentStatus.COMMITTED.value,
        start_date="2024-01-01",
        end_date="2027-01-01",
        licenses=10,
        consumables=5,
    )
    adobe_customer = adobe_customer_factory(
        commitment=commitment, commitment_request=commitment, coterm_date=None
    )
    subscriptions = {
        "items": [
            adobe_subscription_factory(
                offer_id="65304578CA",
                renewal_quantity=15,
                autorenewal_enabled=True,
            ),
            adobe_subscription_factory(
                offer_id="77777777CA",
                renewal_quantity=8,
                autorenewal_enabled=True,
            ),
        ]
    }
    mock_adobe_client.get_subscriptions.return_value = subscriptions
    lines = [
        {
            "id": "line-1",
            "item": {
                "externalIds": {"vendor": "65304578CA"},
            },
            "quantity": 12,
            "oldQuantity": 15,
        },
        {
            "id": "line-1",
            "item": {
                "externalIds": {"vendor": "77777777CA"},
            },
            "quantity": 12,
            "oldQuantity": 7,
        },
    ]
    order = order_factory(lines=lines)
    context = Context(
        order=order,
        adobe_customer=adobe_customer,
        adobe_customer_id="test-customer-id",
        authorization_id="test-auth-id",
        downsize_lines=[order["lines"][0]],
        upsize_lines=[order["lines"][1]],
    )
    mocked_next_step = mocker.MagicMock()
    mocked_client = mocker.MagicMock()
    mocker.patch(
        "adobe_vipm.flows.helpers.get_adobe_product_by_marketplace_sku",
        side_effect=mock_get_sku_adobe_mapping_model.from_id,
    )

    step = Validate3YCCommitment()
    step(mocked_client, context, mocked_next_step)

    mocked_next_step.assert_called_once_with(mocked_client, context)
    mocked_switch_order_to_failed.assert_not_called()
    mocked_set_order_error.assert_not_called()
    assert context.order.get("status") != "failed"


def test_validate_3yc_commitment_sku_not_found(
    mocker,
    mock_adobe_client,
    order_factory,
    adobe_customer_factory,
    adobe_commitment_factory,
    adobe_subscription_factory,
):
    mocked_switch_order_to_failed = mocker.patch("adobe_vipm.flows.helpers.switch_order_to_failed")
    commitment = adobe_commitment_factory(
        status=ThreeYearCommitmentStatus.COMMITTED.value,
        start_date="2024-01-01",
        end_date="2027-01-01",
        licenses=10,
        consumables=5,
    )
    adobe_customer = adobe_customer_factory(
        commitment=commitment, commitment_request=commitment, coterm_date=None
    )
    subscriptions = {
        "items": [
            adobe_subscription_factory(
                offer_id="65304578CA",
                renewal_quantity=15,
                autorenewal_enabled=True,
            ),
            adobe_subscription_factory(
                offer_id="77777777CA",
                renewal_quantity=8,
                autorenewal_enabled=True,
            ),
        ]
    }
    mock_adobe_client.get_subscriptions.return_value = subscriptions
    lines = [
        {
            "id": "line-1",
            "item": {
                "externalIds": {"vendor": "65304578CA"},
            },
            "quantity": 12,
            "oldQuantity": 15,
        },
        {
            "id": "line-1",
            "item": {
                "externalIds": {"vendor": "77777777CA"},
            },
            "quantity": 12,
            "oldQuantity": 7,
        },
    ]
    order = order_factory(lines=lines)
    context = Context(
        order=order,
        adobe_customer=adobe_customer,
        adobe_customer_id="test-customer-id",
        authorization_id="test-auth-id",
        downsize_lines=[order["lines"][0]],
        upsize_lines=[order["lines"][1]],
    )
    mocked_next_step = mocker.MagicMock()
    mocked_client = mocker.MagicMock()
    mocked_send_notification = mocker.patch("adobe_vipm.flows.helpers.send_exception")
    mocker.patch(
        "adobe_vipm.flows.helpers.get_adobe_product_by_marketplace_sku",
        side_effect=AdobeProductNotFoundError("Product not found in Adobe configuration"),
    )

    step = Validate3YCCommitment()
    step(mocked_client, context, mocked_next_step)

    assert mocked_switch_order_to_failed.call_args[0][2]["message"] == (
        "The order has failed. The reduction in quantity "
        "would place the account below the minimum commitment "
        "of 10 licenses or 5 consumables for the three-year commitment."
    )
    mocked_send_notification.assert_has_calls([
        mock.call("Adobe product not found in airtable for SKU: %s", "65304578CA")
    ])


def test_fetch_reseller_change_data_success(
    mocker,
    order_factory,
    reseller_change_order_parameters_factory,
    adobe_reseller_change_preview_factory,
    mock_next_step,
    mock_mpt_client,
    mock_adobe_client,
):
    adobe_transfer = adobe_reseller_change_preview_factory()
    order = order_factory(order_parameters=reseller_change_order_parameters_factory())

    mock_adobe_client.reseller_change_request.return_value = adobe_transfer

    mocker.patch(
        "adobe_vipm.flows.helpers.get_adobe_client",
        return_value=mock_adobe_client,
    )

    context = Context(
        order=order,
        order_id="order-id",
        agreement_id="agreement-id",
        authorization_id="AUT-1234-4567",
    )

    step = FetchResellerChangeData(is_validation=False)
    step(mock_mpt_client, context, mock_next_step)

    mock_adobe_client.reseller_change_request.assert_called_once_with(
        context.authorization_id,
        context.order["agreement"]["seller"]["id"],
        "88888888",
        "admin@admin.com",
        ResellerChangeAction.PREVIEW,
    )
    assert context.adobe_transfer == adobe_transfer
    mock_next_step.assert_called_once_with(mock_mpt_client, context)


def test_fetch_reseller_change_data_already_has_customer_id(
    mocker,
    order_factory,
    reseller_change_order_parameters_factory,
    mock_next_step,
    mock_mpt_client,
    mock_adobe_client,
):
    order = order_factory(order_parameters=reseller_change_order_parameters_factory())

    mocker.patch(
        "adobe_vipm.flows.helpers.get_adobe_client",
        return_value=mock_adobe_client,
    )

    context = Context(
        order=order,
        adobe_customer_id="existing-customer-id",
    )

    step = FetchResellerChangeData(is_validation=False)
    step(mock_mpt_client, context, mock_next_step)

    mock_adobe_client.reseller_change_request.assert_not_called()
    mock_next_step.assert_called_once_with(mock_mpt_client, context)


def test_fetch_reseller_change_data_adobe_api_error_fulfillment_mode(
    mocker,
    order_factory,
    reseller_change_order_parameters_factory,
    mock_next_step,
    mock_mpt_client,
    mock_adobe_client,
):
    order = order_factory(order_parameters=reseller_change_order_parameters_factory())
    api_error = AdobeAPIError(400, {"code": "9999", "message": "Adobe error"})

    mock_adobe_client.reseller_change_request.side_effect = api_error

    mocker.patch(
        "adobe_vipm.flows.helpers.get_adobe_client",
        return_value=mock_adobe_client,
    )

    mocked_switch_order_to_failed = mocker.patch(
        "adobe_vipm.flows.fulfillment.shared.switch_order_to_failed",
    )

    context = Context(
        order=order,
        order_id="order-id",
        agreement_id="agreement-id",
        authorization_id="AUT-1234-4567",
    )
    step = FetchResellerChangeData(is_validation=False)
    step(mock_mpt_client, context, mock_next_step)

    mock_adobe_client.reseller_change_request.assert_called_once()
    mocked_switch_order_to_failed.assert_called_once_with(
        mock_mpt_client,
        context.order,
        ERR_ADOBE_RESSELLER_CHANGE_PREVIEW.to_dict(
            reseller_change_code="88888888",
            error=str(api_error),
        ),
    )
    mock_next_step.assert_not_called()


def test_fetch_reseller_change_data_adobe_api_error_validation_mode(
    mocker,
    order_factory,
    reseller_change_order_parameters_factory,
    mock_next_step,
    mock_mpt_client,
    mock_adobe_client,
):
    order = order_factory(order_parameters=reseller_change_order_parameters_factory())
    api_error = AdobeAPIError(400, {"code": "9999", "message": "Adobe error"})

    mock_adobe_client.reseller_change_request.side_effect = api_error

    mocker.patch(
        "adobe_vipm.flows.helpers.get_adobe_client",
        return_value=mock_adobe_client,
    )

    context = Context(
        order=order,
        order_id="order-id",
        agreement_id="agreement-id",
        authorization_id="AUT-1234-4567",
    )

    step = FetchResellerChangeData(is_validation=True)
    step(mock_mpt_client, context, mock_next_step)

    mock_adobe_client.reseller_change_request.assert_called_once()
    assert context.validation_succeeded is False
    mock_next_step.assert_not_called()


def test_validate_reseller_change_success_when_customer_id_exists(
    mocker,
    order_factory,
    reseller_change_order_parameters_factory,
    mock_next_step,
    mock_mpt_client,
):
    order = order_factory(order_parameters=reseller_change_order_parameters_factory())

    context = Context(
        order=order,
        adobe_customer_id="existing-customer-id",
    )
    step = ValidateResellerChange(is_validation=False)

    step(mock_mpt_client, context, mock_next_step)

    mock_next_step.assert_called_once_with(mock_mpt_client, context)


def test_validate_reseller_change_success_when_validation_passes(
    mocker,
    order_factory,
    reseller_change_order_parameters_factory,
    adobe_reseller_change_preview_factory,
    mock_next_step,
    mock_mpt_client,
):
    order = order_factory(order_parameters=reseller_change_order_parameters_factory())

    adobe_transfer = adobe_reseller_change_preview_factory(
        approval_expiry=(dt.datetime.now(tz=dt.UTC).date() + dt.timedelta(days=5)).isoformat()
    )

    context = Context(order=order)
    context.adobe_transfer = adobe_transfer

    step = ValidateResellerChange(is_validation=False)
    step(mock_mpt_client, context, mock_next_step)
    mock_next_step.assert_called_once_with(mock_mpt_client, context)


def test_validate_reseller_change_expired_code_fulfillment_mode(
    mocker,
    order_factory,
    reseller_change_order_parameters_factory,
    adobe_reseller_change_preview_factory,
    mock_next_step,
    mock_mpt_client,
):
    order = order_factory(order_parameters=reseller_change_order_parameters_factory())

    adobe_transfer = adobe_reseller_change_preview_factory(
        approval_expiry=(dt.datetime.now(tz=dt.UTC).date() - dt.timedelta(days=1)).isoformat()
    )

    context = Context(order=order)
    context.adobe_transfer = adobe_transfer

    mocked_switch_order_to_failed = mocker.patch(
        "adobe_vipm.flows.fulfillment.shared.switch_order_to_failed"
    )

    step = ValidateResellerChange(is_validation=False)

    step(mock_mpt_client, context, mock_next_step)

    mock_next_step.assert_not_called()
    mocked_switch_order_to_failed.assert_called_once()

    call_args = mocked_switch_order_to_failed.call_args
    error_data = call_args[0][2]  # Third argument is error_data
    assert error_data["id"] == ERR_ADOBE_RESSELLER_CHANGE_PREVIEW.id
    assert "Reseller change code has expired" in error_data["message"]


@freeze_time("2024-01-01")
def test_validate_sku_availability_with_valid_3yc_commitment_skips_validation(
    mocker,
    order_factory,
    adobe_customer_factory,
    lines_factory,
    mock_next_step,
    mock_mpt_client,
):
    """Test that validation is skipped when 3YC commitment is valid for more than 365 days."""
    # Mock 3YC commitment that expires in more than 365 days
    commitment = {
        "endDate": "2026-01-01",  # More than 365 days from 2024-01-01
    }

    mocked_get_3yc_commitment = mocker.patch(
        "adobe_vipm.flows.helpers.get_3yc_commitment", return_value=commitment
    )

    # Create order with lines
    lines = lines_factory(
        line_id=1,
        item_id=1,
        external_vendor_id="65304578CA",
        quantity=10,
    )

    order = order_factory(lines=lines)
    adobe_customer = adobe_customer_factory()

    context = Context(
        order=order,
        adobe_customer=adobe_customer,
        new_lines=lines,
        upsize_lines=[],
        downsize_lines=[],
        product_id="PRD-123",
        currency="USD",
    )

    step = ValidateSkuAvailability(is_validation=True)
    step(mock_mpt_client, context, mock_next_step)

    # Should call next_step without doing SKU validation
    mock_next_step.assert_called_once_with(mock_mpt_client, context)
    mocked_get_3yc_commitment.assert_called_once_with(adobe_customer)


@freeze_time("2024-01-01")
def test_validate_sku_availability_with_expired_3yc_commitment_continues_validation(
    mocker,
    order_factory,
    adobe_customer_factory,
    lines_factory,
    mock_next_step,
    mock_mpt_client,
):
    """Test that validation continues when 3YC commitment expires within 365 days."""
    # Mock 3YC commitment that expires in less than 365 days
    commitment = {
        "endDate": "2024-06-01",  # Less than 365 days from 2024-01-01
    }

    mocker.patch("adobe_vipm.flows.helpers.get_3yc_commitment", return_value=commitment)

    mocked_get_adobe_product = mocker.patch(
        "adobe_vipm.flows.helpers.get_adobe_product_by_marketplace_sku",
        return_value=mocker.MagicMock(sku="65304578CA01A12"),
    )

    mocked_get_prices = mocker.patch(
        "adobe_vipm.flows.helpers.get_prices_for_skus",
        return_value={"65304578CA01A12": 637.32},
    )

    lines = lines_factory(
        line_id=1,
        item_id=1,
        external_vendor_id="65304578CA",
        quantity=10,
    )

    order = order_factory(lines=lines)
    adobe_customer = adobe_customer_factory()

    context = Context(
        order=order,
        adobe_customer=adobe_customer,
        new_lines=lines,
        upsize_lines=[],
        downsize_lines=[],
        product_id="PRD-123",
        currency="USD",
    )

    step = ValidateSkuAvailability(is_validation=True)
    step(mock_mpt_client, context, mock_next_step)

    # Should continue with SKU validation
    mocked_get_adobe_product.assert_called_once_with("65304578CA")
    mocked_get_prices.assert_called_once_with("PRD-123", "USD", ["65304578CA01A12"])
    mock_next_step.assert_called_once_with(mock_mpt_client, context)


def test_validate_sku_availability_success_all_skus_available(
    mocker,
    order_factory,
    adobe_customer_factory,
    lines_factory,
    mock_next_step,
    mock_mpt_client,
):
    """Test successful validation when all SKUs are available."""
    mocked_get_3yc_commitment = mocker.patch(
        "adobe_vipm.flows.helpers.get_3yc_commitment", return_value=None
    )

    mocked_get_adobe_product = mocker.patch(
        "adobe_vipm.flows.helpers.get_adobe_product_by_marketplace_sku",
        side_effect=[
            mocker.MagicMock(sku="65304578CA01A12"),
            mocker.MagicMock(sku="77777777CA01A12"),
            mocker.MagicMock(sku="88888888CA01A12"),
        ],
    )

    mocked_get_prices = mocker.patch(
        "adobe_vipm.flows.helpers.get_prices_for_skus",
        return_value={
            "65304578CA01A12": 637.32,
            "77777777CA01A12": 637.32,
            "88888888CA01A12": 637.32,
        },
    )

    # Create order with mixed line types
    new_lines = lines_factory(
        line_id=1,
        item_id=1,
        external_vendor_id="65304578CA",
        quantity=10,
    )
    upsize_lines = lines_factory(
        line_id=2,
        item_id=2,
        external_vendor_id="77777777CA",
        quantity=5,
    )
    downsize_lines = lines_factory(
        line_id=3,
        item_id=3,
        external_vendor_id="88888888CA",
        quantity=3,
    )

    order = order_factory(lines=new_lines + upsize_lines + downsize_lines)
    adobe_customer = adobe_customer_factory()

    context = Context(
        order=order,
        adobe_customer=adobe_customer,
        new_lines=new_lines,
        upsize_lines=upsize_lines,
        downsize_lines=downsize_lines,
        product_id="PRD-123",
        currency="USD",
    )

    step = ValidateSkuAvailability(is_validation=True)
    step(mock_mpt_client, context, mock_next_step)

    mocked_get_3yc_commitment.assert_called_once_with(adobe_customer)
    assert mocked_get_adobe_product.call_count == 3

    mocked_get_prices.assert_called_once_with(
        "PRD-123", "USD", ["65304578CA01A12", "77777777CA01A12", "88888888CA01A12"]
    )
    mock_next_step.assert_called_once_with(mock_mpt_client, context)
    assert context.validation_succeeded is True


def test_validate_sku_availability_missing_skus_validation_mode(
    mocker,
    order_factory,
    adobe_customer_factory,
    lines_factory,
    mock_next_step,
    mock_mpt_client,
):
    """Test validation mode when some SKUs are missing."""
    mocker.patch("adobe_vipm.flows.helpers.get_3yc_commitment", return_value=None)
    mocker.patch(
        "adobe_vipm.flows.helpers.get_adobe_product_by_marketplace_sku",
        side_effect=[
            mocker.MagicMock(sku="65304578CA01A12"),
            mocker.MagicMock(sku="77777777CA01A12"),
        ],
    )
    mocker.patch(
        "adobe_vipm.flows.helpers.get_prices_for_skus",
        return_value={"65304578CA01A12": 637.32},
    )
    mocked_set_order_error = mocker.patch("adobe_vipm.flows.helpers.set_order_error")
    new_lines = lines_factory(
        line_id=1,
        item_id=1,
        external_vendor_id="65304578CA",
        quantity=10,
    )
    upsize_lines = lines_factory(
        line_id=2,
        item_id=2,
        external_vendor_id="77777777CA",
        quantity=5,
    )

    order = order_factory(lines=new_lines + upsize_lines)
    adobe_customer = adobe_customer_factory()

    context = Context(
        order=order,
        adobe_customer=adobe_customer,
        new_lines=new_lines,
        upsize_lines=upsize_lines,
        downsize_lines=[],
        product_id="PRD-123",
        currency="USD",
    )

    step = ValidateSkuAvailability(is_validation=True)
    step(mock_mpt_client, context, mock_next_step)

    mock_next_step.assert_not_called()
    assert context.validation_succeeded is False
    mocked_set_order_error.assert_called_once()


def test_validate_sku_availability_missing_skus_validation_mode_false(
    mocker,
    order_factory,
    adobe_customer_factory,
    lines_factory,
    mock_next_step,
    mock_mpt_client,
):
    """Test validation mode when some SKUs are missing."""
    mocker.patch("adobe_vipm.flows.helpers.get_3yc_commitment", return_value=None)
    mocker.patch(
        "adobe_vipm.flows.helpers.get_adobe_product_by_marketplace_sku",
        side_effect=[
            mocker.MagicMock(sku="65304578CA01A12"),
            mocker.MagicMock(sku="77777777CA01A12"),
        ],
    )
    mocker.patch(
        "adobe_vipm.flows.helpers.get_prices_for_skus",
        return_value={"65304578CA01A12": 637.32},
    )
    mocked_set_order_error = mocker.patch("adobe_vipm.flows.helpers.switch_order_to_failed")
    new_lines = lines_factory(
        line_id=1,
        item_id=1,
        external_vendor_id="65304578CA",
        quantity=10,
    )
    upsize_lines = lines_factory(
        line_id=2,
        item_id=2,
        external_vendor_id="77777777CA",
        quantity=5,
    )

    order = order_factory(lines=new_lines + upsize_lines)
    adobe_customer = adobe_customer_factory()

    context = Context(
        order=order,
        adobe_customer=adobe_customer,
        new_lines=new_lines,
        upsize_lines=upsize_lines,
        downsize_lines=[],
        product_id="PRD-123",
        currency="USD",
    )

    step = ValidateSkuAvailability(is_validation=False)
    step(mock_mpt_client, context, mock_next_step)

    mock_next_step.assert_not_called()
    assert context.validation_succeeded is False
    mocked_set_order_error.assert_called_once()


def test_validate_sku_availability_empty_sku_lists(
    mocker,
    order_factory,
    adobe_customer_factory,
    mock_next_step,
    mock_mpt_client,
):
    """Test validation with empty SKU lists."""
    mocker.patch("adobe_vipm.flows.helpers.get_3yc_commitment", return_value=None)

    mocked_get_prices = mocker.patch(
        "adobe_vipm.flows.helpers.get_prices_for_skus", return_value={}
    )

    order = order_factory(lines=[])
    adobe_customer = adobe_customer_factory()

    context = Context(
        order=order,
        adobe_customer=adobe_customer,
        new_lines=[],
        upsize_lines=[],
        downsize_lines=[],
        product_id="PRD-123",
        currency="USD",
    )

    step = ValidateSkuAvailability(is_validation=True)
    step(mock_mpt_client, context, mock_next_step)

    mock_next_step.assert_called_once_with(mock_mpt_client, context)
    mocked_get_prices.assert_called_once_with("PRD-123", "USD", [])
