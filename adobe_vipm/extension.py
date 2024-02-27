from swo.mpt.extensions.core import Extension

from adobe_vipm.flows.fulfillment import fulfill_order

ext = Extension()


@ext.events.listener("orders")
def process_order(client, event):
    fulfill_order(client, event.data)
