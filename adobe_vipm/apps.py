from django.apps import AppConfig
from django.conf import settings
from django.core.exceptions import ImproperlyConfigured

from .extension import ext


class ExtensionConfig(AppConfig):
    name = "adobe_vipm"
    extension = ext

    def ready(self):
        error_msgs = []

        for product_id in settings.MPT_PRODUCTS_IDS:
            if f"QUERYING_TEMPLATE_ID_{product_id}" not in settings.EXTENSION_CONFIG:
                msg = f"The querying template id for product {product_id} is not found. Please, specify EXT_QUERYING_TEMPLATE_ID_{product_id} environment variable."
                error_msgs.append(msg)

            if f"COMPLETED_TEMPLATE_ID_{product_id}" not in settings.EXTENSION_CONFIG:
                msg = f"The completed template id for product {product_id} is not found. Please, specify EXT_COMPLETED_TEMPLATE_ID_{product_id} environment variable."
                error_msgs.append(msg)

            if f"WEBHOOK_SECRET_{product_id}" not in settings.EXTENSION_CONFIG:
                msg = f"The webhook secret for {product_id} is not found. Please, specify EXT_WEBHOOK_SECRET_{product_id} environment variable."
                error_msgs.append(msg)


        if error_msgs:
            raise ImproperlyConfigured(error_msgs)
