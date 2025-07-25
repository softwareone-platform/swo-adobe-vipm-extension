from django.core.management.base import BaseCommand


class AdobeBaseCommand(BaseCommand):
    """Base Command to share shortcuts for success/info output."""

    def success(self, message: str) -> None:
        """Shortcut for writing message to stdout with success style."""
        self.stdout.write(self.style.SUCCESS(message), ending="\n")

    def info(self, message: str) -> None:
        """Shortcut for writing message to stdout with info style."""
        self.stdout.write(message, ending="\n")

    def warning(self, message: str) -> None:
        """Shortcut for writing message to stdout with warning style."""
        self.stdout.write(self.style.WARNING(message), ending="\n")

    def error(self, message: str) -> None:
        """Shortcut for writing message to stdout with error style."""
        self.stderr.write(self.style.ERROR(message), ending="\n")
