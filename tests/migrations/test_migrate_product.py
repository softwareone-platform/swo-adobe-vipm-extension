from unittest.mock import MagicMock, patch

from mpt_api_client import MPTClient
from mpt_api_client.resources.commerce.agreements import Agreement

from adobe_vipm.migrations.parameters_sync import AgreementClient, MigrateProductAgreementParameters


def test_migrate_product_with_progressbar():
    mpt_client = MagicMock(spec=MPTClient)
    agreement1 = MagicMock(spec=Agreement)
    agreement1.to_dict.return_value = {
        "id": "AGR-1",
        "product": {"id": "PRD-1"},
        "parameters": {"fulfillment": [], "ordering": []},
    }
    mock_agreements = [agreement1]
    migrator = MigrateProductAgreementParameters(mpt_client)

    with (
        patch.object(AgreementClient, "iterate", return_value=mock_agreements),
        patch.object(AgreementClient, "count", return_value=1),
        patch.object(MigrateProductAgreementParameters, "process_agreement") as mock_process,
    ):
        migrator.migrate_product_parameters("PRD-1")  # act

    mock_process.assert_called_once_with(agreement1.to_dict())
