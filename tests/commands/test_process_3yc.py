from django.core.management import call_command


def test_process_sync_agreements(mocker):
    mocked_client = mocker.MagicMock()
    mocker.patch(
        "adobe_vipm.management.commands.process_3yc.setup_client",
        return_value=mocked_client,
    )

    mocked_check = mocker.patch(
        "adobe_vipm.management.commands.process_3yc.check_3yc_commitment_request"
    )

    call_command("process_3yc")

    assert mocked_check.mock_calls[0].args == (mocked_client,)
    assert mocked_check.mock_calls[0].kwargs == {"is_recommitment": False}
    assert mocked_check.mock_calls[1].args == (mocked_client,)
    assert mocked_check.mock_calls[1].kwargs == {"is_recommitment": True}
