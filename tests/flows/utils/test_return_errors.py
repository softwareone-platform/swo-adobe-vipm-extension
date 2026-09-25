import pytest

from adobe_vipm.adobe.errors import AdobeAPIError, AdobeError
from adobe_vipm.flows.utils.return_errors import (
    ReturnErrorAction,
    build_return_report,
    classify_return_error,
)
from adobe_vipm.flows.utils.returns import DownsizeOutcome, DownsizePlan


def _api_error(code, status_code=422):
    return AdobeAPIError(status_code, {"code": code, "message": "An error"})


@pytest.fixture
def downsize_plan_factory():
    def _plan(sku, downsize_quantity, outcome=DownsizeOutcome.RETURN):
        return DownsizePlan(
            sku=sku,
            subscription_id=f"sub-{sku}",
            target_quantity=0,
            downsize_quantity=downsize_quantity,
            returned_quantity=0,
            outcome=outcome,
        )

    return _plan


@pytest.mark.parametrize(
    ("error", "is_line_credited", "can_replan", "expected_action"),
    [
        (AdobeError("connection reset"), False, True, ReturnErrorAction.RETRY),
        (_api_error("1124", 500), True, True, ReturnErrorAction.RETRY),
        (_api_error("RETURN_QTY_EXCEEDS_REMAINING"), True, True, ReturnErrorAction.REPLAN),
        (None, False, True, ReturnErrorAction.REPLAN),
        (_api_error("RETURN_QTY_EXCEEDS_REMAINING"), False, False, ReturnErrorAction.DEFER),
        (_api_error("RETURN_QTY_EXCEEDS_REMAINING"), True, False, ReturnErrorAction.FAIL),
        (_api_error("RETURN_VIOLATES_3YC_MCQ"), False, True, ReturnErrorAction.FAIL),
        (_api_error("RETURN_NOT_SUPPORTED_MOQ_SKU"), False, True, ReturnErrorAction.DEFER),
        (_api_error("RETURN_NOT_SUPPORTED_MOQ_SKU"), True, True, ReturnErrorAction.FAIL),
    ],
)
def test_classify_return_error(error, is_line_credited, can_replan, expected_action):
    result = classify_return_error(error, is_line_credited=is_line_credited, can_replan=can_replan)

    assert result == expected_action


def test_build_return_report(downsize_plan_factory):
    plans = {
        "SKU-A": downsize_plan_factory("SKU-A", 20),
        "SKU-B": downsize_plan_factory("SKU-B", 30),
        "SKU-C": downsize_plan_factory("SKU-C", 5),
        "SKU-D": downsize_plan_factory("SKU-D", 8, DownsizeOutcome.DEFER),
    }
    returned = {
        "SKU-A": [("P1", 20)],
        "SKU-B": [("P2", 10), ("P3", 5)],
    }

    result = build_return_report(plans, returned)

    assert result == (
        "SKU-A: RETURNED 20/20 (P1); SKU-B: PARTIAL 15/30 (P2, P3); SKU-C: NOT PROCESSED 0/5; "
        "SKU-D: DEFERRED (renewal quantity not updated) 0/8"
    )
