import logging

from adobe_vipm.flows.fulfillment import fulfill_order
from swo.mpt.extensions.core import Extension

logger = logging.getLogger(__name__)
ext = Extension()


@ext.events.listener("orders")
def process_order(client, event):
    try:
        fulfill_order(client, event.data)
    except Exception:
        logger.exception("Unhandled exception!")
