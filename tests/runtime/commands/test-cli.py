from click.testing import CliRunner
from django.apps import apps
from swo.mpt.extensions.runtime.swoext import cli


def test_cli():
    app_config_name = "adobe_vipm"
    app_config = apps.get_app_config(app_config_name)
    app_config.ready()
    runner = CliRunner()
    result = runner.invoke(cli, ["django", "--help"])
    assert result.return_value is None
