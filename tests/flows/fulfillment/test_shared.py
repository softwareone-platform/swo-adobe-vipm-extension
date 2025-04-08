import logging
from datetime import date

import pytest
from freezegun import freeze_time

from adobe_vipm.adobe.constants import (
    ORDER_STATUS_DESCRIPTION,
    ORDER_TYPE_NEW,
    ORDER_TYPE_PREVIEW,
    STATUS_ORDER_CANCELLED,
    STATUS_PENDING,
    STATUS_PROCESSED,
)
from adobe_vipm.adobe.dataclasses import ReturnableOrderInfo
from adobe_vipm.adobe.errors import AdobeAPIError
from adobe_vipm.flows.constants import (
    MPT_ORDER_STATUS_COMPLETED,
    MPT_ORDER_STATUS_PROCESSING,
    PARAM_DUE_DATE,
    TEMPLATE_NAME_DELAYED,
)
from adobe_vipm.flows.context import Context
from adobe_vipm.flows.fulfillment.shared import (
    CompleteOrder,
    CreateOrUpdateSubscriptions,
    GetPreviewOrder,
    GetReturnOrders,
    SetOrUpdateCotermNextSyncDates,
    SetupDueDate,
    StartOrderProcessing,
    SubmitNewOrder,
    SubmitReturnOrders,
    SyncAgreement,
    UpdatePrices,
    ValidateDuplicateLines,
    ValidateRenewalWindow,
    send_email_notification,
    send_gc_email_notification,
    set_customer_coterm_date_if_null,
    start_processing_attempt,
)
from adobe_vipm.flows.utils import (
    get_adobe_order_id,
    get_coterm_date,
    get_due_date,
    get_next_sync,
    get_notifications_recipient,
    set_coterm_date,
    set_next_sync,
)


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
def test_send_email_notification(mocker, settings, order_factory, status, subject):
    settings.EXTENSION_CONFIG = {
        "EMAIL_NOTIFICATIONS_ENABLED": "1",
    }
    mocked_mpt_client = mocker.MagicMock()

    mocked_get_rendered_template = mocker.patch(
        "adobe_vipm.flows.fulfillment.shared.get_rendered_template",
        return_value="rendered-template",
    )

    mocked_send_email = mocker.patch("adobe_vipm.flows.fulfillment.shared.send_email")

    order = order_factory(order_id="ORD-1234", status=status)

    send_email_notification(mocked_mpt_client, order)
    mocked_get_rendered_template.assert_called_once_with(mocked_mpt_client, order["id"])

    mocked_send_email.assert_called_once_with(
        [get_notifications_recipient(order)],
        subject,
        "email",
        {
            "order": order,
            "activation_template": "<p>rendered-template</p>\n",
            "api_base_url": settings.MPT_API_BASE_URL,
            "portal_base_url": settings.MPT_PORTAL_BASE_URL,
        },
    )


def test_send_email_notification_no_recipient(mocker, settings, order_factory, caplog):
    settings.EXTENSION_CONFIG = {
        "EMAIL_NOTIFICATIONS_ENABLED": "1",
    }
    mocked_mpt_client = mocker.MagicMock()
    mocker.patch(
        "adobe_vipm.flows.fulfillment.shared.get_notifications_recipient",
        return_value=None,
    )

    mocked_get_rendered_template = mocker.patch(
        "adobe_vipm.flows.fulfillment.shared.get_rendered_template",
    )

    mocked_send_email = mocker.patch("adobe_vipm.flows.fulfillment.shared.send_email")

    order = order_factory(order_id="ORD-1234")

    with caplog.at_level(logging.WARNING):
        send_email_notification(mocked_mpt_client, order)

    assert (
        "Cannot send email notifications "
        f"for order {order['id']}: no recipient found"
    ) in caplog.text

    mocked_get_rendered_template.assert_not_called()
    mocked_send_email.assert_not_called()


@freeze_time("2025-01-01")
def test_start_processing_attempt_first_attempt(
    mocker, settings, order_factory, fulfillment_parameters_factory
):
    order = order_factory()
    updated_order = order_factory(
        fulfillment_parameters=fulfillment_parameters_factory(
            due_date="2025-01-31",
        ),
    )
    mocked_send = mocker.patch(
        "adobe_vipm.flows.fulfillment.shared.send_email_notification"
    )
    mocked_update = mocker.patch(
        "adobe_vipm.flows.fulfillment.shared.update_order",
        return_value=updated_order,
    )

    mocked_client = mocker.MagicMock()

    start_processing_attempt(mocked_client, order)

    mocked_send.assert_called_once_with(mocked_client, updated_order)
    mocked_update.assert_called_once_with(
        mocked_client,
        updated_order["id"],
        parameters=updated_order["parameters"],
    )


@freeze_time("2025-01-01")
def test_start_processing_attempt_other_attempts(
    mocker, order_factory, fulfillment_parameters_factory
):
    mocked_send = mocker.patch(
        "adobe_vipm.flows.fulfillment.shared.send_email_notification"
    )

    mocked_client = mocker.MagicMock()

    order = order_factory(
        fulfillment_parameters=fulfillment_parameters_factory(
            due_date="2024-01-01",
        )
    )

    start_processing_attempt(mocked_client, order)

    mocked_send.assert_not_called()


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
    order = set_customer_coterm_date_if_null(
        mocked_mpt_client, mocked_adobe_client, order
    )
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
    assert (
        set_customer_coterm_date_if_null(mocked_mpt_client, mocked_adobe_client, order)
        == order
    )

    mocked_update_order.assert_not_called()
    mocked_adobe_client.get_customer_assert_not_called()


@freeze_time("2024-01-01")
def test_setup_due_date_for_first_time(
    mocker,
    order_factory,
):
    """
    Tests that the `SetupDueDate` processing step
    setups the fulfillment parameter `dueDate` to now
    if it is not set
    and updates the order to reflect the change.
    """
    order = order_factory()
    mocked_update_order = mocker.patch(
        "adobe_vipm.flows.fulfillment.shared.update_order"
    )

    mocked_client = mocker.MagicMock()
    mocked_next_step = mocker.MagicMock()

    context = Context(order=order, order_id=order["id"])
    step = SetupDueDate()

    assert get_due_date(order) is None

    step(mocked_client, context, mocked_next_step)

    assert get_due_date(context.order) == date(2024, 1, 31)
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
    """
    Tests that the `SetupDueDate` processing step
    fail the order if the current date is more than due date
    parameter
    """
    settings.EXTENSION_CONFIG = {"DUE_DATE_DAYS": "30"}
    order = order_factory(
        fulfillment_parameters=fulfillment_parameters_factory(
            due_date="2024-06-01",
        ),
    )
    mocked_fail = mocker.patch(
        "adobe_vipm.flows.fulfillment.shared.switch_order_to_failed"
    )
    mocked_client = mocker.MagicMock()
    mocked_next_step = mocker.MagicMock()

    context = Context(order=order, order_id=order["id"])
    step = SetupDueDate()

    step(mocked_client, context, mocked_next_step)

    mocked_fail.assert_called_once_with(
        mocked_client,
        context.order,
        "Due date 2024-06-01 for order processing is reached.",
    )
    mocked_next_step.assert_not_called()


@freeze_time("2025-01-01")
def test_setup_due_date_when_parameter_is_missed(
    mocker,
    settings,
    order_factory,
    fulfillment_parameters_factory,
):
    """
    Tests that the `SetupDueDate` processing step
    fail the order if the current date is more than due date
    parameter
    """
    settings.EXTENSION_CONFIG = {"DUE_DATE_DAYS": "30"}
    fulfillment_parameters = fulfillment_parameters_factory()
    fulfillment_parameters = list(
        filter(
            lambda p: p["externalId"] != PARAM_DUE_DATE,
            fulfillment_parameters,
        )
    )
    order = order_factory(
        fulfillment_parameters=fulfillment_parameters,
    )
    mocked_update_order = mocker.patch(
        "adobe_vipm.flows.fulfillment.shared.update_order"
    )

    mocked_client = mocker.MagicMock()
    mocked_next_step = mocker.MagicMock()

    context = Context(order=order, order_id=order["id"])
    step = SetupDueDate()

    assert get_due_date(order) is None

    step(mocked_client, context, mocked_next_step)

    assert get_due_date(context.order) == date(2025, 1, 31)
    mocked_update_order.assert_called_once_with(
        mocked_client,
        context.order_id,
        parameters=context.order["parameters"],
    )
    mocked_next_step.assert_called_once_with(mocked_client, context)


def test_start_order_processing_step(mocker, order_factory):
    """
    Tests that the template for the `Processing` status
    with the name provided during the instantiation of the step class
    is set for the order and the notification email is sent.
    """
    mocked_get_template = mocker.patch(
        "adobe_vipm.flows.fulfillment.shared.get_product_template_or_default",
        return_value={"id": "TPL-1234"},
    )
    mocked_update_order = mocker.patch(
        "adobe_vipm.flows.fulfillment.shared.update_order"
    )
    mocked_send_email = mocker.patch(
        "adobe_vipm.flows.fulfillment.shared.send_email_notification",
    )
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
    mocked_send_email.assert_called_once_with(mocked_client, context.order)
    mocked_next_step.assert_called_once_with(mocked_client, context)


def test_set_processing_template_step_already_set_not_first_attempt(
    mocker, order_factory
):
    """
    Tests that the template for the `Processing` status
    with the name provided during the instantiation of the step class
    is not set for the order if it was already set.
    Also the notification email is not sent since it's not the first attempt.
    """
    mocked_get_template = mocker.patch(
        "adobe_vipm.flows.fulfillment.shared.get_product_template_or_default",
        return_value={"id": "TPL-1234"},
    )
    mocked_update_order = mocker.patch(
        "adobe_vipm.flows.fulfillment.shared.update_order"
    )
    mocked_send_email = mocker.patch(
        "adobe_vipm.flows.fulfillment.shared.send_email_notification",
    )
    mocked_client = mocker.MagicMock()
    mocked_next_step = mocker.MagicMock()

    context = Context(
        order=order_factory(template={"id": "TPL-1234"}),
        due_date=date(2025, 1, 1),
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
    mocked_send_email.assert_not_called()
    mocked_next_step.assert_called_once_with(mocked_client, context)


@freeze_time("2024-05-06")
def test_set_processing_template_to_delayed_in_renewal_win(
    mocker, order_factory, fulfillment_parameters_factory
):
    """
    Tests that the template for the `Processing` status
    that must be used when the processing is delayed due to the renewal window open
    is set.
    """
    mocked_get_template = mocker.patch(
        "adobe_vipm.flows.fulfillment.shared.get_product_template_or_default",
        return_value={"id": "TPL-5678"},
    )
    mocked_update_order = mocker.patch(
        "adobe_vipm.flows.fulfillment.shared.update_order"
    )
    mocked_client = mocker.MagicMock()
    mocked_next_step = mocker.MagicMock()

    order = order_factory(
        fulfillment_parameters=fulfillment_parameters_factory(coterm_date="2024-05-08")
    )

    context = Context(
        order=order,
        order_id=order["id"],
        product_id=order["agreement"]["product"]["id"],
        due_date=date(2025, 1, 1),
    )

    assert "template" not in context.order

    step = StartOrderProcessing("my template")
    step(mocked_client, context, mocked_next_step)

    assert context.order["template"] == {"id": "TPL-5678"}

    mocked_get_template.assert_called_once_with(
        mocked_client,
        context.product_id,
        MPT_ORDER_STATUS_PROCESSING,
        TEMPLATE_NAME_DELAYED,
    )
    mocked_update_order.assert_called_once_with(
        mocked_client,
        context.order_id,
        template={"id": "TPL-5678"},
    )
    mocked_next_step.assert_called_once_with(mocked_client, context)


@freeze_time("2024-05-06")
def test_validate_renewal_window_step(
    mocker, order_factory, fulfillment_parameters_factory
):
    """
    Tests that if the renewal window is not open
    the order processing pipeline continue with the next step.
    """

    mocked_client = mocker.MagicMock()
    mocked_next_step = mocker.MagicMock()

    context = Context(
        order=order_factory(
            fulfillment_parameters=fulfillment_parameters_factory(
                coterm_date="2024-07-08"
            )
        )
    )

    step = ValidateRenewalWindow()
    step(mocked_client, context, mocked_next_step)

    mocked_next_step.assert_called_once_with(mocked_client, context)


@freeze_time("2024-05-06")
def test_validate_renewal_window_step_win_opened(
    mocker,
    order_factory,
    fulfillment_parameters_factory,
    caplog,
):
    """
    Tests that if the renewal window is not open
    the order processing pipeline continue with the next step.
    """

    mocked_client = mocker.MagicMock()
    mocked_next_step = mocker.MagicMock()

    context = Context(
        order=order_factory(
            fulfillment_parameters=fulfillment_parameters_factory(
                coterm_date="2024-05-08"
            )
        )
    )

    step = ValidateRenewalWindow()
    with caplog.at_level(logging.WARNING):
        step(mocked_client, context, mocked_next_step)

    assert (
        f"{context}: Renewal window is open, coterm date is '2024-05-08'" in caplog.text
    )

    mocked_next_step.assert_not_called()


@pytest.mark.parametrize(
    ("coterm_date", "next_sync"),
    [
        ("2025-01-01", None),
        ("2024-12-31", "2026-01-02"),
        (None, "2026-01-02"),
    ],
)
def test_set_or_update_coterm_next_sync_dates_step(
    mocker,
    order_factory,
    adobe_customer_factory,
    coterm_date,
    next_sync,
):
    """
    Tests that the order is updated when either the `cotermDate`
    either the `nextSync` fulfillment parameter are not in sync with
    the adobe customer coterm date.
    """
    mocked_update = mocker.patch("adobe_vipm.flows.fulfillment.shared.update_order")
    customer = adobe_customer_factory(coterm_date="2025-01-01")
    order = order_factory()
    order = set_coterm_date(order, coterm_date)
    order = set_next_sync(order, next_sync)

    context = Context(
        order=order,
        order_id=order["id"],
        adobe_customer_id=customer["customerId"],
        adobe_customer=customer,
    )

    mocked_client = mocker.MagicMock()
    mocked_next_step = mocker.MagicMock()

    step = SetOrUpdateCotermNextSyncDates()

    step(mocked_client, context, mocked_next_step)

    mocked_update.assert_called_once_with(
        mocked_client,
        context.order_id,
        parameters=context.order["parameters"],
    )
    assert get_coterm_date(context.order) == "2025-01-01"
    assert get_next_sync(context.order) == "2025-01-02"
    mocked_next_step.assert_called_once_with(mocked_client, context)


def test_set_or_update_coterm_next_sync_dates_step_are_in_sync(
    mocker,
    order_factory,
    adobe_customer_factory,
):
    """
    Tests that the order is not updated when both the `cotermDate`
    and the `nextSync` fulfillment parameter are in sync with
    the adobe customer coterm date.
    """
    mocked_update = mocker.patch("adobe_vipm.flows.fulfillment.shared.update_order")
    customer = adobe_customer_factory(coterm_date="2025-01-01")
    order = order_factory()
    order = set_coterm_date(order, "2025-01-01")
    order = set_next_sync(order, "2025-01-02")

    context = Context(
        order=order,
        adobe_customer_id=customer["customerId"],
        adobe_customer=customer,
    )

    mocked_client = mocker.MagicMock()
    mocked_next_step = mocker.MagicMock()

    step = SetOrUpdateCotermNextSyncDates()

    step(mocked_client, context, mocked_next_step)

    mocked_update.assert_not_called()
    mocked_next_step.assert_called_once_with(mocked_client, context)


def test_submit_return_orders_step(
    mocker,
    order_factory,
    adobe_order_factory,
    adobe_items_factory,
    settings,
):
    """
    Tests the creation of a return order for a returnable order.
    The newly created return order is still pending of processing by Adobe so
    the processing pipeline will be stopped.
    """
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
        status=STATUS_PROCESSED,
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
        status=STATUS_PENDING,
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
    """
    Tests the creation of a return order for a returnable order.
    The newly created return order is still pending of processing by Adobe so
    the processing pipeline will be stopped.
    """
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
        status=STATUS_PROCESSED,
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
        status=STATUS_PENDING,
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
    """
    Tests the creation of a return order for a returnable order.
    The newly created return order is still pending of processing by Adobe so
    the processing pipeline will be stopped.
    """
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
        status=STATUS_PROCESSED,
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
        status=STATUS_PENDING,
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
    """
    Tests that all return orders previously created have been processed
    and the order processing pipeline will continue.
    """
    api_key = "airtable-token"
    settings.EXTENSION_CONFIG = {
        "AIRTABLE_API_TOKEN": api_key,
        "AIRTABLE_BASES": {"PRD-1111-1111": "base-id"},
    }
    adobe_order_1 = adobe_order_factory(
        order_type="NEW",
        items=adobe_items_factory(quantity=1),
        status=STATUS_PROCESSED,
    )
    ret_info_1 = ReturnableOrderInfo(
        adobe_order_1,
        adobe_order_1["lineItems"][0],
        adobe_order_1["lineItems"][0]["quantity"],
    )
    sku = adobe_order_1["lineItems"][0]["offerId"][:10]

    return_order = adobe_order_factory(
        order_type="RETURN",
        status=STATUS_PROCESSED,
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
    """
    Test the creation of an Adobe new order.
    The Adobe new order id is saved as the vendor external id of the order.
    The created new order is still in processing so the order processing pipeline will stop.
    """
    order = order_factory(deployment_id=None)
    preview_order = adobe_order_factory(order_type=ORDER_TYPE_PREVIEW)
    new_order = adobe_order_factory(order_type=ORDER_TYPE_NEW, status=STATUS_PENDING)

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
    """
    Test the creation of an Adobe new order.
    The Adobe new order id is saved as the vendor external id of the order.
    The created new order is still in processing so the order processing pipeline will stop.
    """
    deployment_id = "deployment-id"

    order = order_factory(deployment_id=deployment_id)
    preview_order = adobe_order_factory(
        order_type=ORDER_TYPE_PREVIEW, deployment_id=deployment_id
    )
    new_order = adobe_order_factory(
        order_type=ORDER_TYPE_NEW,
        status=STATUS_PENDING,
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
    """
    Test that if the NEW order has already been created no new order will be sumbitted to Adobe.
    Furthermore it retrieves the NEW order from Adobe and since it has been processed, the
    order processing pipeline will continue.
    """

    new_order = adobe_order_factory(
        order_type="NEW",
        status=STATUS_PROCESSED,
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
    """
    Test that if the NEW order has already been created no new order will be sumbitted to Adobe.
    Furthermore it retrieves the NEW order from Adobe and since it has been processed, the
    order processing pipeline will continue.
    """

    deployment_id = "deployment-id"

    new_order = adobe_order_factory(
        order_type="NEW",
        status=STATUS_PROCESSED,
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
    """
    Test that if there are no upsize lines in the order
    no NEW order will be placed and the order processing
    pipeline will continue.
    """

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
    """
    Test that if the NEW order has already been created no new order will be sumbitted to Adobe.
    Furthermore it retries the NEW order from Adobe and since its processing status is an error,
    the order will be failed and the processing pipeline will not continue.
    """

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
        ORDER_STATUS_DESCRIPTION[processing_status],
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
    """
    Test that if the NEW order has already been created no new order will be sumbitted to Adobe.
    Furthermore it retries the NEW order from Adobe and since its processing status is unexpected,
    the order will be failed and the processing pipeline will not continue.
    """

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
        "Unexpected status (9999) received from Adobe.",
    )
    mocked_adobe_client.create_preview_order.assert_not_called()
    mocked_adobe_client.create_new_order.assert_not_called()
    mocked_update.assert_not_called()
    mocked_next_step.assert_not_called()


def test_get_return_orders_step(mocker, order_factory, adobe_order_factory):
    """
    Tests the retrieval of return orders for the current order.
    """
    return_order = adobe_order_factory(
        order_type="RETURN",
        status=STATUS_PROCESSED,
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
    """
    Tests the creation of the corresponding subscriptions for new purchased items.
    """
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
            "name": f"Subscription for {order["lines"][0]['item']['name']}",
            "parameters": {
                "fulfillment": [
                    {
                        "externalId": "adobeSKU",
                        "value": adobe_order["lineItems"][0]["offerId"],
                    },
                    {
                        "externalId": "currentQuantity",
                        "value": str(adobe_subscription["currentQuantity"]),
                    },
                    {
                        "externalId": "renewalQuantity",
                        "value": str(
                            adobe_subscription["autoRenewal"]["renewalQuantity"]
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
    """
    Tests that the existing subscription for upsized line is update to reflect
    the actual SKU.
    """
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
    """
    Tests that no subscription will be created or updated if no
    Adobe NEW order has been placed (downsizes only order) and
    the order processing pipeline will continue.
    """

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
    """
    Tests that for expired adobe subscription no subscription is created.
    """
    adobe_order = adobe_order_factory(
        order_type=ORDER_TYPE_NEW,
        items=adobe_items_factory(subscription_id="adobe-sub-id"),
    )
    adobe_subscription = adobe_subscription_factory(
        status=STATUS_ORDER_CANCELLED,
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


def test_update_prices_step(
    mocker, order_factory, adobe_customer_factory, adobe_order_factory
):
    """
    Tests that prices are updated according to actual sku when the customer has no 3yc benefit.
    """
    order = order_factory()
    adobe_customer = adobe_customer_factory()
    adobe_order = adobe_order_factory(order_type=ORDER_TYPE_NEW)
    sku = adobe_order["lineItems"][0]["offerId"]
    mocked_get_prices = mocker.patch(
        "adobe_vipm.flows.fulfillment.shared.get_prices_for_skus",
        return_value={sku: 121.36},
    )
    mocked_update_order = mocker.patch(
        "adobe_vipm.flows.fulfillment.shared.update_order",
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
                "price": {
                    "unitPP": 121.36,
                },
            },
        ],
    )


@freeze_time("2024-11-09 12:30:00")
def test_update_prices_step_3yc(
    mocker,
    order_factory,
    lines_factory,
    adobe_customer_factory,
    adobe_commitment_factory,
    adobe_order_factory,
):
    """
    Tests that prices are updated according to actual sku when the customer has the 3yc benefit.
    """
    line_1 = lines_factory()[0]
    line_2 = lines_factory(line_id=2, item_id=2, external_vendor_id="99999999CA")[0]
    order = order_factory(
        lines=[line_1, line_2],
    )
    commitment = adobe_commitment_factory()
    adobe_customer = adobe_customer_factory(
        commitment=commitment,
    )
    adobe_order = adobe_order_factory(order_type=ORDER_TYPE_NEW)
    sku = adobe_order["lineItems"][0]["offerId"]
    mocked_get_prices = mocker.patch(
        "adobe_vipm.flows.fulfillment.shared.get_prices_for_3yc_skus",
        return_value={sku: 121.36},
    )
    mocked_update_order = mocker.patch(
        "adobe_vipm.flows.fulfillment.shared.update_order",
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
        date.fromisoformat(commitment["startDate"]),
        [sku],
    )
    mocked_update_order.assert_called_once_with(
        mocked_client,
        context.order_id,
        lines=[
            {
                "id": line_1["id"],
                "price": {
                    "unitPP": 121.36,
                },
            },
            {
                "id": line_2["id"],
                "price": {
                    "unitPP": line_2["price"]["unitPP"],
                },
            },
        ],
    )


@freeze_time("2024-01-01")
def test_complete_order_step(mocker, order_factory):
    """
    Tests the right Completed template is set,
    the retry count is reset
    and the order transitions to the Completed status.
    """

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


def test_sync_agreement_step(mocker, order_factory):
    """
    Tests the step call the synchronization of an agreement and then
    continue with the order processing pipeline.
    """
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
        mocked_client,
        [context.agreement_id],
    )

    mocked_next_step.assert_called_once_with(mocked_client, context)


def test_validate_duplicate_lines_step(
    mocker,
    order_factory,
    lines_factory,
):
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
        "The order cannot contain multiple lines for the same item: ITM-1234-1234-1234-0001.",
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
        "The order cannot contain new lines for an existing item: ITM-1234-1234-1234-0010.",
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
    preview_order = adobe_order_factory(
        order_type=ORDER_TYPE_PREVIEW, deployment_id=deployment_id
    )

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
        context.upsize_lines + context.new_lines,
        deployment_id=deployment_id,
    )


def test_get_preview_order_step_order_no_upsize_lines(
    mocker,
    order_factory,
    lines_factory,
):
    """
    Test that if there are no upsize lines in the order
    no PREVIEW order will be retrieved and the order processing
    pipeline will continue.
    """

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
    """
    Test that if there are  upsize lines but the NEW order
    has already been submitted
    no PREVIEW order will be retrieved and the order processing
    pipeline will continue.
    """

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
    """
    Test that if adobe returns an error retrieving the PREVIEW
    order, the order is failed and stop the order processing
    pipeline
    """

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
        mocked_client, context.order, str(error)
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
def test_send_gc_email_notification(mocker, settings, order_factory, status, subject):
    settings.EXTENSION_CONFIG = {
        "EMAIL_NOTIFICATIONS_ENABLED": "1",
        "GC_EMAIL_NOTIFICATIONS_RECIPIENT": "test@mail.com,test1@mail.com",
    }
    mocked_send_email = mocker.patch("adobe_vipm.flows.fulfillment.shared.send_email")

    order = order_factory(order_id="ORD-1234", status=status)

    send_gc_email_notification(order, ["deployment 1"])

    mocked_send_email.assert_called_once_with(
        settings.EXTENSION_CONFIG.get("GC_EMAIL_NOTIFICATIONS_RECIPIENT", "").split(
            ","
        ),
        subject,
        "email",
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


@pytest.mark.parametrize(
    ("status", "subject"),
    [
        (
            "Processing",
            "This order need your attention ORD-1234 for A buyer",
        )
    ],
)
def test_send_gc_email_notification_not_recipient(
    mocker, settings, order_factory, status, subject
):
    settings.EXTENSION_CONFIG = {
        "EMAIL_NOTIFICATIONS_ENABLED": "1",
        "GC_EMAIL_NOTIFICATIONS_RECIPIENT": "",
    }
    mocked_send_email = mocker.patch("adobe_vipm.flows.fulfillment.shared.send_email")

    order = order_factory(order_id="ORD-1234", status=status)

    send_gc_email_notification(order, ["deployment 1"])

    mocked_send_email.assert_not_called()
