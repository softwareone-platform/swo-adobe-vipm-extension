import copy

from adobe_vipm.flows.constants import (
    PARAM_ADDRESS,
    PARAM_COMPANY_NAME,
    PARAM_CONTACT,
)
from adobe_vipm.flows.context import Context
from adobe_vipm.flows.helpers import (
    PrepareCustomerData,
    SetupContext,
)
from adobe_vipm.flows.utils import get_customer_data


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
            retry_count="12",
        ),
    )

    mocked_client = mocker.MagicMock()
    mocked_next_step = mocker.MagicMock()

    context = Context(order=order)

    step = SetupContext()
    step(mocked_client, context, mocked_next_step)

    assert context.order["agreement"] == agreement
    assert context.order["agreement"]["licensee"] == agreement["licensee"]
    assert context.current_attempt == 12
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
    assert context.current_attempt == 0
    assert context.downsize_lines == []
    assert context.upsize_lines == order["lines"]
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
