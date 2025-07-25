import copy
import datetime as dt
from urllib.parse import urljoin

import pytest
from freezegun import freeze_time

from adobe_vipm.adobe.constants import (
    ORDER_TYPE_NEW,
    ORDER_TYPE_PREVIEW,
    AdobeStatus,
    ThreeYearCommitmentStatus,
)
from adobe_vipm.adobe.errors import AdobeError
from adobe_vipm.flows.constants import Param
from adobe_vipm.flows.context import Context
from adobe_vipm.flows.helpers import (
    PrepareCustomerData,
    SetupContext,
    UpdatePrices,
    Validate3YCCommitment,
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

    mocked_adobe_client = mocker.MagicMock()
    mocked_adobe_client.get_customer.return_value = adobe_customer

    mocker.patch(
        "adobe_vipm.flows.helpers.get_adobe_client",
        return_value=mocked_adobe_client,
    )

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
    mocked_get_agreement.assert_called_once_with(
        mocked_client,
        order["agreement"]["id"],
    )
    mocked_get_licensee.assert_called_once_with(
        mocked_client,
        order["agreement"]["licensee"]["id"],
    )
    mocked_next_step.assert_called_once_with(mocked_client, context)


@freeze_time("2025-01-01")
def test_setup_context_step_when_retry_count_was_not_zero(
    mocker,
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

    mocked_adobe_client = mocker.MagicMock()
    mocked_adobe_client.get_customer.return_value = adobe_customer

    mocker.patch(
        "adobe_vipm.flows.helpers.get_adobe_client",
        return_value=mocked_adobe_client,
    )

    fulfillment_parameters = fulfillment_parameters_factory(
        customer_id="adobe-customer-id",
    )
    fulfillment_parameters.append({
        "externalId": Param.RETRY_COUNT.value,
        "value": "1",
    })
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
    mocked_get_agreement.assert_called_once_with(
        mocked_client,
        order["agreement"]["id"],
    )
    mocked_get_licensee.assert_called_once_with(
        mocked_client,
        order["agreement"]["licensee"]["id"],
    )
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


def test_prepare_customer_data_step(mocker, order_factory, customer_data):
    order = order_factory()

    mocked_update_order = mocker.patch(
        "adobe_vipm.flows.helpers.update_order",
    )
    mocked_client = mocker.MagicMock()
    mocked_next_step = mocker.MagicMock()
    context = Context(order=order, customer_data=customer_data)

    step = PrepareCustomerData()
    step(mocked_client, context, mocked_next_step)

    mocked_update_order.assert_not_called()
    mocked_next_step.assert_called_once_with(mocked_client, context)


def test_prepare_customer_data_step_no_company_name(mocker, order_factory, customer_data):
    order = order_factory()

    no_company_customer_data = copy.copy(customer_data)
    del no_company_customer_data[Param.COMPANY_NAME.value]

    mocked_update_order = mocker.patch(
        "adobe_vipm.flows.helpers.update_order",
    )
    mocked_client = mocker.MagicMock()
    mocked_next_step = mocker.MagicMock()
    context = Context(
        order=order,
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


def test_prepare_customer_data_step_no_address(mocker, order_factory, customer_data):
    order = order_factory()

    no_address_customer_data = copy.copy(customer_data)
    del no_address_customer_data[Param.ADDRESS.value]

    mocked_update_order = mocker.patch(
        "adobe_vipm.flows.helpers.update_order",
    )
    mocked_client = mocker.MagicMock()
    mocked_next_step = mocker.MagicMock()
    context = Context(
        order=order,
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


def test_prepare_customer_data_step_no_contact(mocker, order_factory, customer_data):
    order = order_factory()

    no_contact_customer_data = copy.copy(customer_data)
    del no_contact_customer_data[Param.CONTACT.value]

    mocked_update_order = mocker.patch(
        "adobe_vipm.flows.helpers.update_order",
    )
    mocked_client = mocker.MagicMock()
    mocked_next_step = mocker.MagicMock()
    context = Context(
        order=order,
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


def test_update_prices_step_no_orders(mocker, order_factory):
    order = order_factory()
    mocked_client = mocker.MagicMock()
    mocked_next_step = mocker.MagicMock()

    context = Context(
        order=order,
        order_id=order["id"],
        adobe_new_order=None,
        adobe_preview_order=None,
    )

    step = UpdatePrices()
    step(mocked_client, context, mocked_next_step)

    mocked_next_step.assert_called_once_with(mocked_client, context)


def test_update_prices_step_with_new_order(mocker, order_factory, adobe_order_factory):
    order = order_factory()
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
        adobe_new_order=adobe_order,
    )

    step = UpdatePrices()
    step(mocked_client, context, mocked_next_step)

    mocked_get_prices.assert_called_once_with(
        context.product_id,
        context.currency,
        [sku],
    )
    mocked_update_order.assert_called_once_with(
        mocked_client,
        context.order_id,
        lines=[
            {
                "id": order["lines"][0]["id"],
                "price": {"unitPP": 121.36},
            },
        ],
    )
    mocked_next_step.assert_called_once_with(mocked_client, context)


def test_update_prices_step_with_preview_order(mocker, order_factory, adobe_order_factory):
    order = order_factory()
    adobe_order = adobe_order_factory(order_type=ORDER_TYPE_PREVIEW)
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
        adobe_preview_order=adobe_order,
    )

    step = UpdatePrices()
    step(mocked_client, context, mocked_next_step)

    mocked_get_prices.assert_called_once_with(
        context.product_id,
        context.currency,
        [sku],
    )
    mocked_update_order.assert_called_once_with(
        mocked_client,
        context.order_id,
        lines=[
            {
                "id": order["lines"][0]["id"],
                "price": {"unitPP": 121.36},
            },
        ],
    )
    mocked_next_step.assert_called_once_with(mocked_client, context)


@freeze_time("2024-11-09")
def test_update_prices_step_with_3yc_commitment(
    mocker,
    order_factory,
    adobe_order_factory,
    adobe_customer_factory,
    adobe_commitment_factory,
):
    order = order_factory()
    commitment = adobe_commitment_factory(
        status=ThreeYearCommitmentStatus.COMMITTED.value,
        start_date="2024-01-01",
        end_date="2025-01-01",
    )
    adobe_customer = adobe_customer_factory(
        commitment=commitment,
        commitment_request=commitment,
    )
    adobe_order = adobe_order_factory(order_type=ORDER_TYPE_NEW)
    sku = adobe_order["lineItems"][0]["offerId"]

    mocked_get_prices = mocker.patch(
        "adobe_vipm.flows.helpers.get_prices_for_3yc_skus",
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
        adobe_customer=adobe_customer,
        adobe_new_order=adobe_order,
    )
    step = UpdatePrices()
    step(mocked_client, context, mocked_next_step)

    mocked_get_prices.assert_called_once_with(
        context.product_id,
        context.currency,
        dt.date.fromisoformat(commitment["startDate"]),
        [sku],
    )
    mocked_update_order.assert_called_once_with(
        mocked_client,
        context.order_id,
        lines=[
            {
                "id": order["lines"][0]["id"],
                "price": {"unitPP": 121.36},
            },
        ],
    )
    mocked_next_step.assert_called_once_with(mocked_client, context)


def test_update_prices_step_with_expired_3yc_commitment(
    mocker,
    order_factory,
    adobe_order_factory,
    adobe_customer_factory,
    adobe_commitment_factory,
):
    order = order_factory()
    commitment = adobe_commitment_factory(
        status=ThreeYearCommitmentStatus.COMMITTED.value,
        start_date="2023-01-01",
        end_date="2024-01-01",
    )
    adobe_customer = adobe_customer_factory(commitment=commitment)
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
        adobe_customer=adobe_customer,
        adobe_new_order=adobe_order,
    )

    step = UpdatePrices()
    step(mocked_client, context, mocked_next_step)

    mocked_get_prices.assert_called_once_with(
        context.product_id,
        context.currency,
        [sku],
    )
    mocked_update_order.assert_called_once_with(
        mocked_client,
        context.order_id,
        lines=[
            {
                "id": order["lines"][0]["id"],
                "price": {"unitPP": 121.36},
            },
        ],
    )
    mocked_next_step.assert_called_once_with(mocked_client, context)


def test_update_prices_step_with_multiple_lines(
    mocker,
    order_factory,
    lines_factory,
    adobe_order_factory,
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
        adobe_new_order=adobe_order,
    )

    step = UpdatePrices()
    step(mocked_client, context, mocked_next_step)

    mocked_get_prices.assert_called_once_with(
        context.product_id,
        context.currency,
        [sku],
    )
    mocked_update_order.assert_called_once_with(
        mocked_client,
        context.order_id,
        lines=[
            {
                "id": line_1["id"],
                "price": {"unitPP": 121.36},
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

    adobe_customer = adobe_customer_factory(
        commitment=commitment,
        commitment_request=commitment,
    )

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

    order = order_factory(
        lines=lines,
    )

    context = Context(
        order=order,
        adobe_customer=adobe_customer,
        adobe_customer_id="test-customer-id",
        upsize_lines=lines,
    )

    mocked_next_step = mocker.MagicMock()
    mocked_client = mocker.MagicMock()

    mocked_adobe_client = mocker.MagicMock()

    mocker.patch(
        "adobe_vipm.flows.helpers.get_adobe_client",
        return_value=mocked_adobe_client,
    )

    mocker.patch(
        "adobe_vipm.flows.helpers.get_adobe_product_by_marketplace_sku",
        side_effect=mock_get_sku_adobe_mapping_model.from_id,
    )

    step = Validate3YCCommitment()
    step(mocked_client, context, mocked_next_step)

    mocked_next_step.assert_not_called()


def test_validate_3yc_commitment_expired_status(
    mocker,
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

    adobe_customer = adobe_customer_factory(
        commitment=commitment,
        commitment_request=commitment,
    )

    subscriptions = {
        "items": [
            adobe_subscription_factory(
                offer_id="65304578CA",
                renewal_quantity=15,
                autorenewal_enabled=True,
            )
        ]
    }

    mocked_adobe_client = mocker.MagicMock()
    mocked_adobe_client.get_subscriptions.return_value = subscriptions
    mocker.patch(
        "adobe_vipm.flows.helpers.get_adobe_client",
        return_value=mocked_adobe_client,
    )

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

    adobe_customer = adobe_customer_factory(
        commitment=commitment,
        commitment_request=commitment,
    )

    subscriptions = {
        "items": [
            adobe_subscription_factory(
                offer_id="77777777CA",
                renewal_quantity=8,
                autorenewal_enabled=True,
            ),
        ]
    }

    mocked_adobe_client = mocker.MagicMock()
    mocked_adobe_client.get_subscriptions.return_value = subscriptions
    mocker.patch(
        "adobe_vipm.flows.helpers.get_adobe_client",
        return_value=mocked_adobe_client,
    )
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
    order = order_factory(
        lines=lines,
    )

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

    adobe_customer = adobe_customer_factory(
        commitment=commitment,
        commitment_request=commitment,
    )

    subscriptions = {
        "items": [
            adobe_subscription_factory(
                offer_id="77777777CA",
                renewal_quantity=8,
                autorenewal_enabled=True,
            ),
        ]
    }

    mocked_adobe_client = mocker.MagicMock()
    mocked_adobe_client.get_subscriptions.return_value = subscriptions
    mocker.patch(
        "adobe_vipm.flows.helpers.get_adobe_client",
        return_value=mocked_adobe_client,
    )
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
    order = order_factory(
        lines=lines,
    )

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

    adobe_customer = adobe_customer_factory(
        commitment=commitment,
        commitment_request=commitment,
    )

    subscriptions = {
        "items": [
            adobe_subscription_factory(
                offer_id="65304578CA",
                renewal_quantity=15,
                autorenewal_enabled=True,
            )
        ]
    }

    mocked_adobe_client = mocker.MagicMock()
    mocked_adobe_client.get_subscriptions.return_value = subscriptions
    mocker.patch(
        "adobe_vipm.flows.helpers.get_adobe_client",
        return_value=mocked_adobe_client,
    )

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

    adobe_customer = adobe_customer_factory(
        commitment=commitment,
        commitment_request=commitment,
    )

    subscriptions = {
        "items": [
            adobe_subscription_factory(
                offer_id="77777777CA",
                renewal_quantity=15,
                autorenewal_enabled=True,
            )
        ]
    }

    mocked_adobe_client = mocker.MagicMock()
    mocked_adobe_client.get_subscriptions.return_value = subscriptions
    mocker.patch(
        "adobe_vipm.flows.helpers.get_adobe_client",
        return_value=mocked_adobe_client,
    )

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

    adobe_customer = adobe_customer_factory(
        commitment=commitment,
        commitment_request=commitment,
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
                renewal_quantity=15,
                autorenewal_enabled=True,
            ),
        ]
    }

    mocked_adobe_client = mocker.MagicMock()
    mocked_adobe_client.get_subscriptions.return_value = subscriptions
    mocker.patch(
        "adobe_vipm.flows.helpers.get_adobe_client",
        return_value=mocked_adobe_client,
    )

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
        commitment=commitment,
        commitment_request=commitment,
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

    mocked_adobe_client = mocker.MagicMock()
    mocked_adobe_client.get_subscriptions.return_value = subscriptions
    mocker.patch(
        "adobe_vipm.flows.helpers.get_adobe_client",
        return_value=mocked_adobe_client,
    )

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

    order = order_factory(
        lines=lines,
    )

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
    order_factory,
    adobe_customer_factory,
    adobe_commitment_factory,
    adobe_subscription_factory,
    mock_get_sku_adobe_mapping_model,
):
    mocked_switch_order_to_failed = mocker.patch("adobe_vipm.flows.helpers.switch_order_to_failed")
    mocked_set_order_error = mocker.patch("adobe_vipm.flows.helpers.set_order_error")

    adobe_customer = adobe_customer_factory(
        commitment=None,
        commitment_request=None,
    )

    subscriptions = {
        "items": [
            adobe_subscription_factory(
                offer_id="65304578CA",
                renewal_quantity=15,
                autorenewal_enabled=True,
            )
        ]
    }

    mocked_adobe_client = mocker.MagicMock()
    mocked_adobe_client.get_subscriptions.return_value = subscriptions
    mocker.patch(
        "adobe_vipm.flows.helpers.get_adobe_client",
        return_value=mocked_adobe_client,
    )

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
    order_factory,
    adobe_customer_factory,
    adobe_subscription_factory,
    mock_get_sku_adobe_mapping_model,
):
    adobe_customer = adobe_customer_factory(
        commitment=None,
        commitment_request=None,
    )

    subscriptions = {
        "items": [
            adobe_subscription_factory(
                offer_id="65304578CA",
                renewal_quantity=15,
                autorenewal_enabled=True,
            )
        ]
    }

    mocked_adobe_client = mocker.MagicMock()
    mocked_adobe_client.get_subscriptions.return_value = subscriptions
    mocker.patch(
        "adobe_vipm.flows.helpers.get_adobe_client",
        return_value=mocked_adobe_client,
    )

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

    adobe_customer = adobe_customer_factory(
        commitment=commitment,
        commitment_request=commitment,
    )

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

    order = order_factory(
        lines=lines,
    )

    context = Context(
        order=order,
        adobe_customer=adobe_customer,
        adobe_customer_id="test-customer-id",
        upsize_lines=lines,
    )

    mocked_next_step = mocker.MagicMock()
    mocked_client = mocker.MagicMock()

    mocked_adobe_client = mocker.MagicMock()

    mocker.patch(
        "adobe_vipm.flows.helpers.get_adobe_client",
        return_value=mocked_adobe_client,
    )

    mocker.patch(
        "adobe_vipm.flows.helpers.get_adobe_product_by_marketplace_sku",
        side_effect=mock_get_sku_adobe_mapping_model.from_id,
    )

    step = Validate3YCCommitment()
    step(mocked_client, context, mocked_next_step)

    mocked_next_step.assert_called_once()


def test_validate_3yc_commitment_date_without_coterm_date(
    mocker,
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
        commitment=commitment,
        commitment_request=commitment,
        coterm_date=None,
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

    mocked_adobe_client = mocker.MagicMock()
    mocked_adobe_client.get_subscriptions.return_value = subscriptions
    mocker.patch(
        "adobe_vipm.flows.helpers.get_adobe_client",
        return_value=mocked_adobe_client,
    )

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

    order = order_factory(
        lines=lines,
    )

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
