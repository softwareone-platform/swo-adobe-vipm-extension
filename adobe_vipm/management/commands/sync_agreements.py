from django.core.management.base import BaseCommand
from mpt_extension_sdk.core.utils import setup_client

from adobe_vipm.flows.sync import (
    sync_agreements_by_3yc_end_date,
    sync_agreements_by_agreement_ids,
    sync_agreements_by_coterm_date,
    sync_agreements_by_next_sync,
    sync_agreements_by_renewal_date,
    sync_all_agreements,
)


class Command(BaseCommand):
    help = "Synchronize agreements on anniversary."

    def add_arguments(self, parser):
        mutex_group = parser.add_mutually_exclusive_group()
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

    def success(self, message):
        self.stdout.write(self.style.SUCCESS(message), ending="\n")

    def info(self, message):
        self.stdout.write(message, ending="\n")

    def handle(self, *args, **options):
        self.info("Start processing agreements...")
        client = setup_client()
        if options["agreements"]:
            sync_agreements_by_agreement_ids(client, options["agreements"], options["dry_run"])
        elif options["all"]:
            sync_all_agreements(client, options["dry_run"])
        else:
            sync_agreements_by_next_sync(client, options["dry_run"])
            sync_agreements_by_3yc_end_date(client, options["dry_run"])
            sync_agreements_by_coterm_date(client, options["dry_run"])
            sync_agreements_by_renewal_date(client, options["dry_run"])
        self.success("Processing agreements completed.")
