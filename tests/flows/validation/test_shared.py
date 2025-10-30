import pytest

from adobe_vipm.adobe.constants import ORDER_TYPE_PREVIEW
from adobe_vipm.adobe.errors import AdobeAPIError, AdobeProductNotFoundError
from adobe_vipm.flows.constants import (
    ERR_ADOBE_ERROR,
    ERR_DUPLICATED_ITEMS,
    ERR_EXISTING_ITEMS,
    MARKET_SEGMENT_COMMERCIAL,
    MARKET_SEGMENT_EDUCATION,
    MARKET_SEGMENT_GOVERNMENT,
)
from adobe_vipm.flows.context import Context
from adobe_vipm.flows.validation.shared import (
    GetPreviewOrder,
    ValidateDuplicateLines,
)


def test_validate_duplicate_lines_step_duplicates(mocker, order_factory, lines_factory):
    order = order_factory(lines=lines_factory() + lines_factory())

    mocked_client = mocker.MagicMock()
    mocked_next_step = mocker.MagicMock()
    context = Context(order=order)

    step = ValidateDuplicateLines()
    step(mocked_client, context, mocked_next_step)

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
    step(mocked_client, context, mocked_next_step)

    assert context.validation_succeeded is False
    error = ERR_EXISTING_ITEMS.to_dict(duplicates="ITM-1234-1234-1234-0010")
    assert context.order["error"] == error
    mocked_next_step.assert_not_called()


def test_validate_duplicate_lines_step(mocker, mock_mpt_client, mock_order):
    mocked_next_step = mocker.MagicMock()
    context = Context(order=mock_order)

    step = ValidateDuplicateLines()
    step(mock_mpt_client, context, mocked_next_step)

    assert context.validation_succeeded is True
    mocked_next_step.assert_called_once_with(mock_mpt_client, context)


def test_validate_duplicate_lines_step_no_lines(mocker, mock_mpt_client, mock_order):
    mock_order["lines"] = []
    mocked_next_step = mocker.MagicMock()
    context = Context(order=mock_order)

    step = ValidateDuplicateLines()
    step(mock_mpt_client, context, mocked_next_step)

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
        deployment_id=deployment_id,
    )

    step = GetPreviewOrder()
    step(mock_mpt_client, context, mocked_next_step)

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
        deployment_id=deployment_id,
    )

    step = GetPreviewOrder()
    step(mock_mpt_client, context, mocked_next_step)

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
    step(mock_mpt_client, context, mocked_next_step)

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
    step(mock_mpt_client, context, mocked_next_step)

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
    step(mock_mpt_client, context, mocked_next_step)

    assert context.validation_succeeded is False
    assert context.order["error"] == ERR_ADOBE_ERROR.to_dict(details=str(error))
    assert context.adobe_preview_order is None
    mocked_next_step.assert_not_called()
