import logging

import pytest

from adobe_vipm.flows.errors import MPTAPIError
from adobe_vipm.flows.utils import reset_ordering_parameters_error, strip_trace_id
from adobe_vipm.flows.validation.base import validate_order


def test_validate_transfer_order(
    mocker,
    caplog,
    order_factory,
    transfer_order_parameters_factory,
):
    """Tests the validate order entrypoint function for transfer orders when it validates."""
    order = order_factory(order_parameters=transfer_order_parameters_factory())
    m_client = mocker.MagicMock()

    mocker.patch(
        "adobe_vipm.flows.validation.base.populate_order_info", return_value=order
    )
    m_validate_transfer = mocker.patch(
        "adobe_vipm.flows.validation.base.validate_transfer",
        return_value=(False, order),
    )

    m_adobe_cli = mocker.MagicMock()
    mocker.patch(
        "adobe_vipm.flows.validation.base.get_adobe_client", return_value=m_adobe_cli
    )

    with caplog.at_level(logging.INFO):
        assert validate_order(m_client, order) == order

    assert caplog.records[0].message == (
        f"Validation of order {order['id']} succeeded without errors"
    )

    m_validate_transfer.assert_called_once_with(
        m_client,
        m_adobe_cli,
        reset_ordering_parameters_error(order),
    )


def test_validate_transfer_order_no_validate(
    mocker,
    caplog,
    order_factory,
    transfer_order_parameters_factory,
):
    """Tests the validate order entrypoint function for transfers when doesn't validate."""
    mocker.patch("adobe_vipm.flows.validation.base.get_adobe_client")
    order = order_factory(order_parameters=transfer_order_parameters_factory())
    m_client = mocker.MagicMock()

    mocker.patch(
        "adobe_vipm.flows.validation.base.populate_order_info",
        return_value=reset_ordering_parameters_error(order),
    )

    mocker.patch(
        "adobe_vipm.flows.validation.base.validate_transfer",
        return_value=(True, order),
    )

    with caplog.at_level(logging.INFO):
        validate_order(m_client, order)

    assert caplog.records[0].message == (
        f"Validation of order {order['id']} succeeded with errors"
    )


def test_validate_order_exception(mocker, mpt_error_factory, order_factory):
    error_data = mpt_error_factory(500, "Internal Server Error", "Oops!")
    error = MPTAPIError(500, error_data)
    mocked_notify = mocker.patch(
        "adobe_vipm.flows.validation.base.notify_unhandled_exception_in_teams"
    )
    mocker.patch(
        "adobe_vipm.flows.validation.base.validate_purchase_order",
        side_effect=error,
    )
    order = order_factory(order_id="ORD-VVVV")
    with pytest.raises(MPTAPIError):
        validate_order(mocker.MagicMock(), order)

    process, order_id, tb = mocked_notify.mock_calls[0].args
    assert process == "validation"
    assert order_id == order["id"]
    assert strip_trace_id(str(error)) in tb


def test_validate_change_order(mocker, caplog, order_factory):
    """Tests the validate order entrypoint function when it validates."""
    order = order_factory(order_type="Change")

    mocked_client = mocker.MagicMock()
    mocked_validate = mocker.patch(
        "adobe_vipm.flows.validation.base.validate_change_order",
        return_value=(False, order),
    )

    with caplog.at_level(logging.INFO):
        assert validate_order(mocked_client, order) == order

    assert caplog.records[0].message == (
        f"Validation of order {order['id']} succeeded without errors"
    )

    mocked_validate.assert_called_once_with(mocked_client, order)


def test_validate_purchase_order(mocker, caplog, order_factory):
    """Tests the validate order entrypoint function when it validates."""
    order = order_factory(order_type="Purchase")

    mocked_client = mocker.MagicMock()
    mocked_validate = mocker.patch(
        "adobe_vipm.flows.validation.base.validate_purchase_order",
        return_value=(False, order),
    )

    with caplog.at_level(logging.INFO):
        assert validate_order(mocked_client, order) == order

    assert caplog.records[0].message == (
        f"Validation of order {order['id']} succeeded without errors"
    )

    mocked_validate.assert_called_once_with(mocked_client, order)


def test_validate_termination_order(mocker, caplog, order_factory):
    """Tests the validate order entrypoint function when it validates."""
    order = order_factory(order_type="Termination")

    mocked_client = mocker.MagicMock()
    mocked_validate = mocker.patch(
        "adobe_vipm.flows.validation.base.validate_termination_order",
        return_value=(False, order),
    )

    with caplog.at_level(logging.INFO):
        assert validate_order(mocked_client, order) == order

    assert caplog.records[0].message == (
        f"Validation of order {order['id']} succeeded without errors"
    )

    mocked_validate.assert_called_once_with(mocked_client, order)
