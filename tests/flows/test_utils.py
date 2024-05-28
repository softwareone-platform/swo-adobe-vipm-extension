from datetime import UTC, datetime, timedelta

import pytest

from adobe_vipm.flows.constants import CANCELLATION_WINDOW_DAYS
from adobe_vipm.flows.utils import (
    group_items_by_type,
    notify_unhandled_exception_in_teams,
    reset_order_error,
    set_order_error,
    split_phone_number,
)


def test_group_items_by_type(
    order_factory,
    order_parameters_factory,
    lines_factory,
    subscriptions_factory,
):
    downsizing_items = lines_factory(
        line_id=1,
        item_id=1,
        old_quantity=10,
        quantity=8,
        external_vendor_id="sku-downsized",
    )
    upsizing_items = lines_factory(
        line_id=2,
        item_id=2,
        old_quantity=10,
        quantity=12,
        external_vendor_id="sku-upsized",
    )
    upsizing_out_of_window = lines_factory(
        line_id=3,
        item_id=3,
        old_quantity=1,
        quantity=5,
        external_vendor_id="sku-upsized-out",
    )

    downsizing_items_out_of_window = lines_factory(
        line_id=4,
        item_id=4,
        old_quantity=10,
        quantity=8,
        external_vendor_id="sku-downsize-out",
    )

    order_items = (
        upsizing_items
        + downsizing_items
        + upsizing_out_of_window
        + downsizing_items_out_of_window
    )

    order_subscriptions = (
        subscriptions_factory(
            subscription_id="SUB-001",
            adobe_subscription_id="sub-1",
            lines=lines_factory(
                line_id=1,
                item_id=1,
                quantity=10,
                external_vendor_id="sku-downsized",
            ),
        )
        + subscriptions_factory(
            subscription_id="SUB-002",
            adobe_subscription_id="sub-2",
            lines=lines_factory(
                line_id=2,
                item_id=2,
                quantity=10,
                external_vendor_id="sku-upsized",
            ),
        )
        + subscriptions_factory(
            subscription_id="SUB-003",
            adobe_subscription_id="sub-3",
            lines=lines_factory(
                line_id=3,
                item_id=3,
                quantity=1,
                external_vendor_id="sku-upsized-out",
            ),
            start_date=datetime.now(UTC) - timedelta(days=CANCELLATION_WINDOW_DAYS + 1),
        )
        + subscriptions_factory(
            subscription_id="SUB-004",
            adobe_subscription_id="sub-4",
            lines=lines_factory(
                line_id=4,
                item_id=4,
                quantity=10,
                external_vendor_id="sku-downsize-out",
            ),
            start_date=datetime.now(UTC) - timedelta(days=CANCELLATION_WINDOW_DAYS + 1),
        )
    )

    order = order_factory(
        order_type="Change",
        lines=order_items,
        order_parameters=order_parameters_factory(),
        subscriptions=order_subscriptions,
    )

    groups = group_items_by_type(order)

    assert groups.upsizing_in_win == upsizing_items
    assert groups.downsizing_in_win == downsizing_items

    assert groups.upsizing_out_win_or_migrated == upsizing_out_of_window
    assert groups.downsizing_out_win_or_migrated == downsizing_items_out_of_window


def test_group_items_by_type_migraterd(
    order_factory,
    transfer_order_parameters_factory,
    lines_factory,
    subscriptions_factory,
):
    downsizing_items = lines_factory(
        line_id=1,
        item_id=1,
        old_quantity=10,
        quantity=8,
        external_vendor_id="sku-downsized",
    )
    upsizing_items = lines_factory(
        line_id=2,
        item_id=2,
        old_quantity=10,
        quantity=12,
        external_vendor_id="sku-upsized",
    )
    upsizing_out_of_window = lines_factory(
        line_id=3,
        item_id=3,
        old_quantity=1,
        quantity=5,
        external_vendor_id="sku-upsized-out",
    )

    downsizing_items_out_of_window = lines_factory(
        line_id=4,
        item_id=4,
        old_quantity=10,
        quantity=8,
        external_vendor_id="sku-downsize-out",
    )

    order_items = (
        upsizing_items
        + downsizing_items
        + upsizing_out_of_window
        + downsizing_items_out_of_window
    )

    order_subscriptions = (
        subscriptions_factory(
            subscription_id="SUB-001",
            adobe_subscription_id="sub-1",
            lines=lines_factory(
                line_id=1,
                item_id=1,
                quantity=10,
                external_vendor_id="sku-downsized",
            ),
        )
        + subscriptions_factory(
            subscription_id="SUB-002",
            adobe_subscription_id="sub-2",
            lines=lines_factory(
                line_id=2,
                item_id=2,
                quantity=10,
                external_vendor_id="sku-upsized",
            ),
        )
        + subscriptions_factory(
            subscription_id="SUB-003",
            adobe_subscription_id="sub-3",
            lines=lines_factory(
                line_id=3,
                item_id=3,
                quantity=1,
                external_vendor_id="sku-upsized-out",
            ),
            start_date=datetime.now(UTC) - timedelta(days=CANCELLATION_WINDOW_DAYS + 1),
        )
        + subscriptions_factory(
            subscription_id="SUB-004",
            adobe_subscription_id="sub-4",
            lines=lines_factory(
                line_id=4,
                item_id=4,
                quantity=10,
                external_vendor_id="sku-downsize-out",
            ),
            start_date=datetime.now(UTC) - timedelta(days=CANCELLATION_WINDOW_DAYS + 1),
        )
    )

    order = order_factory(
        order_type="Change",
        lines=order_items,
        order_parameters=transfer_order_parameters_factory(),
        subscriptions=order_subscriptions,
    )

    groups = group_items_by_type(order)

    assert groups.upsizing_in_win == []
    assert groups.downsizing_in_win == []

    assert (
        groups.upsizing_out_win_or_migrated == upsizing_items + upsizing_out_of_window
    )
    assert (
        groups.downsizing_out_win_or_migrated
        == downsizing_items + downsizing_items_out_of_window
    )


def test_notify_unhandled_exception_in_teams(mocker):
    mocked_send_exc = mocker.patch("adobe_vipm.flows.utils.send_exception")
    notify_unhandled_exception_in_teams(
        "validation",
        "ORD-0000",
        "exception-traceback",
    )

    mocked_send_exc.assert_called_once_with(
        "Order validation unhandled exception!",
        "An unhandled exception has been raised while performing validation "
        "of the order **ORD-0000**:\n\n"
        "```exception-traceback```",
    )


def test_reset_order_error(order_factory):
    order = order_factory()
    order = reset_order_error(order)
    assert "error" not in order

    order = set_order_error(order, {"id": "ERR-1234", "message": "error_message"})

    order = reset_order_error(order)
    assert "error" not in order


@pytest.mark.parametrize(
    ("number", "country", "expected"),
    [
        (
            "+34687787105",
            "ES",
            {
                "prefix": "+34",
                "number": "687787105",
            },
        ),
        (
            "687787105",
            "ES",
            {
                "prefix": "+34",
                "number": "687787105",
            },
        ),
        (
            "+393356297020",
            "IT",
            {
                "prefix": "+39",
                "number": "3356297020",
            },
        ),
        (
            "3356297020",
            "IT",
            {
                "prefix": "+39",
                "number": "3356297020",
            },
        ),
        (
            "+390817434329",
            "IT",
            {
                "prefix": "+39",
                "number": "0817434329",
            },
        ),
        (
            "0817434329",
            "IT",
            {
                "prefix": "+39",
                "number": "0817434329",
            },
        ),
        (
            "+18004449890",
            "US",
            {
                "prefix": "+1",
                "number": "8004449890",
            },
        ),
        (
            "8004449890",
            "US",
            {
                "prefix": "+1",
                "number": "8004449890",
            },
        ),
    ]
)
def test_split_phone_number(number, country, expected):
    assert split_phone_number(number, country) == expected


def test_split_phone_number_invalid_number():
    assert split_phone_number("9929292", "ZZ") is None


def test_split_phone_number_no_number():
    assert split_phone_number("", "US") is None
