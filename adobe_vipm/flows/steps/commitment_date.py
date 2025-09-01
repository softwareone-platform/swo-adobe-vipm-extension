from adobe_vipm.flows.fulfillment.shared import save_coterm_dates
from adobe_vipm.flows.fulfillment.transfer import get_commitment_date
from adobe_vipm.flows.pipeline import Step


class SetCommitmentDates(Step):
    """Sets commitment dates for the subscriptions."""

    def __call__(self, client, context, next_step):
        """Update commitments dates in context."""
        context.commitment_date = None

        for subscription in context.subscriptions:
            context.commitment_date = get_commitment_date(subscription, context.commitment_date)

        if context.commitment_date:  # pragma: no branch
            context.order = save_coterm_dates(client, context.order, context.commitment_date)

        next_step(client, context)
