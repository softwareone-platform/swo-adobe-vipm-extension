import pytest
from requests import HTTPError, JSONDecodeError

from adobe_vipm.adobe.errors import AdobeAPIError, AdobeError, wrap_http_error


def test_simple_error(adobe_api_error_factory):
    """
    Test the AdobeError exception when the error returned by
    Adobe does not contain additional details.
    """
    error_data = adobe_api_error_factory("1234", "error message")
    error = AdobeAPIError(error_data)
    assert error.code == "1234"
    assert error.message == "error message"
    assert error.details == []
    assert str(error) == "1234 - error message"
    assert repr(error) == str(error_data)


def test_detailed_error(adobe_api_error_factory):
    """
    Test the AdobeError exception when the error returned by
    Adobe does not contain additional details.
    """
    error_data = adobe_api_error_factory(
        "5678", "error message with details", details=["detail1", "detail2"]
    )
    error = AdobeAPIError(error_data)
    assert error.details == ["detail1", "detail2"]
    assert str(error) == "5678 - error message with details: detail1, detail2"


def test_wrap_http_error(mocker, adobe_api_error_factory):
    def func():
        response = mocker.MagicMock()
        response.json.return_value = adobe_api_error_factory(
        "5678", "error message with details", details=["detail1", "detail2"]
    )
        raise HTTPError(response=response)

    wrapped_func = wrap_http_error(func)

    with pytest.raises(AdobeAPIError) as cv:
        wrapped_func()

    assert cv.value.details == ["detail1", "detail2"]
    assert str(cv.value) == "5678 - error message with details: detail1, detail2"


def test_wrap_http_error_json_decode_error(mocker, adobe_api_error_factory):
    def func():
        response = mocker.MagicMock()
        response.status_code = 500
        response.content = b"Internal Server Error"
        response.json.side_effect = JSONDecodeError("msg", "doc", 0)
        raise HTTPError(response=response)

    wrapped_func = wrap_http_error(func)

    with pytest.raises(AdobeError) as cv:
        wrapped_func()

    assert str(cv.value) == "500 - Internal Server Error"
