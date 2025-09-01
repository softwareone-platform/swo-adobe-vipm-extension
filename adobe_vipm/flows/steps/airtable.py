import datetime as dt

from adobe_vipm.flows.pipeline import Step


class UpdateTransferStatus(Step):
    """Step to update transfer status in Airtable."""

    # TODO: Why transfer not in the context???
    def __init__(self, transfer, status):
        self.transfer = transfer
        self.status = status

    def __call__(self, client, context, next_step):
        """Step to update transfer status in Airtable."""
        self.transfer.status = self.status
        self.transfer.mpt_order_id = context.order["id"]
        self.transfer.synchronized_at = dt.datetime.now(tz=dt.UTC)
        self.transfer.save()

        next_step(client, context)
