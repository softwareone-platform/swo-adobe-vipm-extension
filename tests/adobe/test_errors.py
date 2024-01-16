from adobe_vipm.adobe.errors import AdobeAPIError


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
