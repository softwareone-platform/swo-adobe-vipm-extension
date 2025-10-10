from mpt_extension_sdk.core.utils import setup_client

from adobe_vipm.adobe.client import get_adobe_client
from adobe_vipm.flows.sync.helper import sync_agreements_by_3yc_enroll_status
from adobe_vipm.management.commands.base import AdobeBaseCommand


class Command(AdobeBaseCommand):
    """Synchronize 3YC enrollment status back to MPT."""

    help = "Synchronize agreements based on their 3YC enrollment statuses"

    def add_arguments(self, parser):
        """Add required arguments."""
        parser.add_argument(
            "--dry-run",
            action="store_true",
            default=False,
            help="Test synchronization without making changes",
        )

    def handle(self, *args, **options):  # noqa: WPS110
        """Run command."""
        self.info("Start processing 3YC enrollment statuses...")
        mpt_client = setup_client()
        adobe_client = get_adobe_client()
        sync_agreements_by_3yc_enroll_status(mpt_client, adobe_client, dry_run=options["dry_run"])
        self.success("Processing 3YC enrollment statuses completed.")
