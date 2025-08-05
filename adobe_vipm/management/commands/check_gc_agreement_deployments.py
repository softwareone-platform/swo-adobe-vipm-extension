from adobe_vipm.flows.global_customer import check_gc_agreement_deployments
from adobe_vipm.management.commands.base import AdobeBaseCommand


class Command(AdobeBaseCommand):
    """Create agreements for global customer deployments."""

    help = "Create Global Customer Agreement Deployments"

    def handle(self, *args, **options):
        """Run command."""
        self.info("Start processing Global Customer Agreement Deployments synchronization...")
        check_gc_agreement_deployments()
        self.success("Processing Global Customer Agreement Deployments completed.")
