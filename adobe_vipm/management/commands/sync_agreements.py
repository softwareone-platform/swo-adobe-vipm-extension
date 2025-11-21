from mpt_extension_sdk.core.utils import setup_client

from adobe_vipm.adobe.client import get_adobe_client
from adobe_vipm.flows.sync.agreement import (
    sync_agreements_by_3yc_end_date,
    sync_agreements_by_agreement_ids,
    sync_agreements_by_coterm_date,
    sync_agreements_by_renewal_date,
    sync_all_agreements,
)
from adobe_vipm.management.commands.base import AdobeBaseCommand


class Command(AdobeBaseCommand):
    """Sync agreement command."""

    help = "Synchronize agreements on anniversary, 3YC end and coterm date."

    def add_arguments(self, parser):
        """Add required arguments."""
        mutex_group = parser.add_mutually_exclusive_group()
        # TODO: why do we need --all parameters here?? it is not passed anywhere
        mutex_group.add_argument(
            "--all",
            action="store_true",
            default=False,
            help="Allow synchronization for customers that commited for 3y",
        )
        mutex_group.add_argument(
            "--agreements",
            nargs="*",
            metavar="AGREEMENT",
            default=[],
            help="list of specific agreements to synchronize separated by space",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            default=False,
            help="Test synchronization without making changes",
        )
        parser.add_argument(
            "--sync-prices",
            action="store_true",
            default=False,
            help="Force prices sync",
        )

    def handle(self, *args, **options):
        """Run sync agreement command."""
        self.info("Start processing agreements...")
        mpt_client = setup_client()
        adobe_client = get_adobe_client()
        if options["agreements"]:
            sync_agreements_by_agreement_ids(
                mpt_client,
                adobe_client,
                options["agreements"],
                dry_run=options["dry_run"],
                sync_prices=options["sync_prices"],
            )
        elif options["all"]:
            sync_all_agreements(mpt_client, adobe_client, dry_run=options["dry_run"])
        else:
            sync_agreements_by_3yc_end_date(mpt_client, adobe_client, dry_run=options["dry_run"])
            sync_agreements_by_coterm_date(mpt_client, adobe_client, dry_run=options["dry_run"])
            sync_agreements_by_renewal_date(mpt_client, adobe_client, dry_run=options["dry_run"])
        self.success("Processing agreements completed.")
