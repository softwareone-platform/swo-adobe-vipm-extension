from django.core.management.base import BaseCommand

from adobe_vipm.flows.migration import check_running_transfers


class Command(BaseCommand):
    help = "Check running tranfers taking data from AirTable bases."

    def handle(self, *args, **options):
        check_running_transfers()
