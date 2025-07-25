from adobe_vipm.flows.migration import process_transfers
from adobe_vipm.management.commands.base import AdobeBaseCommand


class Command(AdobeBaseCommand):
    """Process transfer command."""

    help = "Process new and rescheduled tranfers taking data from AirTable bases."

    def handle(self, *args, **options):
        """Run command."""
        self.info("Start processing transfers...")
        process_transfers()
        self.success("Transfer processing completed")
