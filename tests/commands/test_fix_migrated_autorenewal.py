from django.core.management import call_command


def test_fix_migrated_autorenewl(mocker):
    mocked = mocker.patch("adobe_vipm.flows.migration.fix_migrated_autorenewal_off")

    call_command("fix_migrated_autorenewal")

    mocked.assert_called()
