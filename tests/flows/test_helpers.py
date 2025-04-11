import copy
from datetime import date
from urllib.parse import urljoin

import pytest
from freezegun import freeze_time

from adobe_vipm.adobe.constants import STATUS_INTERNAL_SERVER_ERROR
from adobe_vipm.adobe.errors import AdobeError
from adobe_vipm.flows.constants import (
    PARAM_ADDRESS,
    PARAM_COMPANY_NAME,
    PARAM_CONTACT,
    PARAM_RETRY_COUNT,
)
from adobe_vipm.flows.context import Context
from adobe_vipm.flows.helpers import (
    PrepareCustomerData,
    SetupContext,
)
from adobe_vipm.flows.utils import get_customer_data


@freeze_time("2024-01-01")
def test_setup_context_step(
    mocker, agreement, order_factory, lines_factory, fulfillment_parameters_factory
):
    """
    Tests the order processing initialization step without the retrival of
    the Adobe customer.
    """
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
    """
    Tests the order processing initialization step with the retrival of
    the Adobe customer.
    """
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
    fulfillment_parameters.append(
        {
            "externalId": PARAM_RETRY_COUNT,
            "value": "1",
        }
    )
    order = order_factory(
        fulfillment_parameters=fulfillment_parameters,
        external_ids={"vendor": "adobe-order-id"},
    )

    mocked_client = mocker.MagicMock()
    mocked_next_step = mocker.MagicMock()

    context = Context(order=order)

    step = SetupContext()
    step(mocked_client, context, mocked_next_step)

    assert context.due_date == date(2025, 1, 31)
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
    """
    Tests the order processing initialization step when the Adobe get customer
    API operation receives an error.
    """
    customer_id = "adobe-customer-id"
    adobe_client, _, _ = adobe_client_factory()
    authorization_uk = adobe_authorizations_file["authorizations"][0][
        "authorization_uk"
    ]
    adobe_api_error = adobe_api_error_factory(
        code=STATUS_INTERNAL_SERVER_ERROR,
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

    assert (
        str(exc_info.value)
        == f"{adobe_api_error["code"]} - {adobe_api_error["message"]}"
    )
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


def test_prepare_customer_data_step_no_company_name(
    mocker, order_factory, customer_data
):
    order = order_factory()

    no_company_customer_data = copy.copy(customer_data)
    del no_company_customer_data[PARAM_COMPANY_NAME]

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
        context.customer_data[PARAM_COMPANY_NAME]
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
    del no_address_customer_data[PARAM_ADDRESS]

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
    assert context.customer_data[PARAM_ADDRESS] == {
        "country": context.order["agreement"]["licensee"]["address"]["country"],
        "state": context.order["agreement"]["licensee"]["address"]["state"],
        "city": context.order["agreement"]["licensee"]["address"]["city"],
        "addressLine1": context.order["agreement"]["licensee"]["address"][
            "addressLine1"
        ],
        "addressLine2": context.order["agreement"]["licensee"]["address"].get(
            "addressLine2"
        ),
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
    del no_contact_customer_data[PARAM_CONTACT]

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
    assert context.customer_data[PARAM_CONTACT] == {
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
