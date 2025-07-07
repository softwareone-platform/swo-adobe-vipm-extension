from django.core.management.base import BaseCommand

from adobe_vipm.flows.global_customer import check_gc_agreement_deployments


class Command(BaseCommand):
    help = "Create Global Customer Agreement Deployments"

    def success(self, message):
        self.stdout.write(self.style.SUCCESS(message), ending="\n")

    def info(self, message):
        self.stdout.write(message, ending="\n")

    def handle(self, *args, **options):
        self.info("Start processing Global Customer Agreement Deployments synchronization...")
        check_gc_agreement_deployments()
        self.success("Processing Global Customer Agreement Deployments completed.")
