import pytest
from freezegun import freeze_time

from adobe_vipm.adobe.constants import (
    ORDER_TYPE_PREVIEW,
    ORDER_TYPE_RENEWAL,
    AdobeOrderStatus,
)
from adobe_vipm.adobe.errors import AdobeAPIError, AdobeProductNotFoundError
from adobe_vipm.adobe.mixins.errors import AdobeCreatePreviewError
from adobe_vipm.flows.constants import (
    ERR_ADOBE_ERROR,
    ERR_DUPLICATED_ITEMS,
    ERR_EARLY_RENEWAL_IN_PROGRESS,
    ERR_EXISTING_ITEMS,
    MARKET_SEGMENT_COMMERCIAL,
    MARKET_SEGMENT_EDUCATION,
    MARKET_SEGMENT_GOVERNMENT,
)
from adobe_vipm.flows.context import Context
from adobe_vipm.flows.validation.shared import (
    GetPreviewOrder,
    ValidateDuplicateLines,
    ValidateNoEarlyRenewal,
)


def test_validate_duplicate_lines_step_duplicates(mocker, order_factory, lines_factory):
    order = order_factory(lines=lines_factory() + lines_factory())
    mocked_client = mocker.MagicMock()
    mocked_next_step = mocker.MagicMock()
    context = Context(order=order)
    step = ValidateDuplicateLines()

    step(mocked_client, context, mocked_next_step)  # act

    assert context.validation_succeeded is False
    error = ERR_DUPLICATED_ITEMS.to_dict(duplicates="ITM-1234-1234-1234-0001")
    assert context.order["error"] == error
    mocked_next_step.assert_not_called()


def test_validate_duplicate_lines_step_existing_lines(mocker, order_factory, lines_factory):
    order = order_factory(lines=lines_factory(line_id=2, item_id=10))
    mocked_client = mocker.MagicMock()
    mocked_next_step = mocker.MagicMock()
    context = Context(order=order)
    step = ValidateDuplicateLines()

    step(mocked_client, context, mocked_next_step)  # act

    assert context.validation_succeeded is False
    error = ERR_EXISTING_ITEMS.to_dict(duplicates="ITM-1234-1234-1234-0010")
    assert context.order["error"] == error
    mocked_next_step.assert_not_called()


def test_validate_duplicate_lines_step(mocker, mock_mpt_client, mock_order):
    mocked_next_step = mocker.MagicMock()
    context = Context(order=mock_order)
    step = ValidateDuplicateLines()

    step(mock_mpt_client, context, mocked_next_step)  # act

    assert context.validation_succeeded is True
    mocked_next_step.assert_called_once_with(mock_mpt_client, context)


def test_validate_duplicate_lines_step_no_lines(mocker, mock_mpt_client, mock_order):
    mock_order["lines"] = []
    mocked_next_step = mocker.MagicMock()
    context = Context(order=mock_order)
    step = ValidateDuplicateLines()

    step(mock_mpt_client, context, mocked_next_step)  # act

    assert context.validation_succeeded is True
    mocked_next_step.assert_called_once_with(mock_mpt_client, context)


@pytest.mark.parametrize(
    "segment",
    [MARKET_SEGMENT_GOVERNMENT, MARKET_SEGMENT_EDUCATION, MARKET_SEGMENT_COMMERCIAL],
)
def test_get_preview_order_step(
    mocker, mock_adobe_client, order_factory, adobe_order_factory, segment, mock_mpt_client
):
    deployment_id = "deployment-id"
    adobe_preview_order = adobe_order_factory(ORDER_TYPE_PREVIEW, deployment_id=deployment_id)
    mock_adobe_client.create_preview_order.return_value = adobe_preview_order
    order = order_factory(deployment_id=deployment_id)
    mocked_next_step = mocker.MagicMock()
    context = Context(
        order=order,
        new_lines=order["lines"],
        order_id="order-id",
        authorization_id="auth-id",
        market_segment=segment,
        product_id="PRD-1234",
        currency="EUR",
    )
    step = GetPreviewOrder()

    step(mock_mpt_client, context, mocked_next_step)  # act

    assert context.validation_succeeded is True
    assert context.adobe_preview_order == adobe_preview_order
    mock_adobe_client.create_preview_order.assert_called_once_with(context)
    mocked_next_step.assert_called_once_with(mock_mpt_client, context)


@pytest.mark.parametrize(
    "segment",
    [MARKET_SEGMENT_GOVERNMENT, MARKET_SEGMENT_EDUCATION, MARKET_SEGMENT_COMMERCIAL],
)
def test_get_preview_order_step_no_deployment(
    mocker, mock_adobe_client, order_factory, adobe_order_factory, mock_mpt_client, segment
):
    deployment_id = None
    adobe_preview_order = adobe_order_factory(ORDER_TYPE_PREVIEW, deployment_id=deployment_id)
    mock_adobe_client.create_preview_order.return_value = adobe_preview_order
    order = order_factory(deployment_id=deployment_id)
    mocked_next_step = mocker.MagicMock()
    context = Context(
        order=order,
        new_lines=order["lines"],
        order_id="order-id",
        authorization_id="auth-id",
        market_segment=segment,
        product_id="PRD-1234",
        currency="EUR",
    )
    step = GetPreviewOrder()

    step(mock_mpt_client, context, mocked_next_step)  # act

    assert context.validation_succeeded is True
    assert context.adobe_preview_order == adobe_preview_order
    mock_adobe_client.create_preview_order.assert_called_once_with(context)
    mocked_next_step.assert_called_once_with(mock_mpt_client, context)


def test_get_preview_order_step_no_lines(mocker, mock_adobe_client, mock_mpt_client, mock_order):
    mock_order["lines"] = []
    mocked_next_step = mocker.MagicMock()
    context = Context(
        order=mock_order,
        upsize_lines=mock_order["lines"],
        authorization_id="auth-id",
    )
    step = GetPreviewOrder()

    step(mock_mpt_client, context, mocked_next_step)  # act

    assert context.validation_succeeded is True
    assert context.adobe_preview_order is None
    mock_adobe_client.create_preview_order.assert_not_called()
    mocked_next_step.assert_called_once_with(mock_mpt_client, context)


def test_get_preview_order_step_api_error(
    mocker, mock_adobe_client, mock_mpt_client, mock_order, adobe_api_error_factory
):
    error = AdobeAPIError(400, adobe_api_error_factory("9999", "unexpected"))
    mock_adobe_client.create_preview_order.side_effect = error
    mocked_next_step = mocker.MagicMock()
    context = Context(
        order=mock_order,
        upsize_lines=mock_order["lines"],
        authorization_id="auth-id",
        market_segment=MARKET_SEGMENT_COMMERCIAL,
    )
    step = GetPreviewOrder()

    step(mock_mpt_client, context, mocked_next_step)  # act

    assert context.validation_succeeded is False
    assert context.order["error"] == ERR_ADOBE_ERROR.to_dict(details=str(error))
    assert context.adobe_preview_order is None
    mocked_next_step.assert_not_called()


def test_get_preview_order_step_product_not_found_error(
    mocker, mock_adobe_client, mock_mpt_client, mock_order
):
    error = AdobeProductNotFoundError("Product not found")
    mock_adobe_client.create_preview_order.side_effect = error
    mocked_next_step = mocker.MagicMock()
    context = Context(
        order=mock_order,
        upsize_lines=mock_order["lines"],
        authorization_id="auth-id",
        market_segment=MARKET_SEGMENT_COMMERCIAL,
    )
    step = GetPreviewOrder()

    step(mock_mpt_client, context, mocked_next_step)  # act

    assert context.validation_succeeded is False
    assert context.order["error"] == ERR_ADOBE_ERROR.to_dict(details=str(error))
    assert context.adobe_preview_order is None
    mocked_next_step.assert_not_called()


def test_get_preview_order_step_adobe_create_preview_order_error(
    mock_adobe_client,
    mock_mpt_client,
    mock_next_step,
    order_factory,
    lines_factory,
):
    order = order_factory(lines=lines_factory(quantity=12, old_quantity=10))
    mock_adobe_client.create_preview_order.side_effect = AdobeCreatePreviewError("error message")
    context = Context(
        order=order,
        adobe_new_order_id=None,
        upsize_lines=order["lines"],
    )
    step = GetPreviewOrder()

    step(mock_mpt_client, context, mock_next_step)  # act

    mock_next_step.assert_not_called()
    assert context.validation_succeeded is False
    assert context.order["error"] == ERR_ADOBE_ERROR.to_dict(details="error message")
    assert context.adobe_preview_order is None


@pytest.fixture
def early_renewal_context(order_factory):
    return Context(
        order=order_factory(),
        authorization_id="AUT-1234-5678",
        adobe_customer_id="a-client-id",
        adobe_customer={"cotermDate": "2027-09-25"},
    )


@freeze_time("2026-09-10 12:30:00")
def test_validate_no_early_renewal_blocks_pending_early_renewal(
    mock_adobe_client, mock_mpt_client, mock_next_step, adobe_order_factory, early_renewal_context
):
    mock_adobe_client.get_orders.return_value = [
        adobe_order_factory(
            ORDER_TYPE_RENEWAL,
            status=AdobeOrderStatus.COMPLETE.value,
            creation_date="2026-09-05T10:00:00Z",
        )
    ]
    step = ValidateNoEarlyRenewal()

    step(mock_mpt_client, early_renewal_context, mock_next_step)  # act

    assert early_renewal_context.validation_succeeded is False
    assert early_renewal_context.order["error"] == ERR_EARLY_RENEWAL_IN_PROGRESS.to_dict()
    mock_adobe_client.get_orders.assert_called_once_with(
        "AUT-1234-5678",
        "a-client-id",
        filters={"order-type": ORDER_TYPE_RENEWAL},
    )
    mock_next_step.assert_not_called()


@freeze_time("2026-09-10 12:30:00")
def test_validate_no_early_renewal_blocks_open_renewal_order(
    mock_adobe_client, mock_mpt_client, mock_next_step, adobe_order_factory, early_renewal_context
):
    early_renewal_context.adobe_customer = {"cotermDate": "2026-09-25"}
    mock_adobe_client.get_orders.return_value = [
        adobe_order_factory(
            ORDER_TYPE_RENEWAL,
            status=AdobeOrderStatus.OPEN.value,
            creation_date="2026-09-08T10:00:00Z",
        )
    ]
    step = ValidateNoEarlyRenewal()

    step(mock_mpt_client, early_renewal_context, mock_next_step)  # act

    assert early_renewal_context.validation_succeeded is False
    assert early_renewal_context.order["error"] == ERR_EARLY_RENEWAL_IN_PROGRESS.to_dict()
    mock_next_step.assert_not_called()


@freeze_time("2026-09-10 12:30:00")
def test_validate_no_early_renewal_ignores_anniversary_auto_renewal(
    mock_adobe_client, mock_mpt_client, mock_next_step, adobe_order_factory, early_renewal_context
):
    early_renewal_context.adobe_customer = {"cotermDate": "2027-09-01"}
    mock_adobe_client.get_orders.return_value = [
        adobe_order_factory(
            ORDER_TYPE_RENEWAL,
            status=AdobeOrderStatus.COMPLETE.value,
            creation_date="2026-09-01T00:10:00Z",
        )
    ]
    step = ValidateNoEarlyRenewal()

    step(mock_mpt_client, early_renewal_context, mock_next_step)  # act

    assert early_renewal_context.validation_succeeded is True
    mock_next_step.assert_called_once_with(mock_mpt_client, early_renewal_context)


@freeze_time("2026-09-10 12:30:00")
def test_validate_no_early_renewal_ignores_orders_outside_lookback(
    mock_adobe_client, mock_mpt_client, mock_next_step, adobe_order_factory, early_renewal_context
):
    mock_adobe_client.get_orders.return_value = [
        adobe_order_factory(
            ORDER_TYPE_RENEWAL,
            status=AdobeOrderStatus.COMPLETE.value,
            creation_date="2026-07-01T10:00:00Z",
        )
    ]
    step = ValidateNoEarlyRenewal()

    step(mock_mpt_client, early_renewal_context, mock_next_step)  # act

    assert early_renewal_context.validation_succeeded is True
    mock_next_step.assert_called_once_with(mock_mpt_client, early_renewal_context)


@freeze_time("2026-09-10 12:30:00")
def test_validate_no_early_renewal_unlocks_after_the_anniversary(
    mock_adobe_client, mock_mpt_client, mock_next_step, adobe_order_factory, early_renewal_context
):
    early_renewal_context.adobe_customer = {"cotermDate": "2027-09-05"}
    mock_adobe_client.get_orders.return_value = [
        adobe_order_factory(
            ORDER_TYPE_RENEWAL,
            status=AdobeOrderStatus.COMPLETE.value,
            creation_date="2026-08-20T10:00:00Z",
        )
    ]
    step = ValidateNoEarlyRenewal()

    step(mock_mpt_client, early_renewal_context, mock_next_step)  # act

    assert early_renewal_context.validation_succeeded is True
    mock_next_step.assert_called_once_with(mock_mpt_client, early_renewal_context)


@freeze_time("2026-09-10 12:30:00")
def test_validate_no_early_renewal_skips_renewal_orders(
    mock_adobe_client,
    mock_mpt_client,
    mock_next_step,
    order_factory,
    order_parameters_factory,
    renewal_payload,
):
    context = Context(
        order=order_factory(
            order_parameters=order_parameters_factory(renewal_payload=renewal_payload)
        ),
        authorization_id="AUT-1234-5678",
        adobe_customer_id="a-client-id",
        adobe_customer={"cotermDate": "2027-09-25"},
    )
    step = ValidateNoEarlyRenewal()

    step(mock_mpt_client, context, mock_next_step)  # act

    assert context.validation_succeeded is True
    mock_adobe_client.get_orders.assert_not_called()
    mock_next_step.assert_called_once_with(mock_mpt_client, context)


def test_validate_no_early_renewal_skips_without_adobe_customer(
    mock_adobe_client, mock_mpt_client, mock_next_step, order_factory
):
    context = Context(order=order_factory())
    step = ValidateNoEarlyRenewal()

    step(mock_mpt_client, context, mock_next_step)  # act

    assert context.validation_succeeded is True
    mock_adobe_client.get_orders.assert_not_called()
    mock_next_step.assert_called_once_with(mock_mpt_client, context)


@freeze_time("2027-02-20 12:30:00")
def test_validate_no_early_renewal_handles_leap_day_coterm(
    mock_adobe_client, mock_mpt_client, mock_next_step, adobe_order_factory, early_renewal_context
):
    early_renewal_context.adobe_customer = {"cotermDate": "2028-02-29"}
    mock_adobe_client.get_orders.return_value = [
        adobe_order_factory(
            ORDER_TYPE_RENEWAL,
            status=AdobeOrderStatus.COMPLETE.value,
            creation_date="2027-02-15T10:00:00Z",
        )
    ]
    step = ValidateNoEarlyRenewal()

    step(mock_mpt_client, early_renewal_context, mock_next_step)  # act

    assert early_renewal_context.validation_succeeded is False
    assert early_renewal_context.order["error"] == ERR_EARLY_RENEWAL_IN_PROGRESS.to_dict()
    mock_next_step.assert_not_called()
