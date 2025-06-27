from django.core.management.base import BaseCommand
from mpt_extension_sdk.core.utils import setup_client

from adobe_vipm.flows.sync import sync_agreements_by_3yc_enroll_status


class Command(BaseCommand):
    help = "Synchronize agreements based on their 3YC enrollment statuses"

    def add_arguments(self, parser):
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
        self.info("Start processing 3YC enrollment statuses...")
        mpt_client = setup_client()
        sync_agreements_by_3yc_enroll_status(mpt_client, options["dry_run"])
        self.success("Processing 3YC enrollment statuses completed.")
