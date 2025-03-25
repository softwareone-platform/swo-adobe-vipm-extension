from django.core.management.base import BaseCommand
from mpt_extension_sdk.core.utils import setup_client

from adobe_vipm.flows.benefits import (
    check_3yc_commitment_request,
)


class Command(BaseCommand):
    help = "Process 3-year commitment and recommitment requests"

    def success(self, message):
        self.stdout.write(self.style.SUCCESS(message), ending="\n")

    def info(self, message):
        self.stdout.write(message, ending="\n")

    def handle(self, *args, **options):
        self.info("Start processing agreements...")
        client = setup_client()
        self.info("Checking pending commitment requests...")
        check_3yc_commitment_request(client)
        self.info("Checking pending recommitment requests...")
        check_3yc_commitment_request(client, is_recommitment=True)
        self.info("Submit recommitment requests...")
        self.success("Processing agreements completed.")
