import pytest

from adobe_vipm.adobe.constants import ORDER_TYPE_PREVIEW
from adobe_vipm.adobe.errors import AdobeAPIError
from adobe_vipm.flows.constants import (
    ERR_ADOBE_ERROR,
    FAKE_CUSTOMERS_IDS,
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
    """
    Tests that if duplicate lines (same Item ID) are present in the order
    an error is set and the validation pipeline stops.
    """
    order = order_factory(lines=lines_factory() + lines_factory())

    mocked_client = mocker.MagicMock()
    mocked_next_step = mocker.MagicMock()
    context = Context(order=order)

    step = ValidateDuplicateLines()
    step(mocked_client, context, mocked_next_step)

    assert context.validation_succeeded is False
    assert context.order["error"]["id"] == "VIPMV009"
    mocked_next_step.assert_not_called()


def test_validate_duplicate_lines_step_existing_lines(
    mocker, order_factory, lines_factory
):
    order = order_factory(lines=lines_factory(line_id=2, item_id=10))

    mocked_client = mocker.MagicMock()
    mocked_next_step = mocker.MagicMock()
    context = Context(order=order)

    step = ValidateDuplicateLines()
    step(mocked_client, context, mocked_next_step)

    assert context.validation_succeeded is False
    assert context.order["error"]["id"] == "VIPMV010"
    mocked_next_step.assert_not_called()


def test_validate_duplicate_lines_step(mocker, order_factory):
    order = order_factory()

    mocked_client = mocker.MagicMock()
    mocked_next_step = mocker.MagicMock()
    context = Context(order=order)

    step = ValidateDuplicateLines()
    step(mocked_client, context, mocked_next_step)

    assert context.validation_succeeded is True
    mocked_next_step.assert_called_once_with(mocked_client, context)


def test_validate_duplicate_lines_step_no_lines(mocker, order_factory):
    order = order_factory()
    order["lines"] = []

    mocked_client = mocker.MagicMock()
    mocked_next_step = mocker.MagicMock()
    context = Context(order=order)

    step = ValidateDuplicateLines()
    step(mocked_client, context, mocked_next_step)

    assert context.validation_succeeded is True
    mocked_next_step.assert_called_once_with(mocked_client, context)


@pytest.mark.parametrize(
    "segment",
    [MARKET_SEGMENT_GOVERNMENT, MARKET_SEGMENT_EDUCATION, MARKET_SEGMENT_COMMERCIAL],
)
def test_get_preview_order_step(mocker, order_factory, adobe_order_factory, segment):
    deployment_id = "deployment-id"
    adobe_preview_order = adobe_order_factory(ORDER_TYPE_PREVIEW, deployment_id=deployment_id)
    mocked_adobe_client = mocker.MagicMock()
    mocked_adobe_client.create_preview_order.return_value = adobe_preview_order
    mocker.patch(
        "adobe_vipm.flows.validation.shared.get_adobe_client",
        return_value=mocked_adobe_client,
    )

    order = order_factory(
        deployment_id=deployment_id,
    )

    mocked_client = mocker.MagicMock()
    mocked_next_step = mocker.MagicMock()
    context = Context(
        order=order,
        upsize_lines=order["lines"],
        order_id="order-id",
        authorization_id="auth-id",
        market_segment=segment,
        product_id="PRD-1234",
        currency="EUR",
    )

    step = GetPreviewOrder()
    step(mocked_client, context, mocked_next_step)

    assert context.validation_succeeded is True
    assert context.adobe_preview_order == adobe_preview_order

    mocked_adobe_client.create_preview_order.assert_called_once_with(
        context.authorization_id,
        FAKE_CUSTOMERS_IDS[segment],
        context.order_id,
        context.upsize_lines,
        deployment_id=deployment_id,
    )
    mocked_next_step.assert_called_once_with(mocked_client, context)


@pytest.mark.parametrize(
    "segment",
    [MARKET_SEGMENT_GOVERNMENT, MARKET_SEGMENT_EDUCATION, MARKET_SEGMENT_COMMERCIAL],
)
def test_get_preview_order_step_no_deployment(mocker, order_factory, adobe_order_factory, segment):
    deployment_id = None
    adobe_preview_order = adobe_order_factory(ORDER_TYPE_PREVIEW, deployment_id=deployment_id)
    mocked_adobe_client = mocker.MagicMock()
    mocked_adobe_client.create_preview_order.return_value = adobe_preview_order
    mocker.patch(
        "adobe_vipm.flows.validation.shared.get_adobe_client",
        return_value=mocked_adobe_client,
    )

    order = order_factory(
        deployment_id=deployment_id,
    )

    mocked_client = mocker.MagicMock()
    mocked_next_step = mocker.MagicMock()
    context = Context(
        order=order,
        upsize_lines=order["lines"],
        order_id="order-id",
        authorization_id="auth-id",
        market_segment=segment,
        product_id="PRD-1234",
        currency="EUR",
    )

    step = GetPreviewOrder()
    step(mocked_client, context, mocked_next_step)

    assert context.validation_succeeded is True
    assert context.adobe_preview_order == adobe_preview_order

    mocked_adobe_client.create_preview_order.assert_called_once_with(
        context.authorization_id,
        FAKE_CUSTOMERS_IDS[segment],
        context.order_id,
        context.upsize_lines,
        deployment_id=deployment_id,
    )
    mocked_next_step.assert_called_once_with(mocked_client, context)


def test_get_preview_order_step_no_lines(mocker, order_factory):
    mocked_adobe_client = mocker.MagicMock()
    mocker.patch(
        "adobe_vipm.flows.validation.shared.get_adobe_client",
        return_value=mocked_adobe_client,
    )
    order = order_factory()
    order["lines"] = []

    mocked_client = mocker.MagicMock()
    mocked_next_step = mocker.MagicMock()

    context = Context(
        order=order,
        upsize_lines=order["lines"],
        authorization_id="auth-id",
    )

    step = GetPreviewOrder()
    step(mocked_client, context, mocked_next_step)

    assert context.validation_succeeded is True
    assert context.adobe_preview_order is None

    mocked_adobe_client.create_preview_order.assert_not_called()
    mocked_next_step.assert_called_once_with(mocked_client, context)


def test_get_preview_order_step_api_error(
    mocker, order_factory, adobe_api_error_factory
):
    error = AdobeAPIError(400, adobe_api_error_factory("9999", "unexpected"))
    mocked_adobe_client = mocker.MagicMock()
    mocked_adobe_client.create_preview_order.side_effect = error
    mocker.patch(
        "adobe_vipm.flows.validation.shared.get_adobe_client",
        return_value=mocked_adobe_client,
    )
    order = order_factory()

    mocked_client = mocker.MagicMock()
    mocked_next_step = mocker.MagicMock()

    context = Context(
        order=order,
        upsize_lines=order["lines"],
        authorization_id="auth-id",
        market_segment=MARKET_SEGMENT_COMMERCIAL,
    )

    step = GetPreviewOrder()
    step(mocked_client, context, mocked_next_step)

    assert context.validation_succeeded is False
    assert context.order["error"] == ERR_ADOBE_ERROR.to_dict(details=str(error))
    assert context.adobe_preview_order is None

    mocked_next_step.assert_not_called()
