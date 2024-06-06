from django.core.management.base import BaseCommand
from swo.mpt.extensions.core.utils import setup_client

from adobe_vipm.flows.sync import (
    sync_agreements_by_agreement_ids,
    sync_agreements_by_next_sync,
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
            "--allow-3yc",
            action="store_true",
            default=False,
            help="Allow synchronization for customers that commited for 3y",
        )

    def success(self, message):
        self.stdout.write(self.style.SUCCESS(message), ending="\n")

    def info(self, message):
        self.stdout.write(message, ending="\n")

    def handle(self, *args, **options):
        self.info("Start processing agreements...")
        client = setup_client()
        if options["agreements"]:
            sync_agreements_by_agreement_ids(client, options["agreements"], options["allow_3yc"])
        elif options["all"]:
            sync_all_agreements(client, options["allow_3yc"])
        else:
            sync_agreements_by_next_sync(client, options["allow_3yc"])
        self.success("Processing agreements completed.")
