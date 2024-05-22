from django.core.management.base import BaseCommand

from adobe_vipm.flows.migration import fix_migrated_autorenewal_off


class Command(BaseCommand):
    help = "Check running tranfers taking data from AirTable bases."

    def success(self, message):
        self.stdout.write(self.style.SUCCESS(message), ending="\n")

    def info(self, message):
        self.stdout.write(message, ending="\n")

    def handle(self, *args, **options):
        self.info("Fix migrated autorenewal...")
        fix_migrated_autorenewal_off()
        self.success("Migrated fixed successfully")
