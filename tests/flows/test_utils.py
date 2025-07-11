from datetime import date, timedelta

import pytest

from adobe_vipm.adobe.constants import AdobeStatus
from adobe_vipm.flows.utils import (
    get_customer_consumables_discount_level,
    get_customer_licenses_discount_level,
    get_transfer_item_sku_by_subscription,
    is_transferring_item_expired,
    notify_agreement_unhandled_exception_in_teams,
    notify_missing_prices,
    notify_not_updated_subscriptions,
    notify_unhandled_exception_in_teams,
    reset_order_error,
    set_order_error,
    split_phone_number,
)


def test_notify_unhandled_exception_in_teams(mocker):
    mocked_send_exc = mocker.patch("adobe_vipm.flows.utils.notification.send_exception")
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


def test_notify_agreement_unhandled_exception_in_teams(mocker):
    mocked_send_exc = mocker.patch("adobe_vipm.flows.utils.notification.send_exception")
    notify_agreement_unhandled_exception_in_teams(
        "AGR-0000",
        "exception-traceback",
    )

    mocked_send_exc.assert_called_once_with(
        "Agreement unhandled exception!",
        "An unhandled exception has been raised "
        "of the agreement **AGR-0000**:\n\n"
        "```exception-traceback```",
    )


def test_notify_missing_prices(mocker):
    mocked_send_exc = mocker.patch("adobe_vipm.flows.utils.notification.send_exception")
    notify_missing_prices("AGR-0000", ["65504578CA01A12"], "65504575CA01A12", "USD", None)

    mocked_send_exc.assert_called_once_with(
        "Missing prices detected",
        "Missing prices detected in agreement **AGR-0000**\n\n"
        "The following SKUs don't have regular prices available:\n"
        "- Product ID: 65504575CA01A12\n"
        "- Currency: USD\n"
        "- SKUs:\n  - 65504578CA01A12\n",
    )


def test_notify_not_updated_subscriptions_no_updated_subs(mocker):
    mocked_send_exc = mocker.patch("adobe_vipm.flows.utils.notification.send_exception")
    notify_not_updated_subscriptions(
        order_id="ORD-1234",
        error_message="Some error occurred",
        updated_subscriptions=[],
        product_id="PROD-5678",
    )

    expected_message = (
        "Some error occurred\n\n"
        "The order **ORD-1234**\n\n"
        "has failed changing the auto-renewal status\n\n "
        "- Product ID: PROD-5678\n\n"
    )

    mocked_send_exc.assert_called_once_with(
        "Error updating the subscriptions in configuration order: ORD-1234", expected_message
    )


def test_notify_not_updated_subscriptions_with_updated_subs(mocker):
    mocked_send_exc = mocker.patch("adobe_vipm.flows.utils.notification.send_exception")
    notify_not_updated_subscriptions(
        order_id="ORD-1234",
        error_message="Some error occurred",
        updated_subscriptions=[
            {"subscription_vendor_id": "SUB-1"},
            {"subscription_vendor_id": "SUB-2"},
        ],
        product_id="PROD-5678",
    )

    expected_message = (
        "Some error occurred\n\n"
        "The order **ORD-1234**\n\n"
        "has failed changing the auto-renewal status\n\n "
        "- Product ID: PROD-5678\n\n"
        "The following subscriptions has been updated and rolled back:\n"
        "  - SUB-1\n"
        "  - SUB-2\n"
    )

    mocked_send_exc.assert_called_once_with(
        "Error updating the subscriptions in configuration order: ORD-1234", expected_message
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
                status=AdobeStatus.STATUS_PROCESSED, renewal_date=date.today().isoformat()
            )
        )
        is False
    )
    assert (
        is_transferring_item_expired(
            adobe_subscription_factory(status=AdobeStatus.STATUS_INACTIVE_OR_GENERIC_FAILURE)
        )
        is True
    )

    assert (
        is_transferring_item_expired(adobe_items_factory(renewal_date=date.today().isoformat())[0])
        is False
    )
    assert (
        is_transferring_item_expired(
            adobe_items_factory(renewal_date=(date.today() + timedelta(days=5)).isoformat())[0]
        )
        is False
    )

    assert (
        is_transferring_item_expired(
            adobe_items_factory(renewal_date=(date.today() - timedelta(days=5)).isoformat())[0]
        )
        is True
    )


def test_get_transfer_item_sku_by_subscription(
    adobe_transfer_factory,
    adobe_items_factory,
):
    items = adobe_items_factory(subscription_id="my-awesome-sub")
    transfer = adobe_transfer_factory(items=items)
    assert get_transfer_item_sku_by_subscription(transfer, "my-awesome-sub") == items[0]["offerId"]


def test_get_customer_licenses_discount_level(adobe_customer_factory):
    assert (
        get_customer_licenses_discount_level(adobe_customer_factory(licenses_discount_level="05"))
        == "05"
    )


def test_get_customer_consumables_discount_level(adobe_customer_factory):
    assert (
        get_customer_consumables_discount_level(
            adobe_customer_factory(consumables_discount_level="T2")
        )
        == "T2"
    )
