import logging

from adobe_vipm.flows.fulfillment.transfer import sync_main_agreement
from adobe_vipm.flows.pipeline import Step
from adobe_vipm.flows.sync import sync_agreements_by_agreement_ids

logger = logging.getLogger(__name__)


class SyncAgreement(Step):
    """Sync agreement."""

    def __call__(self, client, context, next_step):
        """Sync agreement."""
        sync_agreements_by_agreement_ids(
            client, [context.agreement_id], dry_run=False, sync_prices=True
        )
        logger.info("%s: agreement synchoronized", context)
        next_step(client, context)


class SyncGCMainAgreement(Step):
    """Sync Global Customer Main Agreement."""

    def __init__(self, transfer, gc_main_agreement):
        self.gc_main_agreement = gc_main_agreement
        self.transfer = transfer

    def __call__(self, client, context, next_step):
        """Sync global customer main agreement."""
        sync_main_agreement(
            self.gc_main_agreement,
            context.order["agreement"]["product"]["id"],
            context.order["authorization"]["id"],
            self.transfer.customer_id,
        )
        next_step(client, context)
