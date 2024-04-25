from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from swo.mpt.extensions.runtime.djapp.apps import DjAppConfig

from .extension import ext


class ExtensionConfig(DjAppConfig):
    name = "adobe_vipm"
    verbose_name = "SWO Adobe VIPM Extension"
    extension = ext

    def extension_ready(self):
        error_msgs = []

        for product_id in settings.MPT_PRODUCTS_IDS:
            if (
                "QUERYING_TEMPLATES_IDS" not in settings.EXTENSION_CONFIG
                or product_id not in settings.EXTENSION_CONFIG["QUERYING_TEMPLATES_IDS"]
            ):
                msg = (
                    f"The querying template id for product {product_id} is not found. "
                    f"Please, specify it in EXT_QUERYING_TEMPLATES_IDS environment variable."
                )
                error_msgs.append(msg)

            if (
                "COMPLETED_TEMPLATES_IDS" not in settings.EXTENSION_CONFIG
                or product_id
                not in settings.EXTENSION_CONFIG["COMPLETED_TEMPLATES_IDS"]
            ):
                msg = (
                    f"The completed template id for product {product_id} is not found. "
                    f"Please, specify it in EXT_COMPLETED_TEMPLATES_IDS environment variable."
                )
                error_msgs.append(msg)

            if (
                "WEBHOOKS_SECRETS" not in settings.EXTENSION_CONFIG
                or product_id not in settings.EXTENSION_CONFIG["WEBHOOKS_SECRETS"]
            ):
                msg = (
                    f"The webhook secret for {product_id} is not found. "
                    f"Please, specify it in EXT_WEBHOOKS_SECRETS environment variable."
                )
                error_msgs.append(msg)

        if error_msgs:
            raise ImproperlyConfigured("\n".join(error_msgs))
