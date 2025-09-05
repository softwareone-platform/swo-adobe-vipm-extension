import datetime as dt

import pytest
from freezegun import freeze_time

from adobe_vipm.adobe.constants import (
    ORDER_STATUS_DESCRIPTION,
    ORDER_TYPE_NEW,
    ORDER_TYPE_PREVIEW,
    AdobeStatus,
)
from adobe_vipm.adobe.dataclasses import ReturnableOrderInfo
from adobe_vipm.adobe.errors import AdobeAPIError
from adobe_vipm.flows.constants import (
    ERR_DUE_DATE_REACHED,
    ERR_DUPLICATED_ITEMS,
    ERR_EXISTING_ITEMS,
    ERR_UNEXPECTED_ADOBE_ERROR_STATUS,
    ERR_UNRECOVERABLE_ADOBE_ORDER_STATUS,
    ERR_VIPM_UNHANDLED_EXCEPTION,
    MPT_ORDER_STATUS_COMPLETED,
    MPT_ORDER_STATUS_PROCESSING,
    TEMPLATE_CONFIGURATION_AUTORENEWAL_DISABLE,
    TEMPLATE_CONFIGURATION_AUTORENEWAL_ENABLE,
    Param,
)
from adobe_vipm.flows.context import Context
from adobe_vipm.flows.fulfillment.shared import (
    CompleteOrder,
    CreateOrUpdateSubscriptions,
    GetPreviewOrder,
    GetReturnOrders,
    SetOrUpdateCotermDate,
    SetupDueDate,
    StartOrderProcessing,
    SubmitNewOrder,
    SubmitReturnOrders,
    SyncAgreement,
    ValidateDuplicateLines,
    ValidateRenewalWindow,
    send_gc_mpt_notification,
    send_mpt_notification,
    set_customer_coterm_date_if_null,
    start_processing_attempt,
)
from adobe_vipm.flows.utils import (
    get_adobe_order_id,
    get_coterm_date,
    get_due_date,
    set_coterm_date,
)
from adobe_vipm.flows.utils.parameter import get_fulfillment_parameter


@pytest.fixture(autouse=True)
def mocked_send_mpt_notification(mocker):
    return mocker.patch("adobe_vipm.flows.fulfillment.shared.send_mpt_notification", spec=True)


@pytest.mark.parametrize(
    ("status", "subject"),
    [
        (
            "Processing",
            "Order status update ORD-1234 for A buyer",
        ),
        (
            "Querying",
            "This order need your attention ORD-1234 for A buyer",
        ),
        (
            "Completed",
            "Order status update ORD-1234 for A buyer",
        ),
        (
            "Failed",
            "Order status update ORD-1234 for A buyer",
        ),
    ],
)
def test_send_mpt_notification(mocker, settings, order_factory, mock_mpt_client, status, subject):
    mocked_get_rendered_template = mocker.patch(
        "adobe_vipm.flows.fulfillment.shared.get_rendered_template",
        return_value="rendered-template",
    )

    mocked_mpt_notify = mocker.patch("adobe_vipm.flows.fulfillment.shared.mpt_notify")

    order = order_factory(order_id="ORD-1234", status=status)

    send_mpt_notification(mock_mpt_client, order)
    mocked_get_rendered_template.assert_called_once_with(mock_mpt_client, order["id"])

    mocked_mpt_notify.assert_called_once_with(
        mock_mpt_client,
        order["agreement"]["licensee"]["account"]["id"],
        order["agreement"]["buyer"]["id"],
        subject,
        "notification",
        {
            "order": order,
            "activation_template": "<p>rendered-template</p>\n",
            "api_base_url": settings.MPT_API_BASE_URL,
            "portal_base_url": settings.MPT_PORTAL_BASE_URL,
        },
    )


@freeze_time("2025-01-01")
def test_start_processing_attempt_first_attempt(
    mocker, settings, order_factory, fulfillment_parameters_factory, mocked_send_mpt_notification
):
    order = order_factory()
    updated_order = order_factory(
        fulfillment_parameters=fulfillment_parameters_factory(
            due_date="2025-01-31",
        ),
    )
    mocked_update = mocker.patch(
        "adobe_vipm.flows.fulfillment.shared.update_order",
        return_value=updated_order,
    )

    mocked_client = mocker.MagicMock()

    start_processing_attempt(mocked_client, order)

    mocked_send_mpt_notification.assert_called_once_with(mocked_client, updated_order)
    mocked_update.assert_called_once_with(
        mocked_client,
        updated_order["id"],
        parameters=updated_order["parameters"],
    )


@freeze_time("2025-01-01")
def test_start_processing_attempt_other_attempts(
    mocker, order_factory, fulfillment_parameters_factory, mocked_send_mpt_notification
):
    mocked_client = mocker.MagicMock()

    order = order_factory(
        fulfillment_parameters=fulfillment_parameters_factory(
            due_date="2024-01-01",
        )
    )

    start_processing_attempt(mocked_client, order)

    mocked_send_mpt_notification.assert_not_called()


def test_set_customer_coterm_date_if_null(
    mocker, order_factory, adobe_customer_factory, fulfillment_parameters_factory
):
    mocked_mpt_client = mocker.MagicMock()
    mocked_adobe_client = mocker.MagicMock()
    customer = adobe_customer_factory()
    mocked_adobe_client.get_customer.return_value = customer
    mocked_update_order = mocker.patch(
        "adobe_vipm.flows.fulfillment.shared.update_order",
    )
    order = order_factory()
    order = set_customer_coterm_date_if_null(mocked_mpt_client, mocked_adobe_client, order)
    assert get_coterm_date(order) == customer["cotermDate"]
    mocked_update_order.assert_called_once_with(
        mocked_mpt_client,
        order["id"],
        parameters={
            "ordering": order["parameters"]["ordering"],
            "fulfillment": fulfillment_parameters_factory(
                coterm_date=customer["cotermDate"],
            ),
        },
    )


def test_set_customer_coterm_date_if_null_already_set(
    mocker, order_factory, fulfillment_parameters_factory
):
    mocked_mpt_client = mocker.MagicMock()
    mocked_adobe_client = mocker.MagicMock()
    mocked_update_order = mocker.patch(
        "adobe_vipm.flows.fulfillment.shared.update_order",
    )
    order = order_factory(
        fulfillment_parameters=fulfillment_parameters_factory(coterm_date="whatever")
    )
    assert set_customer_coterm_date_if_null(mocked_mpt_client, mocked_adobe_client, order) == order

    mocked_update_order.assert_not_called()
    mocked_adobe_client.get_customer_assert_not_called()


@freeze_time("2024-01-01")
def test_setup_due_date_for_first_time(
    mocker,
    order_factory,
):
    order = order_factory()
    mocked_update_order = mocker.patch("adobe_vipm.flows.fulfillment.shared.update_order")

    mocked_client = mocker.MagicMock()
    mocked_next_step = mocker.MagicMock()

    context = Context(order=order, order_id=order["id"])
    step = SetupDueDate()

    assert get_due_date(order) is None

    step(mocked_client, context, mocked_next_step)

    assert get_due_date(context.order) == dt.date(2024, 1, 31)
    mocked_update_order.assert_called_once_with(
        mocked_client,
        context.order_id,
        parameters=context.order["parameters"],
    )
    mocked_next_step.assert_called_once_with(mocked_client, context)


@freeze_time("2025-01-01")
def test_increment_attempts_counter_step_max_reached(
    mocker,
    settings,
    order_factory,
    fulfillment_parameters_factory,
):
    settings.EXTENSION_CONFIG = {"DUE_DATE_DAYS": "30"}
    order = order_factory(
        fulfillment_parameters=fulfillment_parameters_factory(
            due_date="2024-06-01",
        ),
    )
    mocked_fail = mocker.patch("adobe_vipm.flows.fulfillment.shared.switch_order_to_failed")
    mocked_client = mocker.MagicMock()
    mocked_next_step = mocker.MagicMock()

    context = Context(order=order, order_id=order["id"])
    step = SetupDueDate()

    step(mocked_client, context, mocked_next_step)

    mocked_fail.assert_called_once_with(
        mocked_client,
        context.order,
        ERR_DUE_DATE_REACHED.to_dict(due_date="2024-06-01"),
    )
    mocked_next_step.assert_not_called()


@freeze_time("2025-01-01")
def test_setup_due_date_when_parameter_is_missed(
    mocker,
    settings,
    order_factory,
    fulfillment_parameters_factory,
):
    settings.EXTENSION_CONFIG = {"DUE_DATE_DAYS": "30"}
    fulfillment_parameters = fulfillment_parameters_factory()
    fulfillment_parameters = list(
        filter(
            lambda p: p["externalId"] != Param.DUE_DATE.value,
            fulfillment_parameters,
        )
    )
    order = order_factory(
        fulfillment_parameters=fulfillment_parameters,
    )
    mocked_update_order = mocker.patch("adobe_vipm.flows.fulfillment.shared.update_order")

    mocked_client = mocker.MagicMock()
    mocked_next_step = mocker.MagicMock()

    context = Context(order=order, order_id=order["id"])
    step = SetupDueDate()

    assert get_due_date(order) is None

    step(mocked_client, context, mocked_next_step)

    assert get_due_date(context.order) == dt.date(2025, 1, 31)
    mocked_update_order.assert_called_once_with(
        mocked_client,
        context.order_id,
        parameters=context.order["parameters"],
    )
    mocked_next_step.assert_called_once_with(mocked_client, context)


def test_start_order_processing_step(mocker, order_factory, mocked_send_mpt_notification):
    mocked_get_template = mocker.patch(
        "adobe_vipm.flows.fulfillment.shared.get_product_template_or_default",
        return_value={"id": "TPL-1234"},
    )
    mocked_update_order = mocker.patch("adobe_vipm.flows.fulfillment.shared.update_order")
    mocked_client = mocker.MagicMock()
    mocked_next_step = mocker.MagicMock()
    order = order_factory()
    context = Context(order=order, order_id=order["id"])

    assert "template" not in context.order

    step = StartOrderProcessing("my template")
    step(mocked_client, context, mocked_next_step)

    assert context.order["template"] == {"id": "TPL-1234"}
    mocked_get_template.assert_called_once_with(
        mocked_client,
        context.order["agreement"]["product"]["id"],
        MPT_ORDER_STATUS_PROCESSING,
        "my template",
    )
    mocked_update_order.assert_called_once_with(
        mocked_client,
        context.order["id"],
        template={"id": "TPL-1234"},
    )
    mocked_send_mpt_notification.assert_called_once_with(mocked_client, context.order)
    mocked_next_step.assert_called_once_with(mocked_client, context)


@pytest.mark.parametrize(
    ("auto_renew", "expected_template"),
    [
        (True, TEMPLATE_CONFIGURATION_AUTORENEWAL_ENABLE),
        (False, TEMPLATE_CONFIGURATION_AUTORENEWAL_DISABLE),
    ],
)
def test_configuration_start_order_processing_selects_template(
    mocker, order_factory, auto_renew, expected_template
):
    order = order_factory(subscriptions=[{"autoRenew": auto_renew}])
    context = Context(order=order, order_id=order["id"])
    mocked_client = mocker.MagicMock()
    mocked_next_step = mocker.MagicMock()

    mocked_get_template = mocker.patch(
        "adobe_vipm.flows.fulfillment.shared.get_product_template_or_default",
        return_value={"id": "TPL-1234"},
    )
    mocked_update_order = mocker.patch("adobe_vipm.flows.fulfillment.shared.update_order")

    step = StartOrderProcessing(expected_template)
    step(mocked_client, context, mocked_next_step)

    mocked_get_template.assert_called_once_with(
        mocked_client,
        context.order["agreement"]["product"]["id"],
        "Processing",
        expected_template,
    )
    mocked_update_order.assert_called_once_with(
        mocked_client,
        context.order_id,
        template={"id": "TPL-1234"},
    )
    assert context.order["template"] == {"id": "TPL-1234"}
    mocked_next_step.assert_called_once_with(mocked_client, context)


def test_set_processing_template_step_already_set_not_first_attempt(
    mocker,
    order_factory,
    fulfillment_parameters_factory,
    mocked_send_mpt_notification,
):
    mocked_get_template = mocker.patch(
        "adobe_vipm.flows.fulfillment.shared.get_product_template_or_default",
        return_value={"id": "TPL-1234"},
    )
    mocked_update_order = mocker.patch("adobe_vipm.flows.fulfillment.shared.update_order")
    mocked_client = mocker.MagicMock()
    mocked_next_step = mocker.MagicMock()

    order = order_factory(
        template={"id": "TPL-1234"},
        fulfillment_parameters=fulfillment_parameters_factory(
            due_date="2025-01-01",
        ),
    )

    context = Context(
        order=order,
        due_date=dt.date(2025, 1, 1),
    )

    step = StartOrderProcessing("my template")
    step(mocked_client, context, mocked_next_step)

    mocked_get_template.assert_called_once_with(
        mocked_client,
        context.order["agreement"]["product"]["id"],
        MPT_ORDER_STATUS_PROCESSING,
        "my template",
    )
    mocked_update_order.assert_not_called()
    mocked_send_mpt_notification.assert_not_called()
    mocked_next_step.assert_called_once_with(mocked_client, context)


@freeze_time("2024-05-06")
def test_set_processing_template_to_delayed_in_renewal_win(
    mocker, order_factory, fulfillment_parameters_factory
):
    mocked_get_template = mocker.patch(
        "adobe_vipm.flows.fulfillment.shared.get_product_template_or_default",
        return_value={"id": "TPL-5678"},
    )
    mocked_update_order = mocker.patch("adobe_vipm.flows.fulfillment.shared.update_order")
    mocked_client = mocker.MagicMock()
    mocked_next_step = mocker.MagicMock()

    order = order_factory(
        fulfillment_parameters=fulfillment_parameters_factory(coterm_date="2024-05-08")
    )

    context = Context(
        order=order,
        order_id=order["id"],
        product_id=order["agreement"]["product"]["id"],
        due_date=dt.date(2025, 1, 1),
    )

    assert "template" not in context.order

    step = StartOrderProcessing("my template")
    step(mocked_client, context, mocked_next_step)

    assert context.order["template"] == {"id": "TPL-5678"}

    mocked_get_template.assert_called_once_with(
        mocked_client,
        context.product_id,
        MPT_ORDER_STATUS_PROCESSING,
        "my template",
    )
    mocked_update_order.assert_called_once_with(
        mocked_client,
        context.order_id,
        template={"id": "TPL-5678"},
    )
    mocked_next_step.assert_called_once_with(mocked_client, context)


@pytest.mark.parametrize(
    "coterm_date",
    [
        "2026-01-01",
        "2024-12-31",
        None,
    ],
)
def test_set_or_update_coterm_date_step(
    mocker,
    order_factory,
    adobe_customer_factory,
    coterm_date,
):
    mocked_update = mocker.patch("adobe_vipm.flows.fulfillment.shared.update_order")
    customer = adobe_customer_factory(coterm_date="2025-01-01")
    order = order_factory()
    order = set_coterm_date(order, coterm_date)

    context = Context(
        order=order,
        order_id=order["id"],
        adobe_customer_id=customer["customerId"],
        adobe_customer=customer,
    )

    mocked_client = mocker.MagicMock()
    mocked_next_step = mocker.MagicMock()

    step = SetOrUpdateCotermDate()

    step(mocked_client, context, mocked_next_step)

    mocked_update.assert_called_once_with(
        mocked_client,
        context.order_id,
        parameters=context.order["parameters"],
    )
    assert get_coterm_date(context.order) == "2025-01-01"
    mocked_next_step.assert_called_once_with(mocked_client, context)


def test_set_or_update_without_coterm_date(
    mocker,
    order_factory,
    adobe_customer_factory,
):
    mocked_update = mocker.patch("adobe_vipm.flows.fulfillment.shared.update_order")
    customer = adobe_customer_factory(coterm_date=None)
    order = order_factory()

    context = Context(
        order=order,
        order_id=order["id"],
        adobe_customer_id=customer["customerId"],
        adobe_customer=customer,
    )

    mocked_client = mocker.MagicMock()
    mocked_next_step = mocker.MagicMock()

    step = SetOrUpdateCotermDate()

    step(mocked_client, context, mocked_next_step)

    mocked_update.assert_not_called()
    mocked_next_step.assert_called_once_with(mocked_client, context)


def test_set_or_update_coterm_date_step_are_in_sync(
    mocker,
    order_factory,
    adobe_customer_factory,
):
    mocked_update = mocker.patch("adobe_vipm.flows.fulfillment.shared.update_order")
    customer = adobe_customer_factory(coterm_date="2025-01-01")
    order = order_factory()
    order = set_coterm_date(order, "2025-01-01")

    context = Context(
        order=order,
        adobe_customer_id=customer["customerId"],
        adobe_customer=customer,
    )

    mocked_client = mocker.MagicMock()
    mocked_next_step = mocker.MagicMock()

    step = SetOrUpdateCotermDate()

    step(mocked_client, context, mocked_next_step)

    mocked_update.assert_not_called()
    mocked_next_step.assert_called_once_with(mocked_client, context)


def test_set_or_update_coterm_date_step_with_3yc(
    mocker,
    order_factory,
    adobe_customer_factory,
    adobe_commitment_factory,
):
    mocked_update = mocker.patch("adobe_vipm.flows.fulfillment.shared.update_order")
    commitment = adobe_commitment_factory(
        status="REQUESTED",
        start_date="2024-01-01",
        end_date="2027-01-01",
    )
    customer = adobe_customer_factory(coterm_date="2025-01-01", commitment_request=commitment)

    order = order_factory()

    context = Context(
        order=order,
        order_id=order["id"],
        adobe_customer_id=customer["customerId"],
        adobe_customer=customer,
    )

    mocked_client = mocker.MagicMock()
    mocked_next_step = mocker.MagicMock()

    step = SetOrUpdateCotermDate()
    step(mocked_client, context, mocked_next_step)
    mocked_update.assert_called_once_with(
        mocked_client,
        context.order_id,
        parameters=context.order["parameters"],
    )

    parameter_list = [
        get_fulfillment_parameter(context.order, Param.THREE_YC_ENROLL_STATUS.value)["value"],
        get_fulfillment_parameter(context.order, Param.THREE_YC_COMMITMENT_REQUEST_STATUS.value)[
            "value"
        ],
        get_fulfillment_parameter(context.order, Param.THREE_YC_START_DATE.value)["value"],
        get_fulfillment_parameter(context.order, Param.THREE_YC_END_DATE.value)["value"],
        get_fulfillment_parameter(context.order, Param.THREE_YC.value),
    ]

    assert parameter_list == [
        commitment["status"],
        None,
        commitment["startDate"],
        commitment["endDate"],
        {},
    ]
    assert get_coterm_date(context.order) == "2025-01-01"

    mocked_next_step.assert_called_once_with(mocked_client, context)


def test_submit_return_orders_step(
    mocker,
    order_factory,
    adobe_order_factory,
    adobe_items_factory,
    settings,
):
    api_key = "airtable-token"
    settings.EXTENSION_CONFIG = {
        "AIRTABLE_API_TOKEN": api_key,
        "AIRTABLE_BASES": {"PRD-1111-1111": "base-id"},
        "ADOBE_CREDENTIALS_FILE": "a-credentials-file.json",
        "ADOBE_AUTHORIZATIONS_FILE": "an-authorization-file.json",
    }
    adobe_order_1 = adobe_order_factory(
        order_type="NEW",
        items=adobe_items_factory(quantity=1),
        status=AdobeStatus.PROCESSED.value,
    )
    ret_info_1 = ReturnableOrderInfo(
        adobe_order_1,
        adobe_order_1["lineItems"][0],
        adobe_order_1["lineItems"][0]["quantity"],
    )
    sku = adobe_order_1["lineItems"][0]["offerId"][:10]
    mocked_adobe_client = mocker.MagicMock()
    mocked_adobe_client.create_return_order.return_value = adobe_order_factory(
        order_type="RETURN",
        status=AdobeStatus.PENDING.value,
    )
    mocker.patch(
        "adobe_vipm.flows.fulfillment.shared.get_adobe_client",
        return_value=mocked_adobe_client,
    )
    order = order_factory()
    context = Context(
        order=order,
        order_id=order["id"],
        authorization_id="authorization-id",
        adobe_customer_id="customer-id",
        adobe_returnable_orders={sku: (ret_info_1,)},
        adobe_return_orders={},
    )
    mocked_client = mocker.MagicMock()
    mocked_next_step = mocker.MagicMock()

    step = SubmitReturnOrders()
    step(mocked_client, context, mocked_next_step)

    mocked_adobe_client.create_return_order.assert_called_once_with(
        context.authorization_id,
        context.adobe_customer_id,
        ret_info_1.order,
        ret_info_1.line,
        context.order["id"],
        "",
    )

    mocked_next_step.assert_not_called()


def test_submit_return_orders_step_with_deployment_id(
    mocker,
    order_factory,
    adobe_order_factory,
    adobe_items_factory,
    settings,
):
    deployment_id = "deployment-id-1"
    api_key = "airtable-token"
    settings.EXTENSION_CONFIG = {
        "AIRTABLE_API_TOKEN": api_key,
        "AIRTABLE_BASES": {"PRD-1111-1111": "base-id"},
        "ADOBE_CREDENTIALS_FILE": "a-credentials-file.json",
        "ADOBE_AUTHORIZATIONS_FILE": "an-authorization-file.json",
    }
    adobe_order_1 = adobe_order_factory(
        order_type="NEW",
        items=adobe_items_factory(
            quantity=1,
            deployment_id=deployment_id,
            deployment_currency_code="USD",
        ),
        status=AdobeStatus.PROCESSED.value,
        deployment_id=deployment_id,
    )
    ret_info_1 = ReturnableOrderInfo(
        adobe_order_1,
        adobe_order_1["lineItems"][0],
        adobe_order_1["lineItems"][0]["quantity"],
    )
    sku = adobe_order_1["lineItems"][0]["offerId"][:10]

    mocked_adobe_client = mocker.MagicMock()
    mocked_adobe_client.create_return_order.return_value = adobe_order_factory(
        order_type="RETURN",
        status=AdobeStatus.PENDING.value,
        deployment_id=deployment_id,
    )

    mocker.patch(
        "adobe_vipm.flows.fulfillment.shared.get_adobe_client",
        return_value=mocked_adobe_client,
    )

    order = order_factory(deployment_id=deployment_id)
    context = Context(
        order=order,
        order_id=order["id"],
        authorization_id="authorization-id",
        adobe_customer_id="customer-id",
        adobe_returnable_orders={sku: (ret_info_1,)},
        adobe_return_orders={},
    )
    mocked_client = mocker.MagicMock()
    mocked_next_step = mocker.MagicMock()

    step = SubmitReturnOrders()
    step(mocked_client, context, mocked_next_step)

    mocked_adobe_client.create_return_order.assert_called_once_with(
        context.authorization_id,
        context.adobe_customer_id,
        ret_info_1.order,
        ret_info_1.line,
        context.order["id"],
        deployment_id,
    )

    mocked_next_step.assert_not_called()


def test_submit_return_orders_step_with_only_main_deployment_id(
    mocker,
    order_factory,
    adobe_order_factory,
    adobe_items_factory,
    settings,
):
    deployment_id = "deployment-id"
    api_key = "airtable-token"
    settings.EXTENSION_CONFIG = {
        "AIRTABLE_API_TOKEN": api_key,
        "AIRTABLE_BASES": {"PRD-1111-1111": "base-id"},
        "ADOBE_CREDENTIALS_FILE": "a-credentials-file.json",
        "ADOBE_AUTHORIZATIONS_FILE": "an-authorization-file.json",
    }
    adobe_order_1 = adobe_order_factory(
        order_type="NEW",
        items=adobe_items_factory(quantity=1),
        status=AdobeStatus.PROCESSED.value,
        deployment_id=deployment_id,
    )
    ret_info_1 = ReturnableOrderInfo(
        adobe_order_1,
        adobe_order_1["lineItems"][0],
        adobe_order_1["lineItems"][0]["quantity"],
    )
    sku = adobe_order_1["lineItems"][0]["offerId"][:10]

    mocked_adobe_client = mocker.MagicMock()
    mocked_adobe_client.create_return_order.return_value = adobe_order_factory(
        order_type="RETURN",
        status=AdobeStatus.PENDING.value,
    )

    mocker.patch(
        "adobe_vipm.flows.fulfillment.shared.get_adobe_client",
        return_value=mocked_adobe_client,
    )

    order = order_factory(deployment_id="deployment-id_return")
    context = Context(
        order=order,
        order_id=order["id"],
        authorization_id="authorization-id",
        adobe_customer_id="customer-id",
        adobe_returnable_orders={sku: (ret_info_1,)},
        adobe_return_orders={},
    )
    mocked_client = mocker.MagicMock()
    mocked_next_step = mocker.MagicMock()

    step = SubmitReturnOrders()
    step(mocked_client, context, mocked_next_step)

    mocked_adobe_client.create_return_order.assert_not_called()


def test_submit_return_orders_step_order_processed(
    mocker,
    order_factory,
    adobe_order_factory,
    adobe_items_factory,
    settings,
):
    api_key = "airtable-token"
    settings.EXTENSION_CONFIG = {
        "AIRTABLE_API_TOKEN": api_key,
        "AIRTABLE_BASES": {"PRD-1111-1111": "base-id"},
    }
    adobe_order_1 = adobe_order_factory(
        order_type="NEW",
        items=adobe_items_factory(quantity=1),
        status=AdobeStatus.PROCESSED.value,
    )
    ret_info_1 = ReturnableOrderInfo(
        adobe_order_1,
        adobe_order_1["lineItems"][0],
        adobe_order_1["lineItems"][0]["quantity"],
    )
    sku = adobe_order_1["lineItems"][0]["offerId"][:10]

    return_order = adobe_order_factory(
        order_type="RETURN",
        status=AdobeStatus.PROCESSED.value,
        reference_order_id=adobe_order_1["orderId"],
    )

    mocked_adobe_client = mocker.MagicMock()

    mocker.patch(
        "adobe_vipm.flows.fulfillment.shared.get_adobe_client",
        return_value=mocked_adobe_client,
    )
    order = order_factory()
    context = Context(
        order=order,
        order_id=order["id"],
        authorization_id="authorization-id",
        adobe_customer_id="customer-id",
        adobe_returnable_orders={sku: (ret_info_1,)},
        adobe_return_orders={sku: [return_order]},
    )
    mocked_client = mocker.MagicMock()
    mocked_next_step = mocker.MagicMock()

    step = SubmitReturnOrders()
    step(mocked_client, context, mocked_next_step)

    mocked_adobe_client.create_return_order.assert_not_called()

    mocked_next_step.assert_called_once_with(mocked_client, context)


def test_submit_new_order_step(mocker, order_factory, adobe_order_factory):
    order = order_factory(deployment_id=None)
    preview_order = adobe_order_factory(order_type=ORDER_TYPE_PREVIEW)
    new_order = adobe_order_factory(order_type=ORDER_TYPE_NEW, status=AdobeStatus.PENDING.value)

    mocked_adobe_client = mocker.MagicMock()
    mocked_adobe_client.create_new_order.return_value = new_order

    mocker.patch(
        "adobe_vipm.flows.fulfillment.shared.get_adobe_client",
        return_value=mocked_adobe_client,
    )
    mocked_update = mocker.patch(
        "adobe_vipm.flows.fulfillment.shared.update_order",
    )

    mocked_client = mocker.MagicMock()
    mocked_next_step = mocker.MagicMock()

    context = Context(
        order=order,
        order_id=order["id"],
        authorization_id="authorization-id",
        adobe_customer_id="customer-id",
        upsize_lines=order["lines"],
        adobe_preview_order=preview_order,
        deployment_id=None,
    )

    step = SubmitNewOrder()
    step(mocked_client, context, mocked_next_step)

    mocked_adobe_client.create_new_order.assert_called_once_with(
        context.authorization_id,
        context.adobe_customer_id,
        preview_order,
        deployment_id=None,
    )

    mocked_update.assert_called_once_with(
        mocked_client,
        context.order_id,
        externalIds=context.order["externalIds"],
    )
    assert get_adobe_order_id(context.order) == new_order["orderId"]
    mocked_next_step.assert_not_called()


def test_submit_new_order_step_with_deployment_id(
    mocker, order_factory, adobe_order_factory, settings
):
    deployment_id = "deployment-id"

    order = order_factory(deployment_id=deployment_id)
    preview_order = adobe_order_factory(order_type=ORDER_TYPE_PREVIEW, deployment_id=deployment_id)
    new_order = adobe_order_factory(
        order_type=ORDER_TYPE_NEW,
        status=AdobeStatus.PENDING.value,
        deployment_id=deployment_id,
    )

    mocked_adobe_client = mocker.MagicMock()
    mocked_adobe_client.create_new_order.return_value = new_order

    mocker.patch(
        "adobe_vipm.flows.fulfillment.shared.get_adobe_client",
        return_value=mocked_adobe_client,
    )
    mocked_update = mocker.patch(
        "adobe_vipm.flows.fulfillment.shared.update_order",
    )

    mocked_client = mocker.MagicMock()
    mocked_next_step = mocker.MagicMock()

    context = Context(
        order=order,
        order_id=order["id"],
        authorization_id="authorization-id",
        adobe_customer_id="customer-id",
        upsize_lines=order["lines"],
        adobe_preview_order=preview_order,
        deployment_id=deployment_id,
    )

    step = SubmitNewOrder()
    step(mocked_client, context, mocked_next_step)

    mocked_adobe_client.create_new_order.assert_called_once_with(
        context.authorization_id,
        context.adobe_customer_id,
        preview_order,
        deployment_id=deployment_id,
    )

    mocked_update.assert_called_once_with(
        mocked_client,
        context.order_id,
        externalIds=context.order["externalIds"],
    )
    assert get_adobe_order_id(context.order) == new_order["orderId"]
    mocked_next_step.assert_not_called()


def test_submit_new_order_step_order_created_and_processed(
    mocker,
    order_factory,
    adobe_order_factory,
):
    new_order = adobe_order_factory(
        order_type="NEW",
        status=AdobeStatus.PROCESSED.value,
    )
    order = order_factory(external_ids={"vendor": new_order["orderId"]})

    mocked_adobe_client = mocker.MagicMock()
    mocked_adobe_client.get_order.return_value = new_order

    mocker.patch(
        "adobe_vipm.flows.fulfillment.shared.get_adobe_client",
        return_value=mocked_adobe_client,
    )
    mocked_update = mocker.patch(
        "adobe_vipm.flows.fulfillment.shared.update_order",
    )

    mocked_client = mocker.MagicMock()
    mocked_next_step = mocker.MagicMock()

    context = Context(
        order=order,
        adobe_new_order_id=new_order["orderId"],
        authorization_id="authorization-id",
        adobe_customer_id="customer-id",
        upsize_lines=order["lines"],
        deployment_id="",
    )

    step = SubmitNewOrder()
    step(mocked_client, context, mocked_next_step)

    mocked_adobe_client.get_order.assert_called_once_with(
        context.authorization_id,
        context.adobe_customer_id,
        context.adobe_new_order_id,
    )
    mocked_adobe_client.create_preview_order.assert_not_called()
    mocked_adobe_client.create_new_order.assert_not_called()
    mocked_update.assert_not_called()

    mocked_next_step.assert_called_once_with(mocked_client, context)


def test_submit_new_order_step_order_created_and_processed_with_deployment_id(
    mocker,
    order_factory,
    adobe_order_factory,
):
    deployment_id = "deployment-id"

    new_order = adobe_order_factory(
        order_type="NEW",
        status=AdobeStatus.PROCESSED.value,
    )
    order = order_factory(external_ids={"vendor": new_order["orderId"]})

    mocked_adobe_client = mocker.MagicMock()
    mocked_adobe_client.get_order.return_value = new_order

    mocker.patch(
        "adobe_vipm.flows.fulfillment.shared.get_adobe_client",
        return_value=mocked_adobe_client,
    )
    mocked_update = mocker.patch(
        "adobe_vipm.flows.fulfillment.shared.update_order",
    )

    mocked_client = mocker.MagicMock()
    mocked_next_step = mocker.MagicMock()

    context = Context(
        order=order,
        adobe_new_order_id=new_order["orderId"],
        authorization_id="authorization-id",
        adobe_customer_id="customer-id",
        upsize_lines=order["lines"],
        deployment_id=deployment_id,
    )

    step = SubmitNewOrder()
    step(mocked_client, context, mocked_next_step)

    mocked_adobe_client.get_order.assert_called_once_with(
        context.authorization_id,
        context.adobe_customer_id,
        context.adobe_new_order_id,
    )
    mocked_adobe_client.create_preview_order.assert_not_called()
    mocked_adobe_client.create_new_order.assert_not_called()
    mocked_update.assert_not_called()

    mocked_next_step.assert_called_once_with(mocked_client, context)


def test_submit_new_order_step_order_no_upsize_lines(
    mocker,
    order_factory,
    lines_factory,
):
    order = order_factory(
        lines=lines_factory(quantity=10, old_quantity=12),
    )
    mocked_adobe_client = mocker.MagicMock()

    mocker.patch(
        "adobe_vipm.flows.fulfillment.shared.get_adobe_client",
        return_value=mocked_adobe_client,
    )

    mocked_client = mocker.MagicMock()
    mocked_next_step = mocker.MagicMock()

    context = Context(
        order=order,
        order_id=order["id"],
        authorization_id="authorization-id",
        adobe_customer_id="customer-id",
        downsize_lines=order["lines"],
    )

    step = SubmitNewOrder()
    step(mocked_client, context, mocked_next_step)

    mocked_adobe_client.get_order.assert_not_called()
    mocked_adobe_client.create_preview_order.assert_not_called()
    mocked_adobe_client.create_new_order.assert_not_called()

    mocked_next_step.assert_called_once_with(mocked_client, context)


@pytest.mark.parametrize(
    "processing_status",
    list(ORDER_STATUS_DESCRIPTION.keys()),
)
def test_submit_new_order_step_order_created_unrecoverable_status(
    mocker,
    order_factory,
    adobe_order_factory,
    processing_status,
):
    new_order = adobe_order_factory(
        order_type="NEW",
        status=processing_status,
        order_id="adobe-order-id",
    )
    order = order_factory()

    mocked_adobe_client = mocker.MagicMock()
    mocked_adobe_client.get_order.return_value = new_order

    mocker.patch(
        "adobe_vipm.flows.fulfillment.shared.get_adobe_client",
        return_value=mocked_adobe_client,
    )
    mocked_update = mocker.patch(
        "adobe_vipm.flows.fulfillment.shared.update_order",
    )
    mocked_switch_to_failed = mocker.patch(
        "adobe_vipm.flows.fulfillment.shared.switch_order_to_failed",
    )

    mocked_client = mocker.MagicMock()
    mocked_next_step = mocker.MagicMock()

    context = Context(
        order=order,
        order_id=order["id"],
        adobe_new_order_id="adobe-order-id",
        authorization_id="authorization-id",
        adobe_customer_id="customer-id",
        upsize_lines=order["lines"],
    )

    step = SubmitNewOrder()
    step(mocked_client, context, mocked_next_step)

    mocked_adobe_client.get_order.assert_called_once_with(
        context.authorization_id,
        context.adobe_customer_id,
        context.adobe_new_order_id,
    )
    mocked_switch_to_failed.assert_called_once_with(
        mocked_client,
        context.order,
        ERR_UNRECOVERABLE_ADOBE_ORDER_STATUS.to_dict(
            description=ORDER_STATUS_DESCRIPTION[processing_status],
        ),
    )
    mocked_adobe_client.create_preview_order.assert_not_called()
    mocked_adobe_client.create_new_order.assert_not_called()
    mocked_update.assert_not_called()
    mocked_next_step.assert_not_called()


def test_submit_new_order_step_order_created_unexpected_status(
    mocker,
    order_factory,
    adobe_order_factory,
):
    new_order = adobe_order_factory(
        order_id="order-id",
        order_type="NEW",
        status="9999",
    )
    order = order_factory()

    mocked_adobe_client = mocker.MagicMock()
    mocked_adobe_client.get_order.return_value = new_order

    mocker.patch(
        "adobe_vipm.flows.fulfillment.shared.get_adobe_client",
        return_value=mocked_adobe_client,
    )
    mocked_update = mocker.patch(
        "adobe_vipm.flows.fulfillment.shared.update_order",
    )
    mocked_switch_to_failed = mocker.patch(
        "adobe_vipm.flows.fulfillment.shared.switch_order_to_failed",
    )

    mocked_client = mocker.MagicMock()
    mocked_next_step = mocker.MagicMock()

    context = Context(
        order=order,
        order_id=order["id"],
        adobe_new_order_id="order-id",
        authorization_id="authorization-id",
        adobe_customer_id="customer-id",
        upsize_lines=order["lines"],
    )

    step = SubmitNewOrder()
    step(mocked_client, context, mocked_next_step)

    mocked_adobe_client.get_order.assert_called_once_with(
        context.authorization_id,
        context.adobe_customer_id,
        context.adobe_new_order_id,
    )
    mocked_switch_to_failed.assert_called_once_with(
        mocked_client,
        context.order,
        ERR_UNEXPECTED_ADOBE_ERROR_STATUS.to_dict(status="9999"),
    )
    mocked_adobe_client.create_preview_order.assert_not_called()
    mocked_adobe_client.create_new_order.assert_not_called()
    mocked_update.assert_not_called()
    mocked_next_step.assert_not_called()


def test_get_return_orders_step(mocker, order_factory, adobe_order_factory):
    return_order = adobe_order_factory(
        order_type="RETURN",
        status=AdobeStatus.PROCESSED.value,
        reference_order_id="new-order-id",
    )

    mocked_adobe_client = mocker.MagicMock()
    mocked_adobe_client.get_return_orders_by_external_reference.return_value = {
        "sku": [return_order],
    }

    mocker.patch(
        "adobe_vipm.flows.fulfillment.shared.get_adobe_client",
        return_value=mocked_adobe_client,
    )

    order = order_factory()
    context = Context(
        order=order,
        order_id=order["id"],
        authorization_id="auth-id",
        adobe_customer_id="adobe-customer-id",
    )

    mocked_client = mocker.MagicMock()
    mocked_next_step = mocker.MagicMock()

    step = GetReturnOrders()
    step(mocked_client, context, mocked_next_step)

    assert context.adobe_return_orders == {"sku": [return_order]}
    mocked_adobe_client.get_return_orders_by_external_reference.assert_called_once_with(
        context.authorization_id,
        context.adobe_customer_id,
        context.order_id,
    )
    mocked_next_step.assert_called_once_with(mocked_client, context)


def test_create_or_update_subscriptions_step(
    mocker,
    order_factory,
    subscriptions_factory,
    adobe_order_factory,
    adobe_items_factory,
    adobe_subscription_factory,
):
    adobe_order = adobe_order_factory(
        order_type=ORDER_TYPE_NEW,
        items=adobe_items_factory(subscription_id="adobe-sub-id"),
    )
    adobe_subscription = adobe_subscription_factory()

    mocked_adobe_client = mocker.MagicMock()
    mocked_adobe_client.get_subscription.return_value = adobe_subscription

    mocker.patch(
        "adobe_vipm.flows.fulfillment.shared.get_adobe_client",
        return_value=mocked_adobe_client,
    )

    mocker.patch(
        "adobe_vipm.flows.fulfillment.shared.get_one_time_skus",
        return_value=[],
    )

    mocked_create_subscription = mocker.patch(
        "adobe_vipm.flows.fulfillment.shared.create_subscription",
        return_value=subscriptions_factory()[0],
    )

    mocked_client = mocker.MagicMock()
    mocked_next_step = mocker.MagicMock()

    order = order_factory()

    context = Context(
        order=order,
        order_id=order["id"],
        authorization_id="auth-id",
        adobe_customer_id="adobe-customer-id",
        adobe_new_order=adobe_order,
    )

    step = CreateOrUpdateSubscriptions()
    step(mocked_client, context, mocked_next_step)

    mocked_adobe_client.get_subscription.assert_called_once_with(
        context.authorization_id,
        context.adobe_customer_id,
        adobe_order["lineItems"][0]["subscriptionId"],
    )

    mocked_create_subscription.assert_called_once_with(
        mocked_client,
        context.order_id,
        {
            "name": f"Subscription for {order['lines'][0]['item']['name']}",
            "parameters": {
                "fulfillment": [
                    {
                        "externalId": "adobeSKU",
                        "value": adobe_order["lineItems"][0]["offerId"],
                    },
                    {
                        "externalId": Param.CURRENT_QUANTITY.value,
                        "value": str(adobe_subscription[Param.CURRENT_QUANTITY.value]),
                    },
                    {
                        "externalId": Param.RENEWAL_QUANTITY.value,
                        "value": str(
                            adobe_subscription["autoRenewal"][Param.RENEWAL_QUANTITY.value]
                        ),
                    },
                    {
                        "externalId": "renewalDate",
                        "value": adobe_subscription["renewalDate"],
                    },
                ]
            },
            "externalIds": {"vendor": adobe_order["lineItems"][0]["subscriptionId"]},
            "lines": [{"id": order["lines"][0]["id"]}],
            "startDate": adobe_subscription["creationDate"],
            "commitmentDate": adobe_subscription["renewalDate"],
            "autoRenew": adobe_subscription["autoRenewal"]["enabled"],
        },
    )
    mocked_next_step.assert_called_once_with(mocked_client, context)


def test_create_or_update_subscriptions_step_subscription_exists(
    mocker,
    order_factory,
    subscriptions_factory,
    adobe_order_factory,
    adobe_items_factory,
    adobe_subscription_factory,
):
    adobe_order = adobe_order_factory(
        order_type=ORDER_TYPE_NEW,
        items=adobe_items_factory(subscription_id="adobe-sub-id"),
    )
    adobe_subscription = adobe_subscription_factory()

    mocked_adobe_client = mocker.MagicMock()
    mocked_adobe_client.get_subscription.return_value = adobe_subscription

    mocker.patch(
        "adobe_vipm.flows.fulfillment.shared.get_adobe_client",
        return_value=mocked_adobe_client,
    )

    mocker.patch(
        "adobe_vipm.flows.fulfillment.shared.get_one_time_skus",
        return_value=[],
    )

    mocked_set_sku = mocker.patch(
        "adobe_vipm.flows.fulfillment.shared.set_subscription_actual_sku",
    )

    mocked_client = mocker.MagicMock()
    mocked_next_step = mocker.MagicMock()

    order = order_factory(
        subscriptions=subscriptions_factory(),
    )

    context = Context(
        order=order,
        order_id=order["id"],
        authorization_id="auth-id",
        adobe_customer_id="adobe-customer-id",
        adobe_new_order=adobe_order,
    )

    step = CreateOrUpdateSubscriptions()
    step(mocked_client, context, mocked_next_step)

    mocked_adobe_client.get_subscription.assert_not_called()

    mocked_set_sku.assert_called_once_with(
        mocked_client,
        context.order,
        order["subscriptions"][0],
        adobe_order["lineItems"][0]["offerId"],
    )
    mocked_next_step.assert_called_once_with(mocked_client, context)


def test_create_or_update_subscriptions_step_no_adobe_new_order(
    mocker,
    order_factory,
    subscriptions_factory,
):
    mocked_adobe_client = mocker.MagicMock()

    mocker.patch(
        "adobe_vipm.flows.fulfillment.shared.get_adobe_client",
        return_value=mocked_adobe_client,
    )
    mocked_create_sub = mocker.patch(
        "adobe_vipm.flows.fulfillment.shared.create_subscription",
    )

    mocked_set_sku = mocker.patch(
        "adobe_vipm.flows.fulfillment.shared.set_subscription_actual_sku",
    )

    mocked_client = mocker.MagicMock()
    mocked_next_step = mocker.MagicMock()

    order = order_factory(
        subscriptions=subscriptions_factory(),
    )

    context = Context(
        order=order,
        order_id=order["id"],
        authorization_id="auth-id",
        adobe_customer_id="adobe-customer-id",
        adobe_new_order=None,
    )

    step = CreateOrUpdateSubscriptions()
    step(mocked_client, context, mocked_next_step)

    mocked_adobe_client.get_subscription.assert_not_called()
    mocked_create_sub.assert_not_called()
    mocked_set_sku.assert_not_called()
    mocked_next_step.assert_called_once_with(mocked_client, context)


def test_create_or_update_subscriptions_step_sub_expired(
    mocker,
    order_factory,
    subscriptions_factory,
    adobe_order_factory,
    adobe_items_factory,
    adobe_subscription_factory,
):
    adobe_order = adobe_order_factory(
        order_type=ORDER_TYPE_NEW,
        items=adobe_items_factory(subscription_id="adobe-sub-id"),
    )
    adobe_subscription = adobe_subscription_factory(
        status=AdobeStatus.ORDER_CANCELLED.value,
    )

    mocked_adobe_client = mocker.MagicMock()
    mocked_adobe_client.get_subscription.return_value = adobe_subscription

    mocker.patch(
        "adobe_vipm.flows.fulfillment.shared.get_adobe_client",
        return_value=mocked_adobe_client,
    )

    mocker.patch(
        "adobe_vipm.flows.fulfillment.shared.get_one_time_skus",
        return_value=[],
    )

    mocked_create_subscription = mocker.patch(
        "adobe_vipm.flows.fulfillment.shared.create_subscription",
    )

    mocked_client = mocker.MagicMock()
    mocked_next_step = mocker.MagicMock()

    order = order_factory()

    context = Context(
        order=order,
        order_id=order["id"],
        authorization_id="auth-id",
        adobe_customer_id="adobe-customer-id",
        adobe_new_order=adobe_order,
    )

    step = CreateOrUpdateSubscriptions()
    step(mocked_client, context, mocked_next_step)

    mocked_adobe_client.get_subscription.assert_called_once_with(
        context.authorization_id,
        context.adobe_customer_id,
        adobe_order["lineItems"][0]["subscriptionId"],
    )

    mocked_create_subscription.assert_not_called()
    mocked_next_step.assert_called_once_with(mocked_client, context)


def test_create_or_update_subscriptions_step_update_existing_subscription(
    mocker,
    order_factory,
    subscriptions_factory,
    adobe_order_factory,
    adobe_items_factory,
):
    adobe_order = adobe_order_factory(
        order_type=ORDER_TYPE_NEW,
        items=adobe_items_factory(subscription_id="adobe-sub-id"),
    )

    mocker.patch(
        "adobe_vipm.flows.fulfillment.shared.get_adobe_client",
        return_value=mocker.MagicMock(),
    )

    mocker.patch(
        "adobe_vipm.flows.fulfillment.shared.get_one_time_skus",
        return_value=[],
    )

    mocked_set_sku = mocker.patch(
        "adobe_vipm.flows.fulfillment.shared.set_subscription_actual_sku",
    )

    mocked_client = mocker.MagicMock()
    mocked_next_step = mocker.MagicMock()

    order = order_factory(
        subscriptions=subscriptions_factory(),
    )

    context = Context(
        order=order,
        order_id=order["id"],
        authorization_id="auth-id",
        adobe_customer_id="adobe-customer-id",
        adobe_new_order=adobe_order,
    )
    step = CreateOrUpdateSubscriptions()
    step(mocked_client, context, mocked_next_step)

    mocked_set_sku.assert_called_once_with(
        mocked_client,
        context.order,
        order["subscriptions"][0],
        adobe_order["lineItems"][0]["offerId"],
    )
    mocked_next_step.assert_called_once_with(mocked_client, context)


@freeze_time("2024-01-01")
def test_complete_order_step(mocker, order_factory):
    order = order_factory()

    resetted_order = order_factory()

    completed_order = order_factory(status=MPT_ORDER_STATUS_COMPLETED)

    mocked_get_template = mocker.patch(
        "adobe_vipm.flows.fulfillment.shared.get_product_template_or_default",
        return_value={"id": "TPL-0000"},
    )
    mocked_complete_order = mocker.patch(
        "adobe_vipm.flows.fulfillment.shared.complete_order",
        return_value=completed_order,
    )

    mocked_client = mocker.MagicMock()
    mocked_next_step = mocker.MagicMock()

    context = Context(
        order=order,
        order_id=order["id"],
        product_id=order["agreement"]["product"]["id"],
    )

    step = CompleteOrder("my-template")
    step(mocked_client, context, mocked_next_step)

    mocked_get_template.assert_called_once_with(
        mocked_client,
        context.product_id,
        MPT_ORDER_STATUS_COMPLETED,
        "my-template",
    )
    mocked_complete_order.assert_called_once_with(
        mocked_client,
        context.order_id,
        {"id": "TPL-0000"},
        parameters=resetted_order["parameters"],
    )
    assert context.order == completed_order
    mocked_next_step.assert_called_once_with(mocked_client, context)


@pytest.mark.parametrize(
    ("auto_renew", "expected_template"),
    [
        (True, TEMPLATE_CONFIGURATION_AUTORENEWAL_ENABLE),
        (False, TEMPLATE_CONFIGURATION_AUTORENEWAL_DISABLE),
    ],
)
def test_complete_configuration_order_selects_template(
    mocker, order_factory, auto_renew, expected_template, mocked_send_mpt_notification
):
    order = order_factory(subscriptions=[{"autoRenew": auto_renew}])
    completed_order = order_factory(status="Completed")
    context = Context(
        order=order,
        order_id=order["id"],
        product_id=order["agreement"]["product"]["id"],
    )

    mocked_client = mocker.MagicMock()
    mocked_next_step = mocker.MagicMock()

    mocked_get_template = mocker.patch(
        "adobe_vipm.flows.fulfillment.shared.get_product_template_or_default",
        return_value={"id": "TPL-0000"},
    )
    mocked_complete_order = mocker.patch(
        "adobe_vipm.flows.fulfillment.shared.complete_order",
        return_value=completed_order,
    )

    step = CompleteOrder(expected_template)
    step(mocked_client, context, mocked_next_step)

    mocked_get_template.assert_called_once_with(
        mocked_client,
        context.product_id,
        "Completed",
        expected_template,
    )
    mocked_complete_order.assert_called_once_with(
        mocked_client,
        context.order_id,
        {"id": "TPL-0000"},
        parameters=order["parameters"],
    )
    mocked_send_mpt_notification.assert_called_once_with(mocked_client, completed_order)
    assert context.order == completed_order
    mocked_next_step.assert_called_once_with(mocked_client, context)


def test_sync_agreement_step(mocker, order_factory):
    mocked_sync = mocker.patch(
        "adobe_vipm.flows.fulfillment.shared.sync_agreements_by_agreement_ids",
    )

    mocked_client = mocker.MagicMock()
    mocked_next_step = mocker.MagicMock()

    order = order_factory()

    context = Context(
        order=order,
        order_id=order["id"],
        agreement_id=order["agreement"]["id"],
    )

    step = SyncAgreement()
    step(mocked_client, context, mocked_next_step)

    mocked_sync.assert_called_once_with(
        mocked_client, [context.agreement_id], dry_run=False, sync_prices=True
    )

    mocked_next_step.assert_called_once_with(mocked_client, context)


def test_validate_duplicate_lines_step(mocker, order_factory, lines_factory):
    order = order_factory(
        order_type="Change",
        lines=lines_factory() + lines_factory(),
    )
    mocked_fail = mocker.patch(
        "adobe_vipm.flows.fulfillment.shared.switch_order_to_failed",
    )

    mocked_client = mocker.MagicMock()
    mocked_next_step = mocker.MagicMock()

    context = Context(order=order, order_id=order["id"])

    step = ValidateDuplicateLines()
    step(mocked_client, context, mocked_next_step)

    mocked_fail.assert_called_once_with(
        mocked_client,
        context.order,
        ERR_DUPLICATED_ITEMS.to_dict(duplicates="ITM-1234-1234-1234-0001"),
    )
    mocked_next_step.assert_not_called()


def test_validate_duplicate_lines_step_existing_item(
    mocker,
    order_factory,
    lines_factory,
):
    order = order_factory(
        order_type="Change",
        lines=lines_factory(line_id=2, item_id=10),
    )
    mocked_fail = mocker.patch(
        "adobe_vipm.flows.fulfillment.shared.switch_order_to_failed",
    )

    mocked_client = mocker.MagicMock()
    mocked_next_step = mocker.MagicMock()

    context = Context(order=order, order_id=order["id"])

    step = ValidateDuplicateLines()
    step(mocked_client, context, mocked_next_step)

    mocked_fail.assert_called_once_with(
        mocked_client,
        context.order,
        ERR_EXISTING_ITEMS.to_dict(
            duplicates="ITM-1234-1234-1234-0010",
        ),
    )
    mocked_next_step.assert_not_called()


def test_validate_duplicate_lines_step_no_duplicates(
    mocker,
    order_factory,
):
    order = order_factory(
        order_type="Change",
    )
    mocked_fail = mocker.patch(
        "adobe_vipm.flows.fulfillment.shared.switch_order_to_failed",
    )

    mocked_client = mocker.MagicMock()
    mocked_next_step = mocker.MagicMock()

    context = Context(order=order, order_id=order["id"])

    step = ValidateDuplicateLines()
    step(mocked_client, context, mocked_next_step)

    mocked_fail.assert_not_called()
    mocked_next_step.assert_called_once_with(mocked_client, context)


def test_get_preview_order_step(mocker, order_factory, adobe_order_factory):
    deployment_id = "deployment-id"

    order = order_factory(deployment_id=deployment_id)
    preview_order = adobe_order_factory(order_type=ORDER_TYPE_PREVIEW, deployment_id=deployment_id)

    mocked_adobe_client = mocker.MagicMock()
    mocked_adobe_client.create_preview_order.return_value = preview_order

    mocker.patch(
        "adobe_vipm.flows.fulfillment.shared.get_adobe_client",
        return_value=mocked_adobe_client,
    )

    mocked_client = mocker.MagicMock()
    mocked_next_step = mocker.MagicMock()

    context = Context(
        order=order,
        order_id=order["id"],
        authorization_id="authorization-id",
        adobe_customer_id="customer-id",
        new_lines=order["lines"],
        upsize_lines=[],
        deployment_id=deployment_id,
    )

    step = GetPreviewOrder()
    step(mocked_client, context, mocked_next_step)

    assert context.adobe_preview_order == preview_order

    mocked_adobe_client.create_preview_order.assert_called_once_with(
        context.authorization_id,
        context.adobe_customer_id,
        context.order_id,
        context.upsize_lines,
        context.new_lines,
        deployment_id=deployment_id,
    )


def test_get_preview_order_step_order_no_upsize_lines(
    mocker,
    order_factory,
    lines_factory,
):
    order = order_factory(
        lines=lines_factory(quantity=10, old_quantity=12),
    )
    mocked_adobe_client = mocker.MagicMock()

    mocker.patch(
        "adobe_vipm.flows.fulfillment.shared.get_adobe_client",
        return_value=mocked_adobe_client,
    )

    mocked_client = mocker.MagicMock()
    mocked_next_step = mocker.MagicMock()

    context = Context(
        order=order,
        order_id=order["id"],
        authorization_id="authorization-id",
        adobe_customer_id="customer-id",
        downsize_lines=order["lines"],
    )

    step = GetPreviewOrder()
    step(mocked_client, context, mocked_next_step)

    mocked_adobe_client.create_preview_order.assert_not_called()

    mocked_next_step.assert_called_once_with(mocked_client, context)


def test_get_preview_order_step_order_new_order_created(
    mocker,
    order_factory,
    lines_factory,
):
    order = order_factory(
        lines=lines_factory(quantity=12, old_quantity=10),
    )
    mocked_adobe_client = mocker.MagicMock()

    mocker.patch(
        "adobe_vipm.flows.fulfillment.shared.get_adobe_client",
        return_value=mocked_adobe_client,
    )

    mocked_client = mocker.MagicMock()
    mocked_next_step = mocker.MagicMock()

    context = Context(
        order=order,
        order_id=order["id"],
        authorization_id="authorization-id",
        adobe_customer_id="customer-id",
        upsize_lines=order["lines"],
        adobe_new_order_id="new-order-id",
    )

    step = GetPreviewOrder()
    step(mocked_client, context, mocked_next_step)

    mocked_adobe_client.create_preview_order.assert_not_called()

    mocked_next_step.assert_called_once_with(mocked_client, context)


def test_get_preview_order_step_adobe_error(
    mocker,
    order_factory,
    lines_factory,
    adobe_api_error_factory,
):
    order = order_factory(
        lines=lines_factory(quantity=12, old_quantity=10),
    )

    error_data = adobe_api_error_factory("1234", "error message")
    error = AdobeAPIError(400, error_data)

    mocked_adobe_client = mocker.MagicMock()
    mocked_adobe_client.create_preview_order.side_effect = error

    mocker.patch(
        "adobe_vipm.flows.fulfillment.shared.get_adobe_client",
        return_value=mocked_adobe_client,
    )

    mocked_switch_to_failed = mocker.patch(
        "adobe_vipm.flows.fulfillment.shared.switch_order_to_failed",
    )

    mocked_client = mocker.MagicMock()
    mocked_next_step = mocker.MagicMock()

    context = Context(
        order=order,
        order_id=order["id"],
        authorization_id="authorization-id",
        adobe_customer_id="customer-id",
        upsize_lines=order["lines"],
    )

    step = GetPreviewOrder()
    step(mocked_client, context, mocked_next_step)

    mocked_switch_to_failed.assert_called_once_with(
        mocked_client,
        context.order,
        ERR_VIPM_UNHANDLED_EXCEPTION.to_dict(error=str(error)),
    )
    mocked_next_step.assert_not_called()


@pytest.mark.parametrize(
    ("status", "subject"),
    [
        (
            "Processing",
            "This order need your attention ORD-1234 for A buyer",
        )
    ],
)
def test_send_gc_mpt_notification(
    mocker, settings, order_factory, mock_mpt_client, status, subject
):
    mock_mpt_notify = mocker.patch("adobe_vipm.flows.fulfillment.shared.mpt_notify")

    order = order_factory(order_id="ORD-1234", status=status)

    send_gc_mpt_notification(mock_mpt_client, order, ["deployment 1"])

    mock_mpt_notify.assert_called_once_with(
        mock_mpt_client,
        order["agreement"]["licensee"]["account"]["id"],
        order["agreement"]["buyer"]["id"],
        subject,
        "notification",
        {
            "order": order,
            "activation_template": "This order needs your attention because it contains"
            " items with a deployment ID associated. Please remove "
            "the following items with deployment associated manually."
            " <ul>\n\t<li>deployment 1</li>\n</ul>Then, change the main "
            "agreement status to 'pending' on Airtable.",
            "api_base_url": settings.MPT_API_BASE_URL,
            "portal_base_url": settings.MPT_PORTAL_BASE_URL,
        },
    )


@freeze_time("2024-05-06")
def test_validate_renewal_window_creation_window_validation_mode(
    mocker, order_factory, fulfillment_parameters_factory
):
    mocked_client = mocker.MagicMock()
    mocked_next_step = mocker.MagicMock()
    mocked_set_order_error = mocker.patch("adobe_vipm.flows.fulfillment.shared.set_order_error")
    mocked_switch_order_to_failed = mocker.patch(
        "adobe_vipm.flows.fulfillment.shared.switch_order_to_failed"
    )

    # Test with coterm date in creation window
    order = order_factory(
        fulfillment_parameters=fulfillment_parameters_factory(coterm_date="2024-05-06")
    )
    context = Context(order=order, order_id=order["id"])

    step = ValidateRenewalWindow(is_validation=True)
    step(mocked_client, context, mocked_next_step)

    mocked_set_order_error.assert_called_once()
    mocked_switch_order_to_failed.assert_not_called()
    mocked_next_step.assert_called_once_with(mocked_client, context)


@freeze_time("2024-05-06")
def test_validate_renewal_window_creation_window_non_validation_mode(
    mocker, order_factory, fulfillment_parameters_factory
):
    mocked_client = mocker.MagicMock()
    mocked_next_step = mocker.MagicMock()
    mocked_set_order_error = mocker.patch("adobe_vipm.flows.fulfillment.shared.set_order_error")
    mocked_switch_order_to_failed = mocker.patch(
        "adobe_vipm.flows.fulfillment.shared.switch_order_to_failed"
    )

    # Test with coterm date in creation window
    order = order_factory(
        fulfillment_parameters=fulfillment_parameters_factory(coterm_date="2024-05-06")
    )
    context = Context(order=order, order_id=order["id"])

    step = ValidateRenewalWindow(is_validation=False)
    step(mocked_client, context, mocked_next_step)

    mocked_set_order_error.assert_not_called()
    mocked_switch_order_to_failed.assert_called_once()
    mocked_next_step.assert_not_called()

    # Reset mocks
    mocked_switch_order_to_failed.reset_mock()
    mocked_next_step.reset_mock()

    # Test with no coterm date
    order = order_factory(fulfillment_parameters=fulfillment_parameters_factory(coterm_date=None))
    context = Context(order=order, order_id=order["id"])

    step = ValidateRenewalWindow(is_validation=False)
    step(mocked_client, context, mocked_next_step)

    mocked_set_order_error.assert_not_called()
    mocked_switch_order_to_failed.assert_not_called()
    mocked_next_step.assert_called_once_with(mocked_client, context)
