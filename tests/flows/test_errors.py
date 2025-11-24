import json

import pytest
from requests import HTTPError, JSONDecodeError

from adobe_vipm.flows.errors import (
    AirTableAPIError,
    AirTableError,
    AirTableHttpError,
    MPTAPIError,
    MPTError,
    wrap_airtable_http_error,
    wrap_http_error,
)


def test_simple_error(mpt_error_factory):
    error_data = mpt_error_factory(500, "Internal Server Error", "Oops!")

    result = MPTAPIError(500, error_data)

    assert result.status_code == 500
    assert result.status == 500
    assert result.title == "Internal Server Error"
    assert result.detail == "Oops!"
    assert result.trace_id == error_data["traceId"]
    assert str(result) == f"500 Internal Server Error - Oops! ({result.trace_id})"
    assert repr(result) == str(error_data)


def test_detailed_error(mpt_error_factory):
    error_data = mpt_error_factory(
        400,
        "Bad Request",
        "One or more validation errors occurred.",
        trace_id="trace-id",
        errors={"id": ["The value of 'id' does not match expected format."]},
    )

    result = MPTAPIError(400, error_data)

    assert result.trace_id == "trace-id"
    assert result.errors == error_data["errors"]
    assert str(result) == (
        "400 Bad Request - One or more validation errors occurred. (trace-id)"
        f"\n{json.dumps(error_data['errors'], indent=2)}"
    )


def test_wrap_http_error(mocker, mpt_error_factory):
    error_data = mpt_error_factory(
        400,
        "Bad Request",
        "One or more validation errors occurred.",
        trace_id="trace-id",
        errors={"id": ["The value of 'id' does not match expected format."]},
    )
    response = mocker.Mock(status_code=400, json=mocker.Mock(return_value=error_data))
    mock_func = mocker.Mock(side_effect=HTTPError(response=response))
    wrapped_func = wrap_http_error(mock_func)

    with pytest.raises(MPTAPIError) as cv:
        wrapped_func()

    assert cv.value.trace_id == "trace-id"
    assert cv.value.errors == error_data["errors"]
    assert str(cv.value) == (
        "400 Bad Request - One or more validation errors occurred. (trace-id)"
        f"\n{json.dumps(error_data['errors'], indent=2)}"
    )


def test_wrap_http_error_json_decode_error(mocker):
    response = mocker.Mock(
        status_code=500,
        content=b"Internal Server Error",
        json=mocker.Mock(side_effect=JSONDecodeError("msg", "doc", 0)),
    )
    mock_func = mocker.Mock(side_effect=HTTPError(response=response))
    wrapped_func = wrap_http_error(mock_func)

    with pytest.raises(MPTError) as cv:
        wrapped_func()

    assert str(cv.value) == "500 - Internal Server Error"


def test_simple_airtable_error(
    airtable_error_factory,
):
    error_data = airtable_error_factory("Bad Request", "BAD_REQUEST")

    result = AirTableAPIError(400, error_data)

    assert result.status_code == 400
    assert result.code == 400
    assert result.message == "Bad Request"
    assert str(result) == "400 - Bad Request"
    assert repr(result) == str(error_data)


def test_wrap_airtable_http_error(mocker, airtable_error_factory):
    error_data = airtable_error_factory("Bad Request", "BAD_REQUEST")
    response = mocker.Mock(status_code=400, json=mocker.Mock(return_value=error_data))
    mock_func = mocker.Mock(side_effect=HTTPError(response=response))
    wrapped_func = wrap_airtable_http_error(mock_func)

    with pytest.raises(AirTableHttpError) as cv:
        wrapped_func()

    assert cv.value.status_code == 400
    assert str(cv.value) == "400 - Bad Request"


def test_wrap_airtable_http_error_json_decode_error(mocker):
    response = mocker.Mock(
        status_code=400,
        content=b"Bad Request",
        json=mocker.Mock(side_effect=JSONDecodeError("msg", "doc", 0)),
    )
    mock_func = mocker.Mock(side_effect=HTTPError(response=response))
    wrapped_func = wrap_airtable_http_error(mock_func)

    with pytest.raises(AirTableError) as cv:
        wrapped_func()

    assert str(cv.value) == "400 - Bad Request"
