import typer
from mpt_api_client import MPTClient
from django.conf import settings
from mpt_extension_sdk.core.utils import setup_client

from adobe_vipm.adobe.client import get_adobe_client
from adobe_vipm.adobe.config import Config, get_config
from adobe_vipm.flows.sync.agreement import (
    sync_agreements_by_3yc_end_date,
    sync_agreements_by_agreement_ids,
    sync_agreements_by_coterm_date,
    sync_agreements_by_renewal_date,
    sync_all_agreements,
)
from adobe_vipm.management.commands.base import AdobeBaseCommand
from adobe_vipm.migrations.parameters_sync import MigrateProductAgreementParameters


class Command(AdobeBaseCommand):
    """Sync agreement command."""

    help = "Synchronize product parameters with agreements params and update visibility."

    def add_arguments(self, parser):
        """Add required arguments."""
        parser.add_argument(
            "--dry-run",
            action="store_true",
            default=False,
            help="Test synchronization without making changes",
        )

    def handle(self, *args, **options):
        """Run sync agreement command."""
        self.info(f"Start parametters migrations for products {settings.MPT_PRODUCTS_IDS}...")
        parameters_migration=MigrateProductAgreementParameters(MPTClient(), dry_run=options["dry_run"])
        for product_id in settings.MPT_PRODUCTS_IDS:
            self.info(f"Processing product {product_id}...")
            parameters_migration.migrate_product_parameters(product_id)
            self.info(f"Processing product {product_id} completed.")
        self.success("Processing agreements completed.")
