import uuid

import pytest
from django.conf import settings
from django.http import HttpRequest
from django.http.response import HttpResponseBase
from swo.mpt.extensions.runtime.events.utils import (
    _response_hook,
    instrument_logging,
    wrap_for_trace,
)


@pytest.mark.parametrize("appinsights", [True, False])
def test_wrapper(appinsights, mpt_client, mock_wrap_event):
    def func(client, event):
        assert event == mock_wrap_event

    event_type = "orders"
    settings.USE_APPLICATIONINSIGHTS = appinsights
    wrapped_func = wrap_for_trace(func, event_type)
    wrapped_func(client=mpt_client, event=mock_wrap_event)
    assert event_type == "orders"


def test_instrument_logging():
    is_success = True
    new_uuid = uuid.uuid4()
    try:
        settings.APPLICATIONINSIGHTS_CONNECTION_STRING = f"InstrumentationKey={new_uuid};IngestionEndpoint=https://westeurope-1.in.applicationinsights.azure.com/;LiveEndpoint=https://westeurope.livediagnostics.monitor.azure.com/"
        instrument_logging()
    except Exception:
        is_success = False
    assert is_success


def test_response_hook(mocker):
    mock_span = mocker.MagicMock()
    mock_request = HttpRequest()
    mock_response = HttpResponseBase()
    mock_response.ok = True
    mock_request.META["x-request-id"] = "1234"
    mock_request.META["x-correlation-id"] = "5678"
    mock_request._body = {"data": "test body"}
    _response_hook(mock_span, mock_request, mock_response)
    assert mock_span.set_attribute.call_count == 2
