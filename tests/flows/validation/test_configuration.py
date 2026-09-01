from adobe_vipm.flows.helpers import SetupContext
from adobe_vipm.flows.validation.configuration import validate_configuration_order
from adobe_vipm.flows.validation.shared import ValidateNoEarlyRenewal


def test_validate_configuration_order(mocker):
    mocked_pipeline_instance = mocker.MagicMock()
    mocked_pipeline_ctor = mocker.patch(
        "adobe_vipm.flows.validation.configuration.Pipeline",
        return_value=mocked_pipeline_instance,
    )
    mocked_context = mocker.MagicMock()
    mocked_context_ctor = mocker.patch(
        "adobe_vipm.flows.validation.configuration.Context", return_value=mocked_context
    )
    mocked_client = mocker.MagicMock()
    mocked_order = mocker.MagicMock()

    validate_configuration_order(mocked_client, mocked_order)  # act

    expected_steps = [
        SetupContext,
        ValidateNoEarlyRenewal,
    ]
    actual_steps = [type(step) for step in mocked_pipeline_ctor.mock_calls[0].args]
    assert actual_steps == expected_steps
    mocked_context_ctor.assert_called_once_with(order=mocked_order)
    mocked_pipeline_instance.run.assert_called_once_with(mocked_client, mocked_context)
