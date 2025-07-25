from mpt_extension_sdk.core.utils import setup_client

from adobe_vipm.flows.benefits import check_3yc_commitment_request
from adobe_vipm.management.commands.base import AdobeBaseCommand


# TODO: why do we need to have this, because there is 3YC syn enrollments???
class Command(AdobeBaseCommand):
    """Process 3YC requests."""

    help = "Process 3-year commitment and recommitment requests"

    def handle(self, *args, **options):
        """Run command."""
        self.info("Start processing agreements...")
        client = setup_client()
        self.info("Checking pending commitment requests...")
        check_3yc_commitment_request(client, is_recommitment=False)
        self.info("Checking pending recommitment requests...")
        check_3yc_commitment_request(client, is_recommitment=True)
        self.info("Submit recommitment requests...")
        self.success("Processing agreements completed.")
