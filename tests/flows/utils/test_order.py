import pytest

from adobe_vipm.flows.constants import OrderType
from adobe_vipm.flows.utils import (
    get_adobe_order_id,
    is_change_order,
    is_configuration_order,
    is_purchase_order,
    is_termination_order,
    is_transfer_order,
    set_adobe_order_id,
)


def test_adobe_order_id(order_factory):
    mock_order = order_factory(external_ids={"vendor": "fake_vendor_id"})

    result = get_adobe_order_id(mock_order)

    assert result == "fake_vendor_id"


def test_set_adobe_order_id(order_factory):
    mock_order = order_factory(external_ids={"vendor": None})

    result = set_adobe_order_id(mock_order, "fake_order_id")

    assert result["externalIds"]["vendor"] == "fake_order_id"


@pytest.mark.parametrize(
    ("order_type", "is_new_customer", "expected_result"),
    [
        (OrderType.PURCHASE, True, True),
        (OrderType.PURCHASE, False, False),
        ("no_purchase_order_type", True, False),
    ],
)
def test_is_purchase_order(order_type, is_new_customer, expected_result, mocker, order_factory):
    mocker.patch("adobe_vipm.flows.utils.order.is_new_customer", return_value=is_new_customer)
    mock_order = order_factory(order_type=order_type)

    result = is_purchase_order(mock_order)

    assert result is expected_result


@pytest.mark.parametrize(
    ("order_type", "is_new_customer", "expected_result"),
    [
        (OrderType.PURCHASE, False, True),
        (OrderType.PURCHASE, True, False),
        ("no_purchase_order_type", False, False),
    ],
)
def test_is_transfer_order(order_type, is_new_customer, expected_result, mocker, order_factory):
    mocker.patch("adobe_vipm.flows.utils.order.is_new_customer", return_value=is_new_customer)
    mock_order = order_factory(order_type=order_type)

    result = is_transfer_order(mock_order)

    assert result is expected_result


@pytest.mark.parametrize(
    ("order_type", "expected_result"),
    [
        (OrderType.CHANGE, True),
        ("no_change_order_type", False),
    ],
)
def test_is_change_order(order_type, expected_result, order_factory):
    mock_order = order_factory(order_type=order_type)

    result = is_change_order(mock_order)

    assert result is expected_result


@pytest.mark.parametrize(
    ("order_type", "expected_result"),
    [
        (OrderType.TERMINATION, True),
        ("no_termination_order_type", False),
    ],
)
def test_is_termination_order(order_type, expected_result, order_factory):
    mock_order = order_factory(order_type=order_type)

    result = is_termination_order(mock_order)

    assert result is expected_result


@pytest.mark.parametrize(
    ("order_type", "expected_result"),
    [
        (OrderType.CONFIGURATION, True),
        ("no_configuration_order_type", False),
    ],
)
def test_is_configuration_order(order_type, expected_result, order_factory):
    mock_order = order_factory(order_type=order_type)

    result = is_configuration_order(mock_order)

    assert result is expected_result
