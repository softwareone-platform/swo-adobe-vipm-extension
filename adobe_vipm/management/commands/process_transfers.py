from django.core.management.base import BaseCommand

from adobe_vipm.flows.migration import process_transfers


class Command(BaseCommand):
    help = "Process new and rescheduled tranfers taking data from AirTable bases."

    def success(self, message):
        self.stdout.write(self.style.SUCCESS(message), ending="\n")

    def info(self, message):
        self.stdout.write(message, ending="\n")

    def handle(self, *args, **options):
        self.info("Start processing transfers...")
        process_transfers()
        self.success("Transfer processing completed")
