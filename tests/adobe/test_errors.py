import json
from http.client import RemoteDisconnected

import pytest
from requests import ConnectTimeout, HTTPError, PreparedRequest
from requests.exceptions import ConnectionError as RequestsConnectionError
from requests.models import Response

from adobe_vipm.adobe.errors import (
    AdobeAPIError,
    AdobeError,
    AdobeTransportError,
    wrap_http_error,
)


def test_simple_error(adobe_api_error_factory):
    error_data = adobe_api_error_factory("1234", "error message")

    result = AdobeAPIError(400, error_data)

    assert result.status_code == 400
    assert result.code == "1234"
    assert result.message == "error message"
    assert result.details == []
    assert str(result) == "1234 - error message"
    assert repr(result) == str(error_data)


def test_detailed_error(adobe_api_error_factory):
    error_data = adobe_api_error_factory(
        "5678", "error message with details", details=["detail1", "detail2"]
    )

    result = AdobeAPIError(400, error_data)

    assert result.details == ["detail1", "detail2"]
    assert str(result) == "5678 - error message with details: detail1, detail2"


def test_wrap_http_error(adobe_api_error_factory):
    @wrap_http_error
    def func():
        response = Response()
        response.status_code = 400
        response.headers["Content-Type"] = "application/json"
        response._content = json.dumps(
            adobe_api_error_factory(
                "5678", "error message with details", details=["detail1", "detail2"]
            ),
        ).encode("utf-8")
        raise HTTPError(response=response)

    with pytest.raises(AdobeAPIError) as cv:
        func()

    assert cv.value.status_code == 400
    assert cv.value.details == ["detail1", "detail2"]
    assert str(cv.value) == "5678 - error message with details: detail1, detail2"


def test_wrap_http_error_504_error_code():
    @wrap_http_error
    def func():
        response = Response()
        response.status_code = 504
        response.headers["Content-Type"] = "application/json"
        response._content = json.dumps({
            "error_code": "504001",
            "message": "Gateway Timeout",
        }).encode("utf-8")
        raise HTTPError(response=response)

    with pytest.raises(AdobeError) as cv:
        func()

    assert cv.value.status_code == 504
    assert str(cv.value) == "504001 - Gateway Timeout"


def test_wrap_http_error_json_decode_error():
    @wrap_http_error
    def func():
        response = Response()
        response.status_code = 500
        response._content = b"Internal Server Error"
        raise HTTPError(response=response)

    with pytest.raises(AdobeError) as cv:
        func()

    assert str(cv.value) == "500 - Internal Server Error"


def adobe_prepared_request(url="https://partners.adobe.io/v3/customers/1005301363"):
    request = PreparedRequest()
    request.prepare(method="GET", url=url, headers={"x-correlation-id": "corr-id-1"})
    return request


def test_wrap_http_error_names_the_request_behind_a_dropped_connection():
    @wrap_http_error
    def func():
        raise RequestsConnectionError(
            ("Connection aborted.", RemoteDisconnected("Remote end closed connection")),
            request=adobe_prepared_request(),
        )

    with pytest.raises(AdobeTransportError) as cv:
        func()

    assert str(cv.value) == (
        "Adobe transport failure on GET https://partners.adobe.io/v3/customers/1005301363 "
        "(correlation id: corr-id-1): "
        "('Connection aborted.', RemoteDisconnected('Remote end closed connection'))"
    )


def test_wrap_http_error_names_the_request_behind_a_timeout():
    @wrap_http_error
    def func():
        raise ConnectTimeout("timed out", request=adobe_prepared_request())

    with pytest.raises(AdobeTransportError) as cv:
        func()

    assert cv.value.request_description == (
        "GET https://partners.adobe.io/v3/customers/1005301363 (correlation id: corr-id-1)"
    )


def test_wrap_http_error_falls_back_when_the_request_is_unknown():
    @wrap_http_error
    def func():
        raise RequestsConnectionError("Connection aborted.")

    with pytest.raises(AdobeTransportError) as cv:
        func()

    assert cv.value.request_description == "an Adobe request"


# Flows catch AdobeError to fail an order; a transient network fault must not do that.
def test_transport_error_is_not_an_adobe_error():
    result = issubclass(AdobeTransportError, AdobeError)

    assert result is False
