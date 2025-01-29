import pytest
from swo.mpt.extensions.runtime.initializer import get_extension_variables


def test_get_extension_variables_valid(
    monkeypatch,
    mock_valid_env_values,
    mock_ext_expected_environment_values
):
    for key, value in mock_valid_env_values.items():
        monkeypatch.setenv(key, value)

    extension_variables = get_extension_variables()

    assert mock_ext_expected_environment_values.items() <= extension_variables.items()


def test_get_extension_variables_json_error(
    monkeypatch,
    mock_invalid_env_values
):
    for key, value in mock_invalid_env_values.items():
        monkeypatch.setenv(key, value)

    with pytest.raises(Exception) as e:
        get_extension_variables()

    assert "Variable EXT_PRODUCT_SEGMENT not well formatted" in str(e.value)
