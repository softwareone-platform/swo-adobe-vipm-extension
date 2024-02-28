from adobe_vipm.flows.errors import MPTError


def test_simple_error(mpt_error_factory):
    """
    Test the MPTError.
    """
    error_data = mpt_error_factory(500, "Internal Server Error", "Oops!")
    error = MPTError(error_data)
    assert str(error) == "500 Internal Server Error: Oops!"
    assert repr(error) == str(error_data)
