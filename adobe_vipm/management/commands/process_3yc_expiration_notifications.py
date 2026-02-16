import datetime as dt
import logging

from mpt_extension_sdk.core.utils import setup_client
from mpt_extension_sdk.mpt_http.mpt import get_agreements_by_query

from adobe_vipm.flows.benefits import send_3yc_expiration_notification
from adobe_vipm.flows.constants import Param
from adobe_vipm.management.commands.base import AdobeBaseCommand

logger = logging.getLogger(__name__)


def notify_3yc_expirations(number_of_days):
    """Notify 3YC expirations."""
    client = setup_client()
    today = dt.datetime.now(dt.UTC).date()
    target_date = (today + dt.timedelta(days=number_of_days)).isoformat()

    rql = (
        f"and(eq(status,'Active'),"
        f"any(parameters.fulfillment,and("
        f"eq(externalId,'{Param.THREE_YC_END_DATE.value}'),"
        f"in(displayValue,({target_date}))"
        f")))&select=parameters"
    )

    agreements = get_agreements_by_query(client, rql)
    for agreement in agreements:
        send_3yc_expiration_notification(
            client, agreement, number_of_days, "notification_3yc_expiring"
        )


class Command(AdobeBaseCommand):
    """Notify 3YC expirations."""

    help = "Notify 3YC expirations."

    def add_arguments(self, parser):
        """Add required arguments."""
        parser.add_argument(
            "--number_of_days",
            type=int,
            metavar="NUMBER_OF_DAYS",
            default=0,
            help="Number of days offset for notification (e.g. 30)",
        )

    def handle(self, *args, **options):
        """Run command."""
        self.info("Start notifying 3YC expirations...")
        notify_3yc_expirations(options["number_of_days"])
        self.success("Notifying 3YC expirations completed.")
