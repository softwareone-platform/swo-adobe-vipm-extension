"""
Classification of Adobe RETURN failures and the per-line report of a failed downsize.

Adobe offers no transaction across RETURN orders, so a failure is never undone:
it is either retried, re-planned once, resolved by deferring a line that has
not been credited yet, or it fails the order with a report of what each line
already returned. Nothing here performs I/O.
"""

from enum import StrEnum
from http import HTTPStatus

from adobe_vipm.adobe.constants import AdobeErrorCode
from adobe_vipm.adobe.errors import AdobeAPIError
from adobe_vipm.flows.utils.returns import DownsizeOutcome, DownsizePlan

# RETURN orders of a line as (Adobe order id, returned quantity).
type ReturnedOrders = list[tuple[str, int]]


class ReturnErrorAction(StrEnum):
    """What to do when Adobe does not accept or does not complete a RETURN order."""

    RETRY = "RETRY"
    REPLAN = "REPLAN"
    DEFER = "DEFER"
    FAIL = "FAIL"


def classify_return_error(
    error: Exception | None, *, is_line_credited: bool, can_replan: bool
) -> ReturnErrorAction:
    """
    Decide how to handle a RETURN order that Adobe rejected or failed.

    - Transport errors, non-API HTTP errors and 5xx: retry on the next run (the RETURN,
      if created, is found again by its external reference).
    - ``RETURN_QTY_EXCEEDS_REMAINING``, or a RETURN order that ended failed (``error``
      is None): the remaining quantity dropped since the pool was read, re-plan the
      line once; afterwards resolve it as any other rejection.
    - ``RETURN_VIOLATES_3YC_MCQ``: the commitment minimum applies to the whole product
      family, a re-plan cannot fix it, fail.
    - Any other rejection (for example ``RETURN_NOT_SUPPORTED_MOQ_SKU``): defer the line
      when nothing of it was credited yet, fail otherwise.

    Args:
        error: Exception raised by the Adobe client, None for a failed RETURN order.
        is_line_credited: Whether any quantity of the line was already returned.
        can_replan: Whether the line can still be re-planned in this run.

    Returns:
        The action to take.
    """
    if error is not None and _is_transient(error):
        return ReturnErrorAction.RETRY
    error_code = getattr(error, "code", None)
    if error_code == AdobeErrorCode.RETURN_VIOLATES_3YC_MCQ:
        return ReturnErrorAction.FAIL
    is_quantity_drop = error is None or error_code == AdobeErrorCode.RETURN_QTY_EXCEEDS_REMAINING
    if is_quantity_drop and can_replan:
        return ReturnErrorAction.REPLAN
    return ReturnErrorAction.FAIL if is_line_credited else ReturnErrorAction.DEFER


def _is_transient(error: Exception) -> bool:
    return (
        not isinstance(error, AdobeAPIError)
        or error.status_code >= HTTPStatus.INTERNAL_SERVER_ERROR
    )


def build_return_report(plans: dict[str, DownsizePlan], returned: dict[str, ReturnedOrders]) -> str:
    """
    Describe what each downsize line returned, for a failed downsize.

    Args:
        plans: Downsize plans of the order, by SKU.
        returned: RETURN orders of each SKU, previous runs included.

    Returns:
        One entry per line, for example ``65304578CA: PARTIAL 10/30 (P9202197700)``.
    """
    entries = []
    for sku, plan in plans.items():
        entries.append(_format_entry(sku, plan, returned.get(sku, [])))
    return "; ".join(entries)


def _format_entry(sku: str, plan: DownsizePlan, returned_orders: ReturnedOrders) -> str:
    returned_quantity = sum(quantity for _, quantity in returned_orders)
    status = _get_line_status(plan, returned_quantity)
    return (
        f"{sku}: {status} {returned_quantity}/{plan.downsize_quantity}"
        f"{_format_order_ids(returned_orders)}"
    )


def _get_line_status(plan: DownsizePlan, returned_quantity: int) -> str:
    if plan.outcome == DownsizeOutcome.DEFER:
        return "DEFERRED (renewal quantity not updated)"
    if returned_quantity >= plan.downsize_quantity:
        return "RETURNED"
    return "PARTIAL" if returned_quantity else "NOT PROCESSED"


def _format_order_ids(returned_orders: ReturnedOrders) -> str:
    order_ids = ", ".join(order_id for order_id, _ in returned_orders)
    return f" ({order_ids})" if order_ids else ""
