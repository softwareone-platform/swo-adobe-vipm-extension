import logging

import pytest

from adobe_vipm.flows.errors import MPTAPIError
from adobe_vipm.flows.utils.parameter import reset_ordering_parameters_error
from adobe_vipm.flows.validation.base import validate_order


def test_validate_transfer_order(
    mocker,
    mock_mpt_client,
    caplog,
    order_factory,
    transfer_order_parameters_factory,
):
    order = order_factory(order_parameters=transfer_order_parameters_factory())
    mock_validate_transfer = mocker.patch(
        "adobe_vipm.flows.validation.base.validate_transfer", return_value=(False, order)
    )

    with caplog.at_level(logging.INFO):
        validated_order = validate_order(mock_mpt_client, order)

    assert validated_order == order
    assert caplog.records[0].message == (
        f"Validation of order {order['id']} succeeded without errors"
    )
    mock_validate_transfer.assert_called_once_with(
        mock_mpt_client, reset_ordering_parameters_error(order)
    )


def test_validate_transfer_order_no_validate(
    mocker,
    mock_mpt_client,
    caplog,
    order_factory,
    transfer_order_parameters_factory,
):
    order = order_factory(order_parameters=transfer_order_parameters_factory())
    mocker.patch(
        "adobe_vipm.flows.validation.base.validate_transfer",
        return_value=(True, order),
    )

    with caplog.at_level(logging.INFO):
        validate_order(mock_mpt_client, order)

    assert caplog.records[0].message == f"Validation of order {order['id']} succeeded with errors"


def test_validate_order_exception(mocker, mock_mpt_client, mpt_error_factory, order_factory):
    mocked_notify = mocker.patch(
        "adobe_vipm.flows.validation.base.notify_unhandled_exception_in_teams"
    )
    mock_error = MPTAPIError(500, mpt_error_factory(500, "Internal Server Error", "Oops!"))
    mocker.patch("adobe_vipm.flows.validation.base.validate_purchase_order", side_effect=mock_error)
    mocker.patch("adobe_vipm.flows.validation.base.strip_trace_id", return_value="fake_trace_id")
    order = order_factory(order_id="ORD-VVVV")

    with pytest.raises(MPTAPIError):
        validate_order(mock_mpt_client, order)

    mocked_notify.assert_called_once_with("validation", order["id"], "fake_trace_id")


def test_validate_change_order(mocker, mock_mpt_client, caplog, order_factory):
    order = order_factory(order_type="Change")
    mocked_validate = mocker.patch(
        "adobe_vipm.flows.validation.base.validate_change_order", return_value=(False, order)
    )

    with caplog.at_level(logging.INFO):
        validated_order = validate_order(mock_mpt_client, order)

    assert validated_order == order
    assert caplog.records[0].message == (
        f"Validation of order {order['id']} succeeded without errors"
    )
    mocked_validate.assert_called_once_with(mock_mpt_client, reset_ordering_parameters_error(order))


def test_validate_purchase_order(mocker, mock_mpt_client, caplog, order_factory):
    order = order_factory(order_type="Purchase")
    mocked_validate = mocker.patch(
        "adobe_vipm.flows.validation.base.validate_purchase_order", return_value=(False, order)
    )

    with caplog.at_level(logging.INFO):
        validated_order = validate_order(mock_mpt_client, order)

    assert validated_order == order
    assert caplog.records[0].message == (
        f"Validation of order {order['id']} succeeded without errors"
    )
    mocked_validate.assert_called_once_with(mock_mpt_client, reset_ordering_parameters_error(order))


def test_validate_termination_order(mocker, mock_mpt_client, caplog, order_factory):
    order = order_factory(order_type="Termination")
    mocked_validate = mocker.patch(
        "adobe_vipm.flows.validation.base.validate_termination_order",
        return_value=(False, order),
    )

    with caplog.at_level(logging.INFO):
        validated_order = validate_order(mock_mpt_client, order)

    assert validated_order == order
    assert caplog.records[0].message == (
        f"Validation of order {order['id']} succeeded without errors"
    )
    mocked_validate.assert_called_once_with(mock_mpt_client, reset_ordering_parameters_error(order))


def test_validate_reseller_change_order(
    mocker,
    mock_mpt_client,
    caplog,
    order_factory,
    reseller_change_order_parameters_factory,
):
    order = order_factory(order_parameters=reseller_change_order_parameters_factory())
    mock_validate_transfer = mocker.patch(
        "adobe_vipm.flows.validation.base.validate_reseller_change", return_value=(False, order)
    )

    with caplog.at_level(logging.INFO):
        validated_order = validate_order(mock_mpt_client, order)

    assert validated_order == order
    assert caplog.records[0].message == (
        f"Validation of order {order['id']} succeeded without errors"
    )
    mock_validate_transfer.assert_called_once_with(
        mock_mpt_client, reset_ordering_parameters_error(order)
    )
