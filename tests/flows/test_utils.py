from datetime import UTC, date, datetime, timedelta

import pytest

from adobe_vipm.adobe.constants import (
    STATUS_INACTIVE_OR_GENERIC_FAILURE,
    STATUS_PROCESSED,
)
from adobe_vipm.flows.constants import CANCELLATION_WINDOW_DAYS
from adobe_vipm.flows.utils import (
    get_customer_consumables_discount_level,
    get_customer_licenses_discount_level,
    get_transfer_item_sku_by_subscription,
    group_items_by_type,
    is_transferring_item_expired,
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


def test_group_items_by_type_migrated(
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
    new_items = lines_factory(
        line_id=5,
        item_id=5,
        old_quantity=0,
        quantity=8,
        external_vendor_id="sku-new",
    )

    order_items = (
        upsizing_items
        + downsizing_items
        + upsizing_out_of_window
        + downsizing_items_out_of_window
        + new_items
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

    assert groups.upsizing_in_win == new_items
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
    assert order["error"] is None

    order = set_order_error(order, {"id": "ERR-1234", "message": "error_message"})

    order = reset_order_error(order)
    assert order["error"] is None


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
    ],
)
def test_split_phone_number(number, country, expected):
    assert split_phone_number(number, country) == expected


def test_split_phone_number_invalid_number():
    assert split_phone_number("9929292", "ZZ") is None


def test_split_phone_number_no_number():
    assert split_phone_number("", "US") is None


def test_is_transferring_item_expired(adobe_subscription_factory, adobe_items_factory):
    assert (
        is_transferring_item_expired(
            adobe_subscription_factory(
                status=STATUS_PROCESSED, renewal_date=date.today().isoformat()
            )
        )
        is False
    )
    assert (
        is_transferring_item_expired(
            adobe_subscription_factory(status=STATUS_INACTIVE_OR_GENERIC_FAILURE)
        )
        is True
    )

    assert (
        is_transferring_item_expired(
            adobe_items_factory(renewal_date=date.today().isoformat())[0]
        )
        is False
    )
    assert (
        is_transferring_item_expired(
            adobe_items_factory(
                renewal_date=(date.today() + timedelta(days=5)).isoformat()
            )[0]
        )
        is False
    )

    assert (
        is_transferring_item_expired(
            adobe_items_factory(
                renewal_date=(date.today() - timedelta(days=5)).isoformat()
            )[0]
        )
        is True
    )


def test_get_transfer_item_sku_by_subscription(
    adobe_transfer_factory,
    adobe_items_factory,
):
    items = adobe_items_factory(subscription_id="my-awesome-sub")
    transfer = adobe_transfer_factory(items=items)
    assert (
        get_transfer_item_sku_by_subscription(transfer, "my-awesome-sub")
        == items[0]["offerId"]
    )


def test_get_customer_licenses_discount_level(adobe_customer_factory):
    assert (
        get_customer_licenses_discount_level(
            adobe_customer_factory(licenses_discount_level="05")
        )
        == "05"
    )


def test_get_customer_consumables_discount_level(adobe_customer_factory):
    assert (
        get_customer_consumables_discount_level(
            adobe_customer_factory(consumables_discount_level="T2")
        )
        == "T2"
    )
