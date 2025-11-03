import pytest

from adobe_vipm.flows.constants import OrderType, Param
from adobe_vipm.flows.errors import MPTAPIError
from adobe_vipm.flows.validation import base
from adobe_vipm.flows.validation.base import (
    copy_order_without_errors,
    get_purchase_order_validator,
    get_validator_by_order_type,
    validate_order,
)
from adobe_vipm.flows.validation.change import validate_change_order
from adobe_vipm.flows.validation.purchase import validate_purchase_order
from adobe_vipm.flows.validation.termination import validate_termination_order
from adobe_vipm.flows.validation.transfer import validate_reseller_change, validate_transfer


def test_copy_order_without_errors(mocker, mock_order):
    fake_error = {"id": "fake_id", "message": "fake_error"}
    mock_order["error"] = fake_error
    mock_order["parameters"][Param.PHASE_ORDERING][0]["error"] = fake_error
    spy_reset_ordering_parameters_error = mocker.spy(base, "reset_ordering_parameters_error")
    spy_reset_order_error = mocker.spy(base, "reset_order_error")

    result = copy_order_without_errors(mock_order)

    assert result != mock_order
    assert mock_order["parameters"][Param.PHASE_ORDERING][0]["error"] == fake_error
    assert result["parameters"][Param.PHASE_ORDERING][0].get("error") is None
    assert mock_order["error"] == fake_error
    assert result["error"] is None
    spy_reset_ordering_parameters_error.assert_called_once()
    spy_reset_order_error.assert_called_once()


def test_get_purchase_order_validator_validate_transfer(mocker, mock_order):
    mock_is_migrate_customer = mocker.patch(
        "adobe_vipm.flows.validation.base.is_migrate_customer", return_value=True
    )
    spy_is_reseller_change = mocker.spy(base, "is_reseller_change")

    result = get_purchase_order_validator(mock_order)

    assert result == validate_transfer
    mock_is_migrate_customer.assert_called_once()
    spy_is_reseller_change.assert_not_called()


def test_get_purchase_order_validator_validate_reseller_order(mocker, mock_order):
    mock_is_migrate_customer = mocker.patch(
        "adobe_vipm.flows.validation.base.is_migrate_customer", return_value=False
    )
    mock_is_reseller_change = mocker.patch(
        "adobe_vipm.flows.validation.base.is_reseller_change", return_value=True
    )

    result = get_purchase_order_validator(mock_order)

    assert result == validate_reseller_change
    mock_is_migrate_customer.assert_called_once()
    mock_is_reseller_change.assert_called_once()


def test_get_purchase_order_validator_validate_purchase_order(mocker, mock_order):
    mock_is_migrate_customer = mocker.patch(
        "adobe_vipm.flows.validation.base.is_migrate_customer", return_value=False
    )
    mock_is_reseller_change = mocker.patch(
        "adobe_vipm.flows.validation.base.is_reseller_change", return_value=False
    )

    result = get_purchase_order_validator(mock_order)

    assert result == validate_purchase_order
    mock_is_migrate_customer.assert_called_once()
    mock_is_reseller_change.assert_called_once()


@pytest.mark.parametrize(
    ("order_type", "expected_validator"),
    [
        (OrderType.CHANGE, validate_change_order),
        (OrderType.TERMINATION, validate_termination_order),
        ("no_type", None),
    ],
)
def test_get_validator_by_order_type(order_type, expected_validator, order_factory):
    mock_order = order_factory(order_type=order_type)

    result = get_validator_by_order_type(mock_order)

    assert result == expected_validator


def test_get_validator_by_order_type_purchase_order(mocker, order_factory):
    expected_validator = mocker.Mock()
    mock_get_purchase_order_validator = mocker.patch(
        "adobe_vipm.flows.validation.base.get_purchase_order_validator",
        return_value=expected_validator,
    )
    mock_purchase_order = order_factory(order_type=OrderType.PURCHASE)

    result = get_validator_by_order_type(mock_purchase_order)

    assert result == expected_validator
    mock_get_purchase_order_validator.assert_called_once_with(mock_purchase_order)


def test_validate_order(mocker, mock_mpt_client, mock_order, caplog):
    mock_copy_order_without_errors = mocker.patch(
        "adobe_vipm.flows.validation.base.copy_order_without_errors"
    )
    mock_get_validator_by_order_type = mocker.patch(
        "adobe_vipm.flows.validation.base.get_validator_by_order_type",
        return_value=mocker.Mock(return_value=(False, mock_order)),
    )

    validated_order = validate_order(mock_mpt_client, mock_order)

    assert validated_order == mock_order
    mock_copy_order_without_errors.assert_called_once()
    mock_get_validator_by_order_type.assert_called_once()
    assert "Validation of order ORD-0792-5000-2253-4210 succeeded without errors" in caplog.text


def test_validate_order_no_validator(mocker, mock_mpt_client, mock_order, caplog):
    mock_copy_order_without_errors = mocker.patch(
        "adobe_vipm.flows.validation.base.copy_order_without_errors", return_value=mock_order
    )
    mock_get_validator_by_order_type = mocker.patch(
        "adobe_vipm.flows.validation.base.get_validator_by_order_type", return_value=None
    )

    validated_order = validate_order(mock_mpt_client, mock_order)

    assert validated_order == mock_order
    mock_copy_order_without_errors.assert_called_once()
    mock_get_validator_by_order_type.assert_called_once()
    assert "Validation of order ORD-0792-5000-2253-4210 succeeded without errors" in caplog.text


def test_validate_order_no_validate(mocker, mock_mpt_client, mock_order, caplog):
    mock_copy_order_without_errors = mocker.patch(
        "adobe_vipm.flows.validation.base.copy_order_without_errors", return_value=mock_order
    )
    mock_get_validator_by_order_type = mocker.patch(
        "adobe_vipm.flows.validation.base.get_validator_by_order_type",
        return_value=mocker.Mock(return_value=(True, mock_order)),
    )

    validated_order = validate_order(mock_mpt_client, mock_order)

    assert validated_order == mock_order
    mock_copy_order_without_errors.assert_called_once()
    mock_get_validator_by_order_type.assert_called_once()
    assert "Validation of order ORD-0792-5000-2253-4210 succeeded with errors" in caplog.text


def test_validate_order_exception(mocker, mock_mpt_client, mpt_error_factory, mock_order):
    mock_copy_order_without_errors = mocker.patch(
        "adobe_vipm.flows.validation.base.copy_order_without_errors", return_value=mock_order
    )
    mpt_api_error = MPTAPIError(500, mpt_error_factory(500, "Internal Server Error", "Oops!"))
    mock_get_validator_by_order_type = mocker.patch(
        "adobe_vipm.flows.validation.base.get_validator_by_order_type",
        return_value=mocker.Mock(side_effect=mpt_api_error),
    )
    mock_strip_trace_id = mocker.patch(
        "adobe_vipm.flows.validation.base.strip_trace_id", return_value="fake_trace_id"
    )
    mock_notify_unhandled_exception_in_teams = mocker.patch(
        "adobe_vipm.flows.validation.base.notify_unhandled_exception_in_teams"
    )

    with pytest.raises(MPTAPIError):
        validate_order(mock_mpt_client, mock_order)

    mock_copy_order_without_errors.assert_called_once()
    mock_get_validator_by_order_type.assert_called_once()
    mock_notify_unhandled_exception_in_teams.assert_called_once_with(
        "validation", "ORD-0792-5000-2253-4210", "fake_trace_id"
    )
    mock_strip_trace_id.assert_called_once()
