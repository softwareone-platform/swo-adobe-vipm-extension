"""
Planning of the Adobe RETURN orders of the downsize lines of a Change Order.

Adobe accepts a RETURN for any quantity up to a NEW or RENEWAL line item's
``remainingQuantity``, so a downsize line is feasible when the returnable pool
of its subscription (read fresh from Adobe) covers the whole downsize. A
feasible line is returned in full, oldest order first; an infeasible one is
deferred in full to the renewal quantity. A line is never split between both.
Nothing here performs I/O: the pool and the RETURN orders already placed are
read by the caller.
"""

from dataclasses import dataclass, replace
from enum import StrEnum

from adobe_vipm.adobe.dataclasses import ReturnableOrderInfo
from adobe_vipm.flows.utils.subscription import is_consumables_sku
from adobe_vipm.utils import get_partial_sku


class DownsizeOutcome(StrEnum):
    """How the quantity removed by a downsize line is resolved with Adobe."""

    RETURN = "RETURN"
    DEFER = "DEFER"


@dataclass(frozen=True)
class DownsizePlan:
    """
    Resolution of one downsize line of a Change Order.

    A RETURN plan gives back the whole downsize to Adobe through RETURN orders against
    the ``allocations`` (``quantity`` is the allocated quantity, oldest order first); a
    DEFER plan returns nothing and leaves the reduction to the renewal quantity.
    ``returned_quantity`` is what RETURN orders of the same MPT order already returned,
    so the allocations only cover the outstanding quantity.
    """

    sku: str
    subscription_id: str
    target_quantity: int
    downsize_quantity: int
    returned_quantity: int
    outcome: DownsizeOutcome
    allocations: tuple[ReturnableOrderInfo, ...] = ()

    @property
    def outstanding_quantity(self) -> int:
        """Quantity of the downsize that still has to be returned."""
        return max(self.downsize_quantity - self.returned_quantity, 0)

    @property
    def is_fully_allocated(self) -> bool:
        """Whether the allocations cover the whole outstanding quantity."""
        allocated = sum(allocation.quantity for allocation in self.allocations)
        return allocated == self.outstanding_quantity

    def as_deferred(self) -> "DownsizePlan":
        """Return the same line resolved as a DEFER, with nothing to return."""
        return replace(self, outcome=DownsizeOutcome.DEFER, allocations=())


def is_returnable_offer(offer_id: str) -> bool:
    """
    Check whether Adobe accepts RETURN orders for an offer.

    Adobe does not accept returns of consumables (for example Sign transactions),
    Stock Credit Packs, Acrobat licence packs or MOQ offers. Only consumables can be
    told apart from the offer id; the others are rejected by Adobe on the RETURN.

    Args:
        offer_id: Full Adobe offer id of an order line item.

    Returns:
        False when the offer is known not to be returnable.
    """
    return not is_consumables_sku(offer_id)


def get_sku_returned_quantity(return_orders: list[dict], sku: str) -> int:
    """
    Sum the quantity that RETURN orders returned for a SKU.

    Args:
        return_orders: Adobe RETURN orders placed by the MPT order (open or complete).
        sku: Partial Adobe SKU of the downsize line.

    Returns:
        The quantity already returned for the SKU.
    """
    return sum(
        line_item["quantity"]
        for return_order in return_orders
        for line_item in return_order["lineItems"]
        if get_partial_sku(line_item["offerId"]) == sku
    )


def allocate_oldest_first(
    pool: list[ReturnableOrderInfo], quantity: int
) -> tuple[ReturnableOrderInfo, ...]:
    """
    Allocate a quantity to return across a returnable pool, oldest order first.

    Each pool entry gives at most its returnable quantity; the last entry drawn from
    may be returned in part. Consuming the oldest orders first keeps the newest ones,
    which stay longest inside the return window, returnable for later.

    Args:
        pool: Returnable order lines, each with its returnable quantity.
        quantity: Quantity to allocate.

    Returns:
        The allocations, each with the quantity to return from its order, or an empty
        tuple when the pool cannot cover the whole quantity.
    """
    ordered_pool = sorted(pool, key=lambda entry: entry.order.get("creationDate", ""))
    if sum(entry.quantity for entry in ordered_pool) < quantity:
        return ()

    allocations = []
    still_needed = quantity
    for entry in ordered_pool:
        if still_needed <= 0:
            break
        allocated = min(entry.quantity, still_needed)
        allocations.append(
            ReturnableOrderInfo(order=entry.order, line=entry.line, quantity=allocated)
        )
        still_needed -= allocated
    return tuple(allocations)


def _is_feasible(
    pool: list[ReturnableOrderInfo], allocations: tuple[ReturnableOrderInfo, ...]
) -> bool:
    """Whether a pool of returnable offers yielded the allocations of a whole downsize."""
    offer_ids = [entry.line["offerId"] for entry in pool]
    return bool(allocations) and all(map(is_returnable_offer, offer_ids))


def plan_downsize(
    line: dict,
    subscription_id: str,
    pool: list[ReturnableOrderInfo],
    returned_quantity: int,
) -> DownsizePlan:
    """
    Decide how a downsize line is resolved and allocate its outstanding quantity.

    A line with a quantity already returned by the same MPT order stays a RETURN,
    since deferring it would count the credited quantity twice; its plan may then not
    be fully allocated when the pool shrank. Otherwise the line is a RETURN when the
    offer is returnable and the pool covers the whole downsize, and a DEFER when not.

    Args:
        line: MPT order line with a downsize (``oldQuantity`` > ``quantity``).
        subscription_id: Adobe subscription id of the line.
        pool: Returnable order lines of the subscription, read fresh from Adobe.
        returned_quantity: Quantity already returned for the line by the MPT order.

    Returns:
        The downsize plan of the line.
    """
    downsize_quantity = line["oldQuantity"] - line["quantity"]
    outstanding_quantity = max(downsize_quantity - returned_quantity, 0)
    allocations = allocate_oldest_first(pool, outstanding_quantity)
    if returned_quantity > 0 or _is_feasible(pool, allocations):
        outcome = DownsizeOutcome.RETURN
    else:
        outcome = DownsizeOutcome.DEFER
        allocations = ()

    return DownsizePlan(
        sku=line["item"]["externalIds"]["vendor"],
        subscription_id=subscription_id,
        target_quantity=line["quantity"],
        downsize_quantity=downsize_quantity,
        returned_quantity=returned_quantity,
        outcome=outcome,
        allocations=allocations,
    )
