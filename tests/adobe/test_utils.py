import logging

import pytest

from adobe_vipm.adobe.utils import (
    get_line_remaining_quantity,
    get_returned_quantity,
    is_flex_discount_applied,
)


@pytest.mark.parametrize(
    ("flex_discount", "expected_result"),
    [
        ({"code": "BLACK_FRIDAY", "result": "SUCCESS"}, True),
        # A missing result is not a confirmation.
        ({"code": "BLACK_FRIDAY"}, False),
        ({"code": "BLACK_FRIDAY", "result": "NOT_APPLICABLE"}, False),
    ],
)
def test_is_flex_discount_applied(flex_discount, expected_result):
    result = is_flex_discount_applied(flex_discount)

    assert result is expected_result


@pytest.mark.parametrize(
    ("line_item", "expected_quantity"),
    [
        ({"extLineItemNumber": 1, "quantity": 15, "remainingQuantity": 10}, 10),
        ({"extLineItemNumber": 1, "quantity": 15, "remainingQuantity": 0}, 0),
        ({"extLineItemNumber": 1, "quantity": 15}, 15),
    ],
)
def test_get_line_remaining_quantity(line_item, expected_quantity):
    result = get_line_remaining_quantity(line_item)

    assert result == expected_quantity


def test_get_line_remaining_quantity_logs_missing_field(caplog):
    line_item = {"extLineItemNumber": 1, "offerId": "65304520CA01A12", "quantity": 15}

    with caplog.at_level(logging.WARNING):
        get_line_remaining_quantity(line_item)  # act

    assert "has no remainingQuantity" in caplog.text


def test_get_returned_quantity():
    return_orders = [
        {"referenceOrderId": "P1", "lineItems": [{"extLineItemNumber": 1, "quantity": 15}]},
        {"referenceOrderId": "P1", "lineItems": [{"extLineItemNumber": 1, "quantity": 5}]},
        {"referenceOrderId": "P1", "lineItems": [{"extLineItemNumber": 2, "quantity": 7}]},
        {"referenceOrderId": "P2", "lineItems": [{"extLineItemNumber": 1, "quantity": 9}]},
    ]

    result = get_returned_quantity(return_orders, "P1", {"extLineItemNumber": 1})

    assert result == 20
