import json

import pytest
from requests import HTTPError
from requests.models import Response

from adobe_vipm.adobe.errors import AdobeAPIError, AdobeError, wrap_http_error


def test_simple_error(adobe_api_error_factory):
    error_data = adobe_api_error_factory("1234", "error message")
    error = AdobeAPIError(400, error_data)
    assert error.status_code == 400
    assert error.code == "1234"
    assert error.message == "error message"
    assert error.details == []
    assert str(error) == "1234 - error message"
    assert repr(error) == str(error_data)


def test_detailed_error(adobe_api_error_factory):
    error_data = adobe_api_error_factory(
        "5678", "error message with details", details=["detail1", "detail2"]
    )
    error = AdobeAPIError(400, error_data)
    assert error.details == ["detail1", "detail2"]
    assert str(error) == "5678 - error message with details: detail1, detail2"


def test_wrap_http_error(adobe_api_error_factory):
    def func():
        response = Response()
        response.status_code = 400
        response.headers["Content-Type"] = "application/json"
        response._content = json.dumps(  # noqa: SLF001
            adobe_api_error_factory(
                "5678", "error message with details", details=["detail1", "detail2"]
            ),
        ).encode("utf-8")

        raise HTTPError(response=response)

    wrapped_func = wrap_http_error(func)

    with pytest.raises(AdobeAPIError) as cv:
        wrapped_func()

    assert cv.value.status_code == 400
    assert cv.value.details == ["detail1", "detail2"]
    assert str(cv.value) == "5678 - error message with details: detail1, detail2"


def test_wrap_http_error_504_error_code():
    @wrap_http_error
    def func():
        response = Response()
        response.status_code = 504
        response.headers["Content-Type"] = "application/json"
        response._content = json.dumps({  # noqa: SLF001
            "error_code": "504001",
            "message": "Gateway Timeout",
        }).encode("utf-8")

        raise HTTPError(response=response)

    wrapped_func = wrap_http_error(func)

    with pytest.raises(AdobeError) as cv:
        wrapped_func()

    assert cv.value.status_code == 504
    assert str(cv.value) == "504001 - Gateway Timeout"


def test_wrap_http_error_json_decode_error(mocker):
    def func():
        response = Response()
        response.status_code = 500
        response._content = "Internal Server Error".encode("utf-8")  # noqa: SLF001 UP012

        raise HTTPError(response=response)

    wrapped_func = wrap_http_error(func)

    with pytest.raises(AdobeError) as cv:
        wrapped_func()

    assert str(cv.value) == "500 - Internal Server Error"
