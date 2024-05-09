from django.core.management.base import BaseCommand
from swo.mpt.extensions.core.utils import setup_client

from adobe_vipm.flows.sync import sync_prices


class Command(BaseCommand):
    help = "Synchronize agreements on anniversary."

    def success(self, message):
        self.stdout.write(self.style.SUCCESS(message), ending="\n")

    def info(self, message):
        self.stdout.write(message, ending="\n")

    def handle(self, *args, **options):
        self.info("Start processing agreements...")
        client = setup_client()
        sync_prices(client)
        self.success("Processing agreements completed.")
