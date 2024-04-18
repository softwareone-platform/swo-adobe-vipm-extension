from django.core.management.base import BaseCommand

from adobe_vipm.flows.migration import process_transfers


class Command(BaseCommand):
    help = "Process new and rescheduled tranfers taking data from AirTable bases."

    def handle(self, *args, **options):
        process_transfers()
