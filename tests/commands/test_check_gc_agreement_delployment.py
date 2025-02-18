from django.core.management import call_command


def test_process_transfers(mocker):
    mocked = mocker.patch(
        "adobe_vipm.flows.global_customer.check_gc_agreement_deployments"
    )

    call_command("check_gc_agreement_deployments")

    mocked.assert_called()
