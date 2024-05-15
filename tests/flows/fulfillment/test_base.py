import pytest

from adobe_vipm.flows.errors import MPTAPIError
from adobe_vipm.flows.fulfillment.base import fulfill_order
from adobe_vipm.flows.utils import strip_trace_id

pytestmark = pytest.mark.usefixtures("mock_adobe_config")


def test_fulfill_order_exception(mocker, mpt_error_factory, order_factory):
    error_data = mpt_error_factory(500, "Internal Server Error", "Oops!")
    error = MPTAPIError(500, error_data)
    mocked_notify = mocker.patch(
        "adobe_vipm.flows.fulfillment.base.notify_unhandled_exception_in_teams"
    )
    mocker.patch(
        "adobe_vipm.flows.fulfillment.base.populate_order_info",
        side_effect=error,
    )

    order = order_factory(order_id="ORD-FFFF")
    with pytest.raises(MPTAPIError):
        fulfill_order(mocker.MagicMock(), order)

    process, order_id, tb = mocked_notify.mock_calls[0].args
    assert process == "fulfillment"
    assert order_id == order["id"]
    assert strip_trace_id(str(error)) in tb
