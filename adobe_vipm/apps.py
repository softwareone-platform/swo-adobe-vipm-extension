from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from swo.mpt.extensions.runtime.djapp.apps import DjAppConfig
from swo.mpt.extensions.runtime.djapp.conf import to_postfix

from .extension import ext


class ExtensionConfig(DjAppConfig):
    name = "adobe_vipm"
    verbose_name = "SWO Adobe VIPM Extension"
    extension = ext

    def extension_ready(self):
        error_msgs = []

        for product_id in settings.MPT_PRODUCTS_IDS:
            postfix = to_postfix(product_id)

            if f"QUERYING_TEMPLATE_ID_{postfix}" not in settings.EXTENSION_CONFIG:
                msg = (
                    f"The querying template id for product {product_id} is not found. "
                    f"Please, specify EXT_QUERYING_TEMPLATE_ID_{postfix} environment variable."
                )
                error_msgs.append(msg)

            if f"COMPLETED_TEMPLATE_ID_{postfix}" not in settings.EXTENSION_CONFIG:
                msg = (
                    f"The completed template id for product {product_id} is not found. "
                    f"Please, specify EXT_COMPLETED_TEMPLATE_ID_{postfix} environment variable."
                )
                error_msgs.append(msg)

            if f"WEBHOOK_SECRET_{postfix}" not in settings.EXTENSION_CONFIG:
                msg = (
                    f"The webhook secret for {product_id} is not found. "
                    f"Please, specify EXT_WEBHOOK_SECRET_{postfix} environment variable."
                )
                error_msgs.append(msg)

        if error_msgs:
            raise ImproperlyConfigured("\n".join(error_msgs))
