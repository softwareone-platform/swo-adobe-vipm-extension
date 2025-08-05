from adobe_vipm.flows.migration import check_running_transfers
from adobe_vipm.management.commands.base import AdobeBaseCommand


class Command(AdobeBaseCommand):
    """Check for running transfers in Airtable."""

    help = "Check running transfers taking data from AirTable bases."

    def handle(self, *args, **options):
        """Run command."""
        self.info("Start checking running transfers...")
        check_running_transfers()
        self.success("Running transfers check completed")
