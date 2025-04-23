from django.core.management.base import BaseCommand

from adobe_vipm.flows.migration import check_running_transfers


class Command(BaseCommand):
    help = "Check running transfers taking data from AirTable bases."

    def success(self, message):
        self.stdout.write(self.style.SUCCESS(message), ending="\n")

    def info(self, message):
        self.stdout.write(message, ending="\n")

    def handle(self, *args, **options):
        self.info("Start checking running transfers...")
        check_running_transfers()
        self.success("Running transfers check completed")
