from adobe_vipm.flows.context import Context
from adobe_vipm.flows.validation.shared import (
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


def test_validate_duplicate_lines_step_existing_lines(mocker, order_factory, lines_factory):
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
