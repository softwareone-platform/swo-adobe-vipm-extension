import pytest

from adobe_vipm.adobe.dataclasses import ReturnableOrderInfo
from adobe_vipm.flows.utils.returns import (
    DownsizeOutcome,
    DownsizePlan,
    allocate_oldest_first,
    get_sku_returned_quantity,
    is_returnable_offer,
    plan_downsize,
)

LICENSE_OFFER_ID = "65304520CA01A12"
CONSUMABLE_OFFER_ID = "65322435CAT1A12"


@pytest.fixture
def pool_entry_factory():
    def _entry(order_id, creation_date, quantity, offer_id=LICENSE_OFFER_ID):
        return ReturnableOrderInfo(
            order={"orderId": order_id, "creationDate": creation_date},
            line={"extLineItemNumber": 1, "offerId": offer_id, "quantity": quantity},
            quantity=quantity,
        )

    return _entry


@pytest.fixture
def downsize_line():
    def _line(old_quantity, quantity):
        return {
            "id": "ALI-1234-1234-1234-0001",
            "item": {"externalIds": {"vendor": "65304520CA"}},
            "oldQuantity": old_quantity,
            "quantity": quantity,
        }

    return _line


@pytest.fixture
def worked_example_pool(pool_entry_factory):
    return [
        pool_entry_factory("order_c", "2024-01-08T00:00:00Z", 10),
        pool_entry_factory("order_a", "2024-01-02T00:00:00Z", 20),
        pool_entry_factory("order_b", "2024-01-06T00:00:00Z", 10),
    ]


@pytest.mark.parametrize(
    ("offer_id", "expected_result"),
    [
        (LICENSE_OFFER_ID, True),
        (CONSUMABLE_OFFER_ID, False),
    ],
)
def test_is_returnable_offer(offer_id, expected_result):
    result = is_returnable_offer(offer_id)

    assert result is expected_result


def test_get_sku_returned_quantity():
    return_orders = [
        {"lineItems": [{"offerId": LICENSE_OFFER_ID, "quantity": 20}]},
        {"lineItems": [{"offerId": "65304520CA03A12", "quantity": 5}]},
        {"lineItems": [{"offerId": "99999999CA01A12", "quantity": 7}]},
    ]

    result = get_sku_returned_quantity(return_orders, "65304520CA")

    assert result == 25


def test_allocate_oldest_first_partial_last_order(worked_example_pool):
    result = allocate_oldest_first(worked_example_pool, 25)

    assert [(entry.order["orderId"], entry.quantity) for entry in result] == [
        ("order_a", 20),
        ("order_b", 5),
    ]


def test_allocate_oldest_first_whole_pool(worked_example_pool):
    result = allocate_oldest_first(worked_example_pool, 40)

    assert [(entry.order["orderId"], entry.quantity) for entry in result] == [
        ("order_a", 20),
        ("order_b", 10),
        ("order_c", 10),
    ]


def test_allocate_oldest_first_pool_too_small(worked_example_pool):
    result = allocate_oldest_first(worked_example_pool, 41)

    assert result == ()


def test_plan_downsize_return_single_order(pool_entry_factory, downsize_line):
    pool = [pool_entry_factory("order_a", "2024-01-02T00:00:00Z", 20)]

    result = plan_downsize(downsize_line(20, 15), "SUB-1", pool, 0)

    assert result == DownsizePlan(
        sku="65304520CA",
        subscription_id="SUB-1",
        target_quantity=15,
        downsize_quantity=5,
        returned_quantity=0,
        outcome=DownsizeOutcome.RETURN,
        allocations=(ReturnableOrderInfo(order=pool[0].order, line=pool[0].line, quantity=5),),
    )


def test_plan_downsize_worked_example(worked_example_pool, downsize_line):
    result = plan_downsize(downsize_line(45, 15), "SUB-1", worked_example_pool, 0)

    assert (
        result.outcome,
        [(entry.order["orderId"], entry.quantity) for entry in result.allocations],
    ) == (DownsizeOutcome.RETURN, [("order_a", 20), ("order_b", 10)])


@pytest.mark.parametrize(
    ("old_quantity", "quantity", "pool_quantities"),
    [
        (50, 20, [20]),
        (20, 15, []),
    ],
)
def test_plan_downsize_defers_when_pool_does_not_cover(
    pool_entry_factory, downsize_line, old_quantity, quantity, pool_quantities
):
    pool = [
        pool_entry_factory("order_a", "2024-01-02T00:00:00Z", pool_quantity)
        for pool_quantity in pool_quantities
    ]

    result = plan_downsize(downsize_line(old_quantity, quantity), "SUB-1", pool, 0)

    assert (result.outcome, result.allocations) == (DownsizeOutcome.DEFER, ())


def test_plan_downsize_defers_consumables(pool_entry_factory, downsize_line):
    pool = [pool_entry_factory("order_a", "2024-01-02T00:00:00Z", 2000, CONSUMABLE_OFFER_ID)]

    result = plan_downsize(downsize_line(2000, 1000), "SUB-1", pool, 0)

    assert (result.outcome, result.allocations) == (DownsizeOutcome.DEFER, ())


def test_plan_downsize_already_returning_allocates_outstanding(pool_entry_factory, downsize_line):
    pool = [pool_entry_factory("order_b", "2024-01-06T00:00:00Z", 10)]

    result = plan_downsize(downsize_line(45, 15), "SUB-1", pool, 20)

    assert (
        result.outcome,
        result.outstanding_quantity,
        [entry.quantity for entry in result.allocations],
        result.is_fully_allocated,
    ) == (DownsizeOutcome.RETURN, 10, [10], True)


def test_plan_downsize_already_returning_pool_shrank(pool_entry_factory, downsize_line):
    pool = [pool_entry_factory("order_b", "2024-01-06T00:00:00Z", 5)]

    result = plan_downsize(downsize_line(45, 15), "SUB-1", pool, 20)

    assert (result.outcome, result.allocations, result.is_fully_allocated) == (
        DownsizeOutcome.RETURN,
        (),
        False,
    )


def test_plan_downsize_already_fully_returned(downsize_line):
    result = plan_downsize(downsize_line(45, 15), "SUB-1", [], 30)

    assert (result.outcome, result.outstanding_quantity, result.is_fully_allocated) == (
        DownsizeOutcome.RETURN,
        0,
        True,
    )
